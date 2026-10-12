"""Repository base: the core CRUD plus the two helpers it lacks.

``src.core.db.repository.BaseCRUD`` covers create/read/update/delete;
list endpoints additionally want deterministic ordering and a total count in
one round trip, so those live here rather than being re-implemented per
repository.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, UnaryExpression, func, select

from src.core.db.repository import BaseCRUD, ModelT

__all__ = ["CRUD", "BaseCRUD", "icu_contains"]


def icu_contains(column, value: str) -> ColumnElement[bool]:
    """Literal, case-insensitive substring match that also folds non-ASCII.

    The tenant DB may use locale C, whose ILIKE only folds ASCII; ICU's root
    locale also folds Cyrillic and other Unicode text. ``%`` and ``_`` in
    ``value`` match themselves.
    """
    return column.collate("und-x-icu").icontains(value.strip(), autoescape=True)


class CRUD(BaseCRUD[ModelT]):
    """BaseCRUD with ordered listing and count-alongside pagination."""

    async def get_many_ordered(
        self,
        *clauses: ColumnElement[bool],
        order_by: ColumnElement | UnaryExpression | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[ModelT]:
        """``get_many`` with a stable order — pagination without one is a lie.

        Args:
            *clauses: SQLAlchemy column expressions joined with AND.
            order_by: Ordering expression; defaults to the model's ``id``.
            limit: Maximum number of records to return.
            offset: Number of records to skip.

        Returns:
            Matching model instances in the requested order.
        """
        stmt = (
            select(self.model)
            .where(*clauses)
            .order_by(order_by if order_by is not None else self.model.id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)
        result = await self.session.execute(stmt)
        return result.unique().scalars().all()

    async def get_many_with_count(
        self,
        *clauses: ColumnElement[bool],
        order_by: ColumnElement | UnaryExpression | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[list[ModelT], int]:
        """One page of results plus the total the filters match.

        Args:
            *clauses: SQLAlchemy column expressions joined with AND.
            order_by: Ordering expression; defaults to the model's ``id``.
            limit: Page size.
            offset: Page start.

        Returns:
            ``(items, total_count)``.
        """
        items = await self.get_many_ordered(
            *clauses, order_by=order_by, limit=limit, offset=offset
        )
        count_stmt = select(func.count()).select_from(self.model).where(*clauses)
        total = (await self.session.execute(count_stmt)).scalar_one()
        return items, total
