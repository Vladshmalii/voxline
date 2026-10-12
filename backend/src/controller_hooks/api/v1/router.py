from fastapi import APIRouter

from src.controller_hooks.api.v1 import media, sms

# No verify_user here: nothing on this surface is a platform user. Callers are
# telephony providers, authenticated per call by the HMAC token minted at dial
# time (see src/application/worker/registry.py).
router = APIRouter()
router.include_router(media.router)
router.include_router(sms.router)
