"""Messaging adapters — outbound SMS, one vendor per organization row.

Importing this package registers every built-in route in
:data:`~src.integrations.messaging.base.MessagingAdapters`. Services resolve
by name and never import a vendor module directly.
"""

from src.integrations.messaging.base import (
    BaseMessagingAdapter,
    CallbackVerdict,
    MessagingAdapters,
    MessagingCapabilities,
    MessagingConfig,
    build_messaging,
)
from src.integrations.messaging.mamonty import MamontyMessagingAdapter
from src.integrations.messaging.twilio import TwilioMessagingAdapter

__all__ = [
    "BaseMessagingAdapter",
    "CallbackVerdict",
    "MamontyMessagingAdapter",
    "MessagingAdapters",
    "MessagingCapabilities",
    "MessagingConfig",
    "TwilioMessagingAdapter",
    "build_messaging",
]
