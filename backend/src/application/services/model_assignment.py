"""Server-owned model assignment within the caller's organization database."""

from fastapi import HTTPException
from sqlalchemy import select, text, update

from src.common.enums.engine import ProviderKindEnum
from src.models.provider import Model
from src.repositories.provider import ModelCRUD

MODEL_FIELDS = {f"{kind.value}_model_id": kind for kind in ProviderKindEnum}


def guard_model_fields(data, full_access: bool) -> None:
    if full_access:
        return
    if data.model_fields_set & MODEL_FIELDS.keys():
        raise HTTPException(403, "Only project administrators can assign models")
    # OpenAI extra_body is merged into the wire payload and can replace model.
    if "ttt_extra_body" in data.model_fields_set:
        raise HTTPException(
            403, "Only project administrators can set model request overrides"
        )
    for key in ("stt_params", "tts_params", "ttt_params"):
        params = getattr(data, key, None) or {}
        if params.keys() & {"model", "adapter", "provider", "extra_body"}:
            raise HTTPException(
                403, "Only project administrators can set model request overrides"
            )


async def default_model(session, kind: ProviderKindEnum) -> Model:
    model = await ModelCRUD(session).get_one_or_none(
        Model.kind == kind, Model.is_default.is_(True), Model.is_active.is_(True)
    )
    if model is None:
        raise HTTPException(
            422,
            f"The organization has no default {kind.value.upper()} model. Contact the project administrator.",
        )
    return model


async def validate_bindings(session, payload: dict, *, create=False, language=False):
    for field, kind in MODEL_FIELDS.items():
        if field not in payload and not create:
            continue
        model_id = payload.get(field)
        if model_id is None:
            if language:
                continue
            if not create:
                raise HTTPException(422, f"{field} cannot be null")
            payload[field] = (await default_model(session, kind)).id
            continue
        model = await ModelCRUD(session).get_one_or_none(Model.id == model_id)
        if model is None or model.kind != kind or not model.is_active:
            raise HTTPException(
                422,
                f"{field} must reference an active {kind.value.upper()} model in this organization",
            )


async def prepare_model_write(session, payload, item_id=None):
    # Serialize admin writes, including concurrent default replacement, in this DB.
    await session.execute(text("SELECT pg_advisory_xact_lock(741923)"))
    current = None
    if item_id is not None:
        current = (
            (await session.execute(select(Model).where(Model.id == item_id)))
            .unique()
            .scalar_one_or_none()
        )
        if current is None:
            raise HTTPException(404, "model not found")
    for field in ("is_active", "is_default", "is_analysis"):
        if field in payload and payload[field] is None:
            raise HTTPException(422, f"{field} cannot be null")
    is_default = payload.get("is_default", current.is_default if current else False)
    is_active = payload.get("is_active", current.is_active if current else False)
    is_analysis = payload.get("is_analysis", current.is_analysis if current else False)
    kind = current.kind if current else payload["kind"]
    if is_default and not is_active:
        raise HTTPException(422, "A default model must be active")
    if is_analysis and (not is_active or kind != ProviderKindEnum.ttt):
        raise HTTPException(422, "The analysis model must be an active TTT model")
    if is_default:
        payload["is_default"] = True
        await session.execute(
            update(Model)
            .where(Model.kind == kind, Model.is_default.is_(True))
            .values(is_default=False)
        )
    if is_analysis:
        # One per organization: flagging a model moves the flag, like defaults.
        payload["is_analysis"] = True
        await session.execute(
            update(Model).where(Model.is_analysis.is_(True)).values(is_analysis=False)
        )
