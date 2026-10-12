from sqlalchemy import ColumnElement, select

from src.models.provider import Model, ModelProvider
from src.repositories.base import CRUD


class ModelProviderCRUD(CRUD[ModelProvider]):
    model = ModelProvider


class ModelCRUD(CRUD[Model]):
    model = Model

    async def preferred(self, *clauses: ColumnElement[bool]) -> Model | None:
        """The one model to use when ``clauses`` match several.

        The organization's default wins, then any active model, then the
        lowest id — so the same rows always pick the same model, where
        ``get_one_or_none`` would fail on a second match.
        """
        stmt = (
            select(Model)
            .where(*clauses)
            .order_by(Model.is_default.desc(), Model.is_active.desc(), Model.id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()
