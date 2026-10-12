from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SServiceStatusItem(BaseModel):
    name: str
    category: str  # "telephony" | "stt" | "tts" | "ttt" | "messaging" | "database"
    status: str  # "operational" | "degraded" | "down" | "unconfigured"
    latency_ms: float | None = None
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class SServicesStatusRead(BaseModel):
    status: str  # "operational" | "degraded" | "down"
    checked_at: datetime
    services: list[SServiceStatusItem]
    telephony_operational: bool
    telephony_count: int
    models_count: int
    messaging_operational: bool
