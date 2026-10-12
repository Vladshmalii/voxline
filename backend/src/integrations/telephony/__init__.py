"""Telephony adapters.

Importing this package registers every built-in leg in
:data:`~src.integrations.telephony.base.TelephonyAdapters`. The worker
resolves by name and hands the engine a built transport — the engine never
learns which carrier it is speaking through.
"""

from src.integrations.telephony.base import (
    BaseTelephonyAdapter,
    TelephonyAdapters,
    TelephonyCapabilities,
    TelephonyConfig,
    build_telephony,
)
from src.integrations.telephony.jambonz import (
    JambonzFrameSerializer,
    JambonzTelephonyAdapter,
)
from src.integrations.telephony.sip_bridge import (
    SipBridgeFrameSerializer,
    SipBridgeTelephonyAdapter,
)
from src.integrations.telephony.twilio import TwilioTelephonyAdapter

__all__ = [
    "BaseTelephonyAdapter",
    "JambonzFrameSerializer",
    "JambonzTelephonyAdapter",
    "SipBridgeFrameSerializer",
    "SipBridgeTelephonyAdapter",
    "TelephonyAdapters",
    "TelephonyCapabilities",
    "TelephonyConfig",
    "TwilioTelephonyAdapter",
    "build_telephony",
]
