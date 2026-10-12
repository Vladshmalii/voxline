from typing import Generic, TypeVar, Any, Sequence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from .models import Base
from sqlalchemy import (
    ColumnElement,
    select,
    delete,
    update,
    func,
    exists,
    RowMapping,
)


ModelT = TypeVar("ModelT", bound=Base)


class BaseCRUD(Generic[ModelT]):
    """Generic base class for repository (CRUD) objects.

    Bind the ORM model type via the generic parameter::

        class UserCRUD(BaseCRUD[User]):
            model = User
            ...

    Every subclass receives a scoped ``AsyncSession`` injected at construction
    time.  Add query/write methods in subclasses.
    """

    model: type[ModelT]
    session: AsyncSession

    def __init__(
        self, session: AsyncSession, model: type[ModelT] | None = None
    ) -> None:
        """Store the database session for use in subclass methods.

        Args:
            session: An active ``AsyncSession`` bound to a specific database.
            model:   The model class to use for the repository.
        """
        self.session = session
        if model is not None:
            self.model = model

    async def get_one_or_none(self, *clauses: ColumnElement[bool]) -> ModelT | None:
        """Fetch a single record matching all clauses, or None if not found.

        Raises ``MultipleResultsFound`` if more than one record matches.

        Args:
            *clauses: SQLAlchemy column expressions joined with AND.

        Returns:
            A model instance, or None if no record matches.
        """
        stmt = select(self.model).where(*clauses)
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def get_many(
        self,
        *clauses: ColumnElement[bool],
        limit: int | None = None,
        offset: int | None = None,
        order_by: ColumnElement | None = None,
    ) -> Sequence[ModelT]:
        """Fetch all records matching the given clauses.

        Args:
            *clauses: SQLAlchemy column expressions joined with AND.
            limit:    Maximum number of records to return.
            offset:   Number of records to skip (for pagination).

        Returns:
            List of matching model instances, or an empty list.
        """
        stmt = select(self.model).where(*clauses)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        result = await self.session.execute(stmt)
        return result.unique().scalars().all()

    async def get_many_with_count(
        self,
        *clauses: ColumnElement[bool],
        limit: int | None = None,
        offset: int | None = None,
        order_by: ColumnElement | None = None,
    ) -> tuple[Sequence[ModelT], int]:
        """Fetch records matching the given clauses along with the total count.

        The count is computed with a window function before ``limit``/``offset``
        are applied, so it reflects all matching rows — useful for pagination.

        Args:
            *clauses: SQLAlchemy column expressions joined with AND.
            limit:    Maximum number of records to return.
            offset:   Number of records to skip (for pagination).
            order_by: Column expression to order the results by.

        Returns:
            Tuple of (matching model instances, total number of matching rows).
        """
        stmt = select(self.model, func.count().over()).where(*clauses)
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        result = await self.session.execute(stmt)
        rows = result.unique().all()
        if not rows:
            # offset may point past the last row while matches still exist
            return [], await self.count(*clauses)
        return [row[0] for row in rows], rows[0][1]

    async def create(self, data: dict[str, Any]) -> ModelT:
        """Insert a new record from a dict and return the persisted instance.

        Calls ``flush()`` to obtain the generated primary key without
        committing the transaction.  The caller controls commit/rollback.

        Args:
            data: Column-value pairs for the new record.

        Returns:
            The newly created model instance with all server defaults populated.
        """
        obj = self.model(**data)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def create_many(self, data: list[dict[str, Any]]) -> list[ModelT]:
        """Bulk-insert multiple records and return the persisted instances.


        Args:
            data: List of column-value dicts, one per record.

        Returns:
            List of created model instances in the same order as ``data``.
        """
        objs = [self.model(**item) for item in data]
        self.session.add_all(objs)
        await self.session.flush()
        return objs

    async def delete(self, *clauses: ColumnElement[bool]) -> int:
        """Delete all records matching the given clauses.

        Executes a single ``DELETE WHERE`` statement.  Does not load records
        into memory — more efficient than fetching then deleting.

        Args:
            *clauses: SQLAlchemy column expressions joined with AND.

        Returns:
            Number of deleted rows.
        """
        stmt = delete(self.model).where(*clauses)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def update(
        self,
        *clauses: ColumnElement[bool],
        data: dict[str, Any],
    ) -> int:
        """Update all records matching the given clauses.

        Args:
            *clauses: SQLAlchemy column expressions that identify target rows.
            data:     Column-value pairs to set on matched records.

        Returns:
            Number of updated rows.
        """
        stmt = update(self.model).where(*clauses).values(data)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount

    async def update_returning(
        self,
        *clauses: ColumnElement[bool],
        data: dict[str, Any],
    ) -> Sequence[ModelT]:
        """Update matching records and return the updated model instances.

        Args:
            *clauses: SQLAlchemy column expressions that identify target rows.
            data:     Column-value pairs to set on matched records.

        Returns:
            List of updated model instances with fresh values.
        """
        stmt = update(self.model).where(*clauses).values(data).returning(self.model)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalars().all()

    async def update_returning_columns(
        self,
        *clauses: ColumnElement[bool],
        data: dict[str, Any],
        columns: list[ColumnElement],
    ) -> Sequence[RowMapping]:
        """Update matching records and return only specific columns.

        Args:
            *clauses: SQLAlchemy column expressions that identify target rows.
            data:     Column-value pairs to set on matched records.
            columns:  Columns to include in the result (e.g. ``[User.id, User.updated_at]``).

        Returns:
            List of ``RowMapping`` dicts with the requested columns.
        """
        stmt = update(self.model).where(*clauses).values(data).returning(*columns)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.mappings().all()

    async def exists(self, *clauses: ColumnElement[bool]) -> bool:
        """Return True if at least one record matches the given clauses.

        Args:
            *clauses: SQLAlchemy column expressions joined with AND.

        Returns:
            ``True`` if a matching record exists, ``False`` otherwise.
        """
        stmt = select(exists().where(*clauses))
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def count(self, *clauses: ColumnElement[bool]) -> int:
        """Count records matching the given clauses.

        Args:
            *clauses: SQLAlchemy column expressions joined with AND.
                      Pass no arguments to count all rows in the table.

        Returns:
            Number of matching records.
        """
        stmt = select(func.count()).select_from(self.model).where(*clauses)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def upsert(
        self,
        data: dict[str, Any],
        conflict_target: list[str],
    ) -> ModelT:
        """Insert a record, updating it on conflict (upsert).

        Args:
            data:            Values to insert or update.
            conflict_target: Column names that define the conflict (unique constraint).

        Returns:
            The inserted or updated model instance.
        """
        stmt = pg_insert(self.model).values(**data)
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict_target,
            set_=data,
        ).returning(self.model)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalars().one()

    async def upsert_many(
        self,
        data: list[dict[str, Any]],
        conflict_target: list[str],
    ) -> Sequence[ModelT]:
        """Bulk insert records, updating on conflict (bulk upsert).

        Uses ``stmt.excluded`` to reference the values that were not inserted
        due to a conflict, so the update reflects the attempted new values.

        Args:
            data:            List of value dicts to insert or update.
            conflict_target: Column names that define the conflict.

        Returns:
            List of inserted or updated model instances.
        """
        keys = [frozenset(d.keys()) for d in data]
        if len(set(keys)) > 1:
            raise ValueError(f"All dicts must have the same keys. Got: {keys}")
        stmt = pg_insert(self.model).values(data)
        update_cols = {
            col: getattr(stmt.excluded, col)
            for col in data[0].keys()
            if col not in conflict_target
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict_target,
            set_=update_cols,
        ).returning(self.model)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalars().all()

    async def create_or_ignore(
        self,
        data: dict[str, Any],
        conflict_target: list[str],
    ) -> ModelT | None:
        """Insert a record, doing nothing on conflict.

        Args:
            data:            Values to insert.
            conflict_target: Column names that define the conflict.

        Returns:
            The inserted model instance, or None if a conflict occurred.
        """
        stmt = pg_insert(self.model).values(**data)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=conflict_target,
        ).returning(self.model)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalars().one_or_none()

    async def create_many_or_ignore(
        self,
        data: list[dict[str, Any]],
        conflict_target: list[str],
    ) -> Sequence[ModelT]:
        """Bulk insert records, skipping conflicts.

        Args:
            data:            List of value dicts to insert.
            conflict_target: Column names that define the conflict.

        Returns:
            List of only the successfully inserted model instances.
        """
        stmt = pg_insert(self.model).values(data)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=conflict_target,
        ).returning(self.model)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalars().all()
