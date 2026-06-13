# coding=utf-8
"""
EFB Session Reminder Middleware
A middleware that reminds users before WeChat session expires.
"""

from .__version__ import __version__
from .middleware import SessionReminderMiddleware

__all__ = ['SessionReminderMiddleware', '__version__']
