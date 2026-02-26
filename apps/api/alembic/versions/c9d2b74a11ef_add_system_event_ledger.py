"""add system event ledger

Revision ID: c9d2b74a11ef
Revises: b8a1f4d2c9e7
Create Date: 2026-02-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c9d2b74a11ef"
down_revision: Union[str, Sequence[str], None] = "b8a1f4d2c9e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _has_unique_constraint(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    return any(c["name"] == constraint_name for c in inspector.get_unique_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "system_event_ledger"):
        op.create_table(
            "system_event_ledger",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("event_type", sa.String(length=128), nullable=False),
            sa.Column("resource_type", sa.String(length=128), nullable=True),
            sa.Column("resource_id", sa.String(length=128), nullable=True),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("prev_event_hash", sa.String(length=64), nullable=True),
            sa.Column("event_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_hash", name="uq_system_event_ledger_event_hash"),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "system_event_ledger") and not _has_index(
        inspector, "system_event_ledger", "ix_system_event_ledger_tenant_id"
    ):
        op.create_index(
            "ix_system_event_ledger_tenant_id",
            "system_event_ledger",
            ["tenant_id"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "system_event_ledger") and not _has_index(
        inspector, "system_event_ledger", "ix_system_event_ledger_event_type"
    ):
        op.create_index(
            "ix_system_event_ledger_event_type",
            "system_event_ledger",
            ["event_type"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "system_event_ledger") and not _has_index(
        inspector, "system_event_ledger", "ix_system_event_ledger_event_type_created_at"
    ):
        op.create_index(
            "ix_system_event_ledger_event_type_created_at",
            "system_event_ledger",
            ["event_type", "created_at"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "system_event_ledger") and not _has_unique_constraint(
        inspector, "system_event_ledger", "uq_system_event_ledger_event_hash"
    ):
        op.create_unique_constraint(
            "uq_system_event_ledger_event_hash",
            "system_event_ledger",
            ["event_hash"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "system_event_ledger"):
        op.drop_table("system_event_ledger")
