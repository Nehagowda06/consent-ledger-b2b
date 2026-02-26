"""add consent lineage events

Revision ID: b8a1f4d2c9e7
Revises: 6d4f3a2a9e11
Create Date: 2026-02-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b8a1f4d2c9e7"
down_revision: Union[str, Sequence[str], None] = "6d4f3a2a9e11"
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

    if not _has_table(inspector, "consent_lineage_events"):
        op.create_table(
            "consent_lineage_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("consent_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("event_hash", sa.String(length=64), nullable=False),
            sa.Column("prev_event_hash", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "event_hash", name="uq_lineage_tenant_event_hash"),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "consent_lineage_events") and not _has_index(
        inspector, "consent_lineage_events", "ix_consent_lineage_events_tenant_id"
    ):
        op.create_index(
            "ix_consent_lineage_events_tenant_id",
            "consent_lineage_events",
            ["tenant_id"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "consent_lineage_events") and not _has_index(
        inspector, "consent_lineage_events", "ix_consent_lineage_events_consent_id"
    ):
        op.create_index(
            "ix_consent_lineage_events_consent_id",
            "consent_lineage_events",
            ["consent_id"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "consent_lineage_events") and not _has_index(
        inspector, "consent_lineage_events", "ix_lineage_tenant_consent_created"
    ):
        op.create_index(
            "ix_lineage_tenant_consent_created",
            "consent_lineage_events",
            ["tenant_id", "consent_id", "created_at"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "consent_lineage_events") and not _has_unique_constraint(
        inspector, "consent_lineage_events", "uq_lineage_tenant_event_hash"
    ):
        op.create_unique_constraint(
            "uq_lineage_tenant_event_hash",
            "consent_lineage_events",
            ["tenant_id", "event_hash"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "consent_lineage_events"):
        op.drop_table("consent_lineage_events")
