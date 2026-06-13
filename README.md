# EFB Session Reminder Middleware

<p align="center">
  <strong>微信会话过期提醒中间件</strong>
</p>

<p align="center">
  <a href="#功能特点">功能特点</a> •
  <a href="#安装">安装</a> •
  <a href="#配置">配置</a> •
  <a href="#使用">使用</a> •
  <a href="#许可证">许可证</a>
</p>

---

## 功能特点

- ⏰ **智能提醒** - 在会话过期前自动发送提醒
- 🔇 **静默时段** - 支持设置静默时段，避免半夜打扰
- 📊 **状态查询** - 随时查看所有监控频道的会话状态
- ⚙️ **灵活配置** - 支持自定义提醒阈值、检查间隔等
- 🔄 **自动检测** - 自动检测登录事件并记录登录时间
- 📱 **多频道支持** - 支持同时监控多个从频道

## 背景

微信网页版登录有效期通常为30天，过期后需要重新扫码登录。如果会话在半夜过期，可能会导致：
- 错过重要消息
- 需要半夜起来重新登录
- 消息收发中断

本中间件通过提前提醒用户，让您可以在方便的时间重新登录，避免这些问题。

## 安装

### 方法一：通过 pip 安装

```bash
pip install efb-session-reminder-middleware
```

### 方法二：从源码安装

```bash
git clone https://github.com/yourusername/efb-session-reminder-middleware.git
cd efb-session-reminder-middleware
pip install .
```

## 配置

### 1. 在 EFB 配置文件中启用中间件

编辑 `~/.ehforwarderbot/profiles/default/config.yaml`：

```yaml
master_channel: blueset.telegram
slave_channels:
  - blueset.wechat
middlewares:
  - efb_session_reminder  # 添加此行
```

### 2. 配置中间件（可选）

创建 `~/.ehforwarderbot/profiles/default/efb_session_reminder/config.yaml`：

```yaml
# 是否启用
enabled: true

# 会话有效期（天数）
session_validity_days: 30

# 提醒阈值（过期前几天）
reminder_thresholds:
  - 5  # 5天前提醒
  - 3  # 3天前提醒
  - 1  # 1天前提醒

# 静默时段（不发送提醒的时间）
quiet_hours:
  - 0   # 开始时间（凌晨）
  - 8   # 结束时间（早上8点）

# 检查间隔（秒）
check_interval: 3600

# 监控的频道
monitored_channels:
  - blueset.wechat
```

## 使用

### 自动提醒

中间件会在以下情况自动发送提醒：
- 会话即将过期（根据配置的阈值）
- 检测到登录成功事件

### 手动查询状态

在 Telegram 中发送以下命令：

| 命令 | 说明 |
|------|------|
| `session` 或 `会话状态` | 查看所有监控频道的会话状态 |
| `setlogintime <频道ID>` | 手动设置登录时间 |

### 额外功能

通过 EFB 的额外功能接口调用：

```
会话状态
设置登录时间 blueset.wechat
刷新状态
```

## 提醒级别

| 剩余时间 | 级别 | 图标 |
|---------|------|------|
| > 5天 | 正常 | 🟢 |
| 3-5天 | 提醒 | 🟢 |
| 1-3天 | 警告 | 🟡 |
| < 1天 | 紧急 | 🔴 |
| 已过期 | 过期 | 🔴 |

## 示例输出

### 状态报告

```
📊 会话状态报告

当前时间: 2024-01-15 14:30

【微信网页版】
  状态: 🟡 即将过期
  登录时间: 2023-12-20 10:00
  过期时间: 2024-01-19 10:00
  剩余时间: 4 天 (91.5 小时)

💡 提示:
  发送 'session' 或 '会话状态' 查看此报告
  发送 'setlogintime <频道ID>' 手动设置登录时间
```

### 提醒消息

```
🟡 警告 会话过期提醒

您的 微信网页版 会话将在 3 天后过期。
建议您在方便时重新登录以延长会话有效期。

过期时间: 2024-01-19 10:00
```

## 常见问题

### Q: 如何手动更新登录时间？

A: 发送 `setlogintime blueset.wechat` 命令，或者在微信频道重新登录。

### Q: 提醒时间可以自定义吗？

A: 可以，在配置文件中修改 `reminder_thresholds` 参数。

### Q: 如何关闭半夜的提醒？

A: 在配置文件中设置 `quiet_hours`，例如 `[0, 8]` 表示凌晨0点到8点不发送提醒。

### Q: 支持监控多个频道吗？

A: 支持，在配置文件的 `monitored_channels` 列表中添加多个频道ID即可。

## 许可证

本项目采用 GNU General Public License v3.0 许可证。

## 贡献

欢迎提交 Issue 和 Pull Request！

---

<p align="center">
  Made with ❤️ for EFB users
</p>
