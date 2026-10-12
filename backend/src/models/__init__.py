"""ORM models for the call service, one organization database each.

Importing this package registers every table on ``Base.metadata`` — alembic's
autogenerate and the app both rely on that, so a new model module must be
imported here (same convention as the chat and payment services).

The layering these rows feed: repositories read them and build the engine's
plain pydantic configuration (``VoiceAgentConfig`` / ``LanguageConfig`` /
``TelephonyConfig``); the engine never sees a row.
"""

from src.core.db.models import Base
from src.models.agent import AgentLanguage, VoiceAgent
from src.models.audience import Audience, AudienceMember
from src.models.billing import BalanceTransaction, OrganizationBalance
from src.models.call import Call, CallAttempt
from src.models.campaign import Campaign
from src.models.client import Client
from src.models.messaging import Message, Messaging
from src.models.provider import Model, ModelProvider
from src.models.telephony import Telephony

__all__ = [
    "AgentLanguage",
    "Audience",
    "AudienceMember",
    "BalanceTransaction",
    "Base",
    "Call",
    "CallAttempt",
    "Campaign",
    "Client",
    "Message",
    "Messaging",
    "Model",
    "ModelProvider",
    "OrganizationBalance",
    "Telephony",
    "VoiceAgent",
]
