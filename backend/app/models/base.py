"""Declarative base and shared column mixins (conventions in DATABASE.md §1)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import Date, DateTime, ForeignKey, LargeBinary, MetaData, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.core.ids import new_id

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        uuid.UUID: UUID(as_uuid=True),
        datetime: DateTime(timezone=True),
        date: Date(),
        str: Text(),
        Decimal: Numeric(14, 2),
        bytes: LargeBinary(),
        dict[str, Any]: JSONB(),
        list[Any]: JSONB(),
    }


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id, sort_order=-100)


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), sort_order=100)


class Timestamps(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now(), sort_order=101)


class TenantOwned:
    """Row belongs to one tenant. RLS is applied to the table in its migration.

    Exposes ``UNIQUE (tenant_id, id)`` so children can use composite foreign keys
    ``(tenant_id, parent_id) → parent (tenant_id, id)`` (DATABASE.md §3).
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True, sort_order=-99
    )

    @declared_attr.directive
    def __table_args__(cls) -> tuple[Any, ...]:
        return (UniqueConstraint("tenant_id", "id"), *getattr(cls, "__extra_table_args__", ()))


def check_in(column: str, values: tuple[str, ...]) -> str:
    """SQL for ``CHECK (column IN (...))`` on text status/type columns."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"
