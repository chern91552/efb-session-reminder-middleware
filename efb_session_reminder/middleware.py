# coding=utf-8
"""
Session Reminder Middleware
Reminds users before WeChat session expires to prevent unexpected disconnections.
Supports pre-emptive QR code generation for seamless re-login.
"""

import json
import logging
import threading
import time
import uuid
import io
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional, Dict, Any, List

from ehforwarderbot import Middleware, Message, MsgType, Status, coordinator, Channel
from ehforwarderbot.types import ModuleID, InstanceID, ChatID
from ehforwarderbot.utils import extra, get_data_path, get_config_path
from ehforwarderbot.chat import SystemChat

try:
    from pyqrcode import QRCode as PyQRCode
except ImportError:
    PyQRCode = None


class SessionReminderMiddleware(Middleware):
    """
    A middleware that monitors WeChat session status and sends reminders
    before the session expires.

    Features:
    - Monitors session validity period (default 30 days for WeChat Web)
    - Sends progressive reminders (5 days, 3 days, 1 day, hours before)
    - Pre-emptive QR code generation for seamless re-login
    - Respects quiet hours to avoid midnight notifications
    - Provides commands to check session status
    - Supports multiple slave channels
    - Multi-channel delivery (Telegram, WeChat, or both)
    """

    middleware_id: ModuleID = ModuleID("efb_session_reminder")
    middleware_name: str = "Session Reminder Middleware"
    __version__: str = '1.4.0'

    DEFAULT_SESSION_VALIDITY_DAYS = 30
    DEFAULT_REMINDER_THRESHOLDS = [5, 3, 1]
    DEFAULT_QUIET_HOURS = (0, 8)
    DEFAULT_CHECK_INTERVAL = 3600
    DEFAULT_QR_THRESHOLD_DAYS = 3

    def __init__(self, instance_id: Optional[InstanceID] = None):
        super().__init__(instance_id=instance_id)

        self.logger = logging.getLogger(f"EFB.middleware.{self.middleware_id}")

        self.data_path: Path = get_data_path(self.middleware_id)
        self.config: Dict[str, Any] = self._load_config()

        self.enabled: bool = self.config.get('enabled', True)
        self.session_validity_days: int = self.config.get('session_validity_days',
                                                           self.DEFAULT_SESSION_VALIDITY_DAYS)
        self.reminder_thresholds: list = self.config.get('reminder_thresholds',
                                                          self.DEFAULT_REMINDER_THRESHOLDS)
        self.quiet_hours: tuple = tuple(self.config.get('quiet_hours', list(self.DEFAULT_QUIET_HOURS)))
        self.check_interval: int = self.config.get('check_interval', self.DEFAULT_CHECK_INTERVAL)
        self.monitored_channels: list = self.config.get('monitored_channels', ['blueset.wechat'])

        # QR code configuration
        self.qr_threshold_days: int = self.config.get('qr_threshold_days',
                                                        self.DEFAULT_QR_THRESHOLD_DAYS)
        self.auto_qr: bool = self.config.get('auto_qr', True)

        # Channel delivery configuration
        # Options: 'telegram', 'wechat', 'both'
        self.delivery_channels: List[str] = self.config.get('delivery_channels', ['telegram', 'wechat'])
        # WeChat recipient for reminders (can be username, remark, or 'filehelper')
        self.wechat_recipient: str = self.config.get('wechat_recipient', 'filehelper')

        self._login_times: Dict[str, datetime] = {}
        self._last_reminder: Dict[str, Dict[int, datetime]] = {}

        self._load_login_times()

        self._stop_event = threading.Event()
        self._reminder_thread: Optional[threading.Thread] = None

        if self.enabled:
            self._start_reminder_thread()

        self.logger.info(f"Session Reminder Middleware initialized (enabled={self.enabled})")

    def _load_config(self) -> Dict[str, Any]:
        config_path = get_config_path(self.middleware_id)
        config = {}

        if config_path.exists():
            try:
                from ruamel.yaml import YAML
                yaml = YAML()
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.load(f) or {}
                self.logger.info(f"Configuration loaded from {config_path}")
            except Exception as e:
                self.logger.error(f"Failed to load configuration: {e}")

        return config

    def _load_login_times(self):
        login_file = self.data_path / "login_times.json"
        if login_file.exists():
            try:
                with open(login_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for channel_id, time_str in data.items():
                        self._login_times[channel_id] = datetime.fromisoformat(time_str)
                self.logger.info(f"Loaded login times for {len(self._login_times)} channels")
            except Exception as e:
                self.logger.error(f"Failed to load login times: {e}")

    def _save_login_times(self):
        login_file = self.data_path / "login_times.json"
        try:
            data = {
                channel_id: dt.isoformat()
                for channel_id, dt in self._login_times.items()
            }
            with open(login_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self.logger.debug("Login times saved")
        except Exception as e:
            self.logger.error(f"Failed to save login times: {e}")

    def _start_reminder_thread(self):
        self._reminder_thread = threading.Thread(
            target=self._reminder_loop,
            name=f"{self.middleware_id}.reminder",
            daemon=True
        )
        self._reminder_thread.start()
        self.logger.info("Reminder thread started")

    def _reminder_loop(self):
        time.sleep(30)

        while not self._stop_event.is_set():
            try:
                self._check_all_sessions()
            except Exception as e:
                self.logger.error(f"Error in reminder loop: {e}", exc_info=True)

            self._stop_event.wait(self.check_interval)

    def _check_all_sessions(self):
        now = datetime.now()

        for channel_id in self.monitored_channels:
            if channel_id not in self._login_times:
                self.logger.debug(f"No login time recorded for {channel_id}")
                continue

            login_time = self._login_times[channel_id]
            expiry_time = login_time + timedelta(days=self.session_validity_days)
            days_remaining = (expiry_time - now).days

            self.logger.debug(f"Channel {channel_id}: {days_remaining} days remaining")

            for threshold in sorted(self.reminder_thresholds, reverse=True):
                if days_remaining <= threshold:
                    if self._should_send_reminder(channel_id, threshold, now):
                        qr_image = None
                        if self.auto_qr and days_remaining <= self.qr_threshold_days:
                            qr_image = self._get_preemptive_qr_code(channel_id)

                        self._send_reminder(channel_id, days_remaining, expiry_time, qr_image)
                        self._mark_reminder_sent(channel_id, threshold, now)
                    break

    def _get_preemptive_qr_code(self, channel_id: str) -> Optional[io.BytesIO]:
        """Get a pre-emptive QR code for re-login."""
        try:
            if channel_id != 'blueset.wechat':
                self.logger.debug(f"Pre-emptive QR not supported for {channel_id}")
                return None

            if not hasattr(coordinator, 'slaves') or channel_id not in coordinator.slaves:
                self.logger.warning(f"WeChat slave channel not available")
                return None

            wechat_channel = coordinator.slaves[channel_id]

            if not hasattr(wechat_channel, 'bot') or not wechat_channel.bot:
                self.logger.warning("WeChat bot not available")
                return None

            bot = wechat_channel.bot

            import requests

            cookies = bot.s.cookies.get_dict()
            if 'wxuin' not in cookies:
                self.logger.warning("No wxuin cookie found, cannot generate pre-emptive QR")
                return None

            base_url = "https://wx.qq.com"
            url = f"{base_url}/cgi-bin/mmwebwx-bin/webwxpushloginurl?uin={cookies['wxuin']}"
            headers = {'User-Agent': bot.user_agent}

            response = bot.s.get(url, headers=headers)

            try:
                result = response.json()
            except Exception:
                self.logger.error(f"Push login response is not valid JSON: {response.content}")
                return None

            if 'uuid' not in result or result.get('ret') not in (0, '0'):
                self.logger.warning(f"Push login failed: {result}")
                return None

            uuid_str = result['uuid']
            self.logger.info(f"Got pre-emptive login UUID: {uuid_str}")

            if PyQRCode is None:
                self.logger.warning("pyqrcode not installed, cannot generate QR image")
                return None

            qr_url = f"https://login.weixin.qq.com/l/{uuid_str}"
            qr_code = PyQRCode(qr_url)

            qr_image = io.BytesIO()
            qr_code.png(qr_image, scale=10)
            qr_image.seek(0)

            return qr_image

        except Exception as e:
            self.logger.error(f"Failed to get pre-emptive QR code: {e}", exc_info=True)
            return None

    def _should_send_reminder(self, channel_id: str, threshold: int, now: datetime) -> bool:
        if self._is_quiet_hours(now):
            self.logger.debug("Skipping reminder during quiet hours")
            return False

        if channel_id in self._last_reminder:
            if threshold in self._last_reminder[channel_id]:
                last_time = self._last_reminder[channel_id][threshold]
                if last_time.date() == now.date():
                    return False

        return True

    def _is_quiet_hours(self, now: datetime) -> bool:
        """Check if current time is within quiet hours."""
        current_hour = now.hour
        start_hour, end_hour = self.quiet_hours

        if start_hour <= end_hour:
            # Same day range (e.g., [0, 8] means 0:00 to 8:00)
            return start_hour <= current_hour < end_hour
        else:
            # Cross-midnight range (e.g., [23, 8] means 23:00 to 8:00 next day)
            return current_hour >= start_hour or current_hour < end_hour

    def _send_reminder(self, channel_id: str, days_remaining: int, expiry_time: datetime,
                       qr_image: Optional[io.BytesIO] = None):
        try:
            if days_remaining <= 1:
                urgency = "🔴 紧急"
                level = "critical"
            elif days_remaining <= 3:
                urgency = "🟡 警告"
                level = "warning"
            else:
                urgency = "🟢 提醒"
                level = "info"

            channel_name = self._get_channel_name(channel_id)

            if days_remaining <= 0:
                text = (
                    f"{urgency} 会话已过期\n\n"
                    f"您的 {channel_name} 会话已过期。\n"
                    f"请尽快重新登录以恢复消息收发。\n\n"
                    f"过期时间: {expiry_time.strftime('%Y-%m-%d %H:%M')}"
                )
            elif days_remaining == 1:
                text = (
                    f"{urgency} 会话即将过期\n\n"
                    f"您的 {channel_name} 会话将在明天过期。\n"
                    f"请尽快重新登录，避免消息收发中断。\n\n"
                    f"过期时间: {expiry_time.strftime('%Y-%m-%d %H:%M')}\n"
                    f"剩余时间: 约 {(expiry_time - datetime.now()).total_seconds() / 3600:.1f} 小时"
                )
            else:
                text = (
                    f"{urgency} 会话过期提醒\n\n"
                    f"您的 {channel_name} 会话将在 {days_remaining} 天后过期。\n"
                    f"建议您在方便时重新登录以延长会话有效期。\n\n"
                    f"过期时间: {expiry_time.strftime('%Y-%m-%d %H:%M')}"
                )

            if qr_image and self.auto_qr:
                text += "\n\n📱 扫描下方二维码可提前登录续期："

            text += "\n\n💡 发送 'getqr' 可获取新的登录二维码"

            # Send to configured channels
            if 'telegram' in self.delivery_channels:
                self._send_to_telegram(text, level)

            if 'wechat' in self.delivery_channels:
                self._send_to_wechat(text, qr_image if (qr_image and self.auto_qr) else None)

            if qr_image and self.auto_qr:
                if 'telegram' in self.delivery_channels:
                    self._send_qr_to_telegram(qr_image)
                if 'wechat' in self.delivery_channels:
                    self._send_qr_to_wechat(qr_image)

            self.logger.info(f"Reminder sent for {channel_id}: {days_remaining} days remaining")

        except Exception as e:
            self.logger.error(f"Failed to send reminder: {e}", exc_info=True)

    def _send_to_telegram(self, text: str, level: str = "info"):
        """Send message to Telegram."""
        try:
            system_chat = SystemChat(
                channel=coordinator.master,
                name="会话提醒助手",
                uid=ChatID(f"__session_reminder_{uuid.uuid4()}__")
            )

            msg = Message(
                uid=f"__session_reminder_{time.time()}__",
                type=MsgType.Text,
                chat=system_chat,
                author=system_chat.other,
                text=text,
                deliver_to=coordinator.master
            )

            coordinator.send_message(msg)
            self.logger.debug("Telegram message sent")

        except Exception as e:
            self.logger.error(f"Failed to send to Telegram: {e}", exc_info=True)

    def _send_to_wechat(self, text: str, qr_image: Optional[io.BytesIO] = None):
        """Send message to WeChat."""
        try:
            if not hasattr(coordinator, 'slaves') or 'blueset.wechat' not in coordinator.slaves:
                self.logger.warning("WeChat slave channel not available")
                return

            wechat_channel = coordinator.slaves['blueset.wechat']

            if not hasattr(wechat_channel, 'bot') or not wechat_channel.bot:
                self.logger.warning("WeChat bot not available")
                return

            bot = wechat_channel.bot

            # Find the recipient chat
            recipient = None
            recipient_display = self.wechat_recipient

            if self.wechat_recipient.lower() == 'filehelper':
                try:
                    recipient = bot.file_helper
                    recipient_display = "文件传输助手"
                except Exception as e:
                    self.logger.error(f"Failed to get file_helper: {e}")
                    return
            else:
                # Try to search by name or username
                try:
                    search_results = bot.search(self.wechat_recipient)
                    if search_results:
                        recipient = search_results[0]
                    else:
                        self.logger.warning(f"WeChat recipient '{self.wechat_recipient}' not found")
                        return
                except Exception as e:
                    self.logger.error(f"Failed to search for recipient: {e}")
                    return

            # Send the message
            recipient.send_msg(text)
            self.logger.info(f"WeChat message sent to {recipient_display}")

        except Exception as e:
            self.logger.error(f"Failed to send to WeChat: {e}", exc_info=True)

    def _send_qr_to_telegram(self, qr_image: io.BytesIO):
        """Send QR code image to Telegram."""
        try:
            system_chat = SystemChat(
                channel=coordinator.master,
                name="会话提醒助手",
                uid=ChatID(f"__session_reminder_qr_{uuid.uuid4()}__")
            )

            temp_file = NamedTemporaryFile(suffix=".png", delete=False)
            temp_file.write(qr_image.getvalue())
            temp_file.close()

            msg = Message(
                uid=f"__session_qr_{time.time()}__",
                type=MsgType.Image,
                chat=system_chat,
                author=system_chat.other,
                text="登录二维码 - 请使用微信扫码",
                path=Path(temp_file.name),
                file=open(temp_file.name, 'rb'),
                mime='image/png',
                deliver_to=coordinator.master
            )

            coordinator.send_message(msg)
            self.logger.info("QR code sent to Telegram")

        except Exception as e:
            self.logger.error(f"Failed to send QR to Telegram: {e}", exc_info=True)

    def _send_qr_to_wechat(self, qr_image: io.BytesIO):
        """Send QR code image to WeChat."""
        try:
            if not hasattr(coordinator, 'slaves') or 'blueset.wechat' not in coordinator.slaves:
                return

            wechat_channel = coordinator.slaves['blueset.wechat']

            if not hasattr(wechat_channel, 'bot') or not wechat_channel.bot:
                return

            bot = wechat_channel.bot

            recipient = None
            recipient_display = self.wechat_recipient

            if self.wechat_recipient.lower() == 'filehelper':
                recipient = bot.file_helper
                recipient_display = "文件传输助手"
            else:
                search_results = bot.search(self.wechat_recipient)
                if search_results:
                    recipient = search_results[0]

            if recipient:
                # Save QR image to temp file and send
                temp_file = NamedTemporaryFile(suffix=".png", delete=False)
                temp_file.write(qr_image.getvalue())
                temp_file.close()

                recipient.send_image(temp_file.name)
                self.logger.info(f"QR code sent to WeChat {recipient_display}")

        except Exception as e:
            self.logger.error(f"Failed to send QR to WeChat: {e}", exc_info=True)

    def _get_channel_name(self, channel_id: str) -> str:
        channel_names = {
            'blueset.wechat': '微信网页版',
            'blueset.telegram': 'Telegram',
        }
        return channel_names.get(channel_id, channel_id)

    def _mark_reminder_sent(self, channel_id: str, threshold: int, now: datetime):
        if channel_id not in self._last_reminder:
            self._last_reminder[channel_id] = {}
        self._last_reminder[channel_id][threshold] = now

    def sent_by_master(self, message: Message) -> bool:
        """Check if message is sent by master channel."""
        author = message.author
        return author and hasattr(author, 'module_id') and author.module_id == coordinator.master.channel_id

    def process_message(self, message: Message) -> Optional[Message]:
        if not self.enabled:
            return message

        try:
            # Detect login events from messages sent to master (Telegram)
            if message.deliver_to == coordinator.master:
                self._detect_login_event(message)

            # Handle commands from both Telegram and WeChat
            if hasattr(message, 'text') and message.text:
                text = message.text.strip().lower()

                # Check if this is a command we should handle
                is_command = text in ['session', '会话状态', '/session'] or \
                             text.startswith('setlogintime ') or \
                             text in ['getqr', '获取二维码', 'qr']

                if is_command:
                    # Handle commands from Telegram (sent to slave channels)
                    if message.deliver_to != coordinator.master:
                        self._handle_command(text, message, source='telegram')
                        return None

                    # Handle commands from WeChat (sent to master channel)
                    # Check if the message is sent to the configured recipient
                    if message.deliver_to == coordinator.master:
                        # Check if this is a message to filehelper or configured recipient
                        if self._is_command_to_recipient(message):
                            self._handle_command(text, message, source='wechat')
                            return None

        except Exception as e:
            self.logger.error(f"Error processing message: {e}", exc_info=True)

        return message

    def _is_command_to_recipient(self, message: Message) -> bool:
        """Check if the message is sent to the configured WeChat recipient."""
        try:
            # Get the chat/recipient of this message
            chat = message.chat

            # Check if this is filehelper
            if self.wechat_recipient.lower() == 'filehelper':
                # File helper's UID is typically 'filehelper'
                if hasattr(chat, 'uid') and chat.uid.lower() == 'filehelper':
                    return True
                # Also check by name
                if hasattr(chat, 'name') and '文件传输助手' in chat.name:
                    return True

            # Check if this matches the configured recipient name
            if hasattr(chat, 'name') and chat.name == self.wechat_recipient:
                return True
            if hasattr(chat, 'alias') and chat.alias == self.wechat_recipient:
                return True

            return False
        except Exception as e:
            self.logger.error(f"Error checking recipient: {e}")
            return False

    def _handle_command(self, text: str, message: Message, source: str = 'telegram'):
        """Handle commands from different sources."""
        if text in ['session', '会话状态', '/session']:
            self._handle_status_command(message, source)
        elif text.startswith('setlogintime '):
            self._handle_set_login_time_command(message, source)
        elif text in ['getqr', '获取二维码', 'qr']:
            self._handle_get_qr_command(message, source)

    def _detect_login_event(self, message: Message):
        if message.type == MsgType.Text and message.text:
            text = message.text.lower()

            # Comprehensive login patterns to detect successful login
            login_patterns = [
                # English patterns (from efb-wechat-slave)
                'successfully logged in',
                'login successful',
                'logged in',
                'qr code login successful',

                # Chinese patterns
                '登录成功',
                '已登录',
                '扫码登录成功',
                '登陆成功',

                # Additional patterns
                're-authenticated',
                'reauthenticated',
                'session renewed',
                '二维码登录成功',
                'qrcode scanned',
                'scan successful'
            ]

            for pattern in login_patterns:
                if pattern in text:
                    channel_id = getattr(message.author, 'channel_id', None)
                    if channel_id:
                        self.logger.info(f"Login event detected for {channel_id}: matched pattern '{pattern}'")
                        self._record_login(channel_id)
                    break

    def _record_login(self, channel_id: str, source: str = 'telegram'):
        now = datetime.now()
        self._login_times[channel_id] = now
        self._save_login_times()
        self._last_reminder[channel_id] = {}

        self.logger.info(f"Login recorded for {channel_id} at {now}")

        expiry = now + timedelta(days=self.session_validity_days)
        text = (
            f"✅ 登录已记录\n\n"
            f"频道: {self._get_channel_name(channel_id)}\n"
            f"登录时间: {now.strftime('%Y-%m-%d %H:%M')}\n"
            f"预计过期: {expiry.strftime('%Y-%m-%d %H:%M')}\n"
            f"有效期: {self.session_validity_days} 天"
        )

        if source == 'telegram' or 'telegram' in self.delivery_channels:
            self._send_to_telegram(text, "info")
        if source == 'wechat' or 'wechat' in self.delivery_channels:
            self._send_to_wechat(text)

    def _handle_status_command(self, message: Message, source: str = 'telegram'):
        status_text = self._get_status_report()
        if source == 'telegram' or 'telegram' in self.delivery_channels:
            self._send_to_telegram(status_text, "info")
        if source == 'wechat' or 'wechat' in self.delivery_channels:
            self._send_to_wechat(status_text)

    def _handle_set_login_time_command(self, message: Message, source: str = 'telegram'):
        try:
            parts = message.text.strip().split(maxsplit=1)
            if len(parts) < 2:
                error_msg = "用法: setlogintime <频道ID>\n示例: setlogintime blueset.wechat"
                if source == 'telegram':
                    self._send_to_telegram(error_msg, "warning")
                else:
                    self._send_to_wechat(error_msg)
                return

            channel_id = parts[1].strip()
            self._record_login(channel_id, source)

        except Exception as e:
            self.logger.error(f"Error handling setlogintime command: {e}")
            error_msg = f"设置登录时间失败: {e}"
            if source == 'telegram':
                self._send_to_telegram(error_msg, "error")
            else:
                self._send_to_wechat(error_msg)

    def _handle_get_qr_command(self, message: Message, source: str = 'telegram'):
        """Handle the get QR code command."""
        # Send status message
        status_msg = "正在获取登录二维码..."
        if source == 'telegram':
            self._send_to_telegram(status_msg, "info")
        else:
            self._send_to_wechat(status_msg)

        qr_image = self._get_preemptive_qr_code('blueset.wechat')

        if qr_image:
            text = (
                "📱 登录二维码\n\n"
                "请使用微信扫描下方二维码登录。\n"
                "扫码后，当前会话将被新会话替换，消息不会中断。"
            )

            # Send to the source channel
            if source == 'telegram':
                self._send_to_telegram(text, "info")
                self._send_qr_to_telegram(qr_image)
            else:
                self._send_to_wechat(text)
                self._send_qr_to_wechat(qr_image)
        else:
            error_msg = (
                "❌ 获取二维码失败\n\n"
                "可能的原因：\n"
                "1. 微信会话已过期，请使用 /reauth 命令重新登录\n"
                "2. 网络连接问题\n"
                "3. 微信服务器暂时不可用\n\n"
                "请尝试使用 /reauth 命令手动重新登录。"
            )
            if source == 'telegram':
                self._send_to_telegram(error_msg, "warning")
            else:
                self._send_to_wechat(error_msg)

    def _get_status_report(self) -> str:
        now = datetime.now()
        lines = ["📊 会话状态报告", "", f"当前时间: {now.strftime('%Y-%m-%d %H:%M')}", ""]

        for channel_id in self.monitored_channels:
            channel_name = self._get_channel_name(channel_id)

            if channel_id in self._login_times:
                login_time = self._login_times[channel_id]
                expiry_time = login_time + timedelta(days=self.session_validity_days)
                days_remaining = (expiry_time - now).days
                hours_remaining = (expiry_time - now).total_seconds() / 3600

                if days_remaining > 5:
                    status = "✅ 正常"
                elif days_remaining > 2:
                    status = "🟡 即将过期"
                elif days_remaining > 0:
                    status = "🟠 需要关注"
                else:
                    status = "🔴 已过期"

                lines.append(f"【{channel_name}】")
                lines.append(f"  状态: {status}")
                lines.append(f"  登录时间: {login_time.strftime('%Y-%m-%d %H:%M')}")
                lines.append(f"  过期时间: {expiry_time.strftime('%Y-%m-%d %H:%M')}")

                if days_remaining > 0:
                    lines.append(f"  剩余时间: {days_remaining} 天 ({hours_remaining:.1f} 小时)")
                else:
                    lines.append(f"  已过期: {abs(days_remaining)} 天")

                lines.append("")
            else:
                lines.append(f"【{channel_name}】")
                lines.append(f"  状态: ❓ 未记录登录时间")
                lines.append("")

        lines.append("💡 提示:")
        lines.append("  发送 'session' 或 '会话状态' 查看此报告")
        lines.append("  发送 'getqr' 获取登录二维码（提前续期）")
        lines.append("  发送 'setlogintime <频道ID>' 手动设置登录时间")

        return "\n".join(lines)

    def process_status(self, status: Status) -> Optional[Status]:
        return status

    @extra(name="会话状态",
           desc="查看所有监控频道的会话状态。\n"
                "用法: {function_name}")
    def status(self, args: str = "") -> str:
        return self._get_status_report()

    @extra(name="设置登录时间",
           desc="手动设置某个频道的登录时间。\n"
                "用法: {function_name} <频道ID>\n"
                "示例: {function_name} blueset.wechat")
    def set_login_time(self, args: str) -> str:
        if not args:
            return "请提供频道ID。用法: set_login_time <频道ID>"

        channel_id = args.strip()
        self._record_login(channel_id)
        return f"已记录 {channel_id} 的登录时间。"

    @extra(name="获取登录二维码",
           desc="获取微信登录二维码，可提前扫码续期。\n"
                "用法: {function_name}")
    def get_qr(self, args: str = "") -> str:
        """Extra function to get QR code."""
        qr_image = self._get_preemptive_qr_code('blueset.wechat')

        if qr_image:
            return "登录二维码已发送，请查看消息。"
        else:
            return "获取二维码失败，请检查日志或使用 /reauth 命令重新登录。"

    @extra(name="刷新状态",
           desc="强制检查所有会话状态并发送提醒。\n"
                "用法: {function_name}")
    def force_check(self, args: str = "") -> str:
        try:
            self._check_all_sessions()
            return "已触发会话检查。"
        except Exception as e:
            return f"检查失败: {e}"

    def __del__(self):
        if hasattr(self, '_stop_event'):
            self._stop_event.set()
        self.logger.info("Session Reminder Middleware stopped")