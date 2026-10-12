"""Services status router: real-time health and connectivity of telephony, AI, and messaging."""

from fastapi import APIRouter

from src.application.services.services_status import ServicesStatusService
from src.controller.dependencies.db import SessionUserDep
from src.controller.dependencies.permission import view_dashboard
from src.schemas.services_status import SServicesStatusRead

router = APIRouter(prefix="/services", tags=["services"], dependencies=[view_dashboard])


@router.get("/status", response_model=SServicesStatusRead)
async def get_services_status(session: SessionUserDep):
    """Returns the operational status of telephony, STT/TTS/LLM models, SMS, and database."""
    return await ServicesStatusService(session).get_status()
