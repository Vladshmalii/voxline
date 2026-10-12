"""Declarative bases for the per-organization (tenant) databases."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Identity, MetaData, func
from sqlalchemy import Enum as SQL_ENUM
from sqlalchemy.dialects.postgresql import UUID as SQL_UUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from src.core.config import Config


class _Base(AsyncAttrs, DeclarativeBase):
    __abstract__ = True
    metadata = MetaData(schema=Config.get_service_prefix())

    @declared_attr
    def __tablename__(cls) -> str:
        """Derive the table name from the class name (lowercased)."""
        return cls.__name__.lower()


class Base(_Base):
    """Abstract base: ``id`` identity key plus ``created_at`` / ``updated_at``."""

    __abstract__ = True

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), default=datetime.now, onupdate=datetime.now
    )

    def __str__(self) -> str:
        return f"<{self.__class__.__name__}> ({self.id})"


class BaseRel(_Base):
    """Abstract base for join tables that need no timestamps and no id."""

    __abstract__ = True


class BaseUUID(Base):
    """Abstract base for models that carry a public UUID."""

    __abstract__ = True
    uuid: Mapped[UUID] = mapped_column(SQL_UUID(as_uuid=True), default=uuid4)


class Enum(SQL_ENUM):
    """``sqlalchemy.Enum`` whose type lives in the service schema by default."""

    def __init__(self, *enums, **kwargs):
        kwargs["schema"] = kwargs.pop("schema", Config.get_service_prefix())
        super().__init__(*enums, **kwargs)
