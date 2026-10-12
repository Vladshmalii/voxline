from fastapi import APIRouter, Depends

from src.controller.api.v1 import (
    account_admin,
    admin_stats,
    agents,
    audiences,
    auth,
    billing,
    calls,
    campaigns,
    clients,
    me,
    messaging,
    models,
    playground,
    providers,
    services_status,
    sms,
    stats,
    telephony,
)
from src.core.auth.dependencies import verify_user

router = APIRouter()
# login / refresh / logout: the only routes that work without a session.
router.include_router(auth.public_router)

# Authentication is enforced for every other route via ``verify_user``;
# authorization is per-router/per-endpoint on top of it — see
# src/controller/dependencies/permission.py for the access matrix.
protected = APIRouter(dependencies=[Depends(verify_user)])
protected.include_router(auth.router)  # me, organizations, change_organization
protected.include_router(account_admin.router)  # organizations/users/members admin
protected.include_router(me.router)  # me: the caller's own role, for frontend gating
protected.include_router(providers.router)  # model-providers: endpoints + keys, per org
protected.include_router(models.router)  # models: served STT/TTS/LLM rows, per kind
protected.include_router(telephony.router)  # telephony: carrier/bridge bindings
protected.include_router(messaging.router)  # messaging: SMS route bindings
protected.include_router(sms.router)  # sms: send + delivery history
protected.include_router(agents.router)  # voice-agents + languages + diagnostics
protected.include_router(clients.router)  # clients: the people behind phone numbers
protected.include_router(audiences.router)  # audiences: reusable contact lists
protected.include_router(campaigns.router)  # campaigns: scripts, uploads, lifecycle
protected.include_router(
    calls.router
)  # calls: originate/cancel/inspect (worker runs them)
protected.include_router(stats.router)  # stats: one global snapshot for the dashboard
protected.include_router(
    services_status.router
)  # services: real-time health and status of telephony/AI/SMS
protected.include_router(
    billing.router
)  # billing: balances, tariffs, top-ups, transaction history
protected.include_router(admin_stats.router)  # admin: unified company/account analytics
protected.include_router(playground.router)  # WS: talk to an agent, no telephony

router.include_router(protected)
