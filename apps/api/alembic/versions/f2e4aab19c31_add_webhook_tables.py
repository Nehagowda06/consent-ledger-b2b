"""add webhook tables

Revision ID: f2e4aab19c31
Revises: a43e9f2c1b77
Create Date: 2026-02-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f2e4aab19c31"
down_revision: Union[str, Sequence[str], None] = "a43e9f2c1b77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    # Ensure enum type exists (safe if already present).
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='webhookdeliverystatus') THEN
                    CREATE TYPE webhookdeliverystatus AS ENUM ('pending', 'sent', 'failed');
                END IF;
            END $$;
            """
        )
    )

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "webhook_endpoints"):
        op.create_table(
            "webhook_endpoints",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("url", sa.String(length=2048), nullable=False),
            sa.Column("secret_hash", sa.String(length=256), nullable=False),
            sa.Column("label", sa.String(length=128), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "webhook_endpoints") and not _has_index(
        inspector, "webhook_endpoints", "ix_webhook_endpoints_tenant_id"
    ):
        op.create_index("ix_webhook_endpoints_tenant_id", "webhook_endpoints", ["tenant_id"], unique=False)

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "webhook_deliveries"):
        op.create_table(
            "webhook_deliveries",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("endpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("event_type", sa.String(length=128), nullable=False),
            sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column(
                "status",
                postgresql.ENUM("pending", "sent", "failed", name="webhookdeliverystatus", create_type=False),
                nullable=False,
                server_default=sa.text("'pending'::webhookdeliverystatus"),
            ),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["endpoint_id"], ["webhook_endpoints.id"], ondelete="CASCADE"),
        )

    inspector = sa.inspect(bind)
    if _has_table(inspector, "webhook_deliveries") and not _has_index(
        inspector, "webhook_deliveries", "ix_webhook_deliveries_tenant_id"
    ):
        op.create_index("ix_webhook_deliveries_tenant_id", "webhook_deliveries", ["tenant_id"], unique=False)
    if _has_table(inspector, "webhook_deliveries") and not _has_index(
        inspector, "webhook_deliveries", "ix_webhook_deliveries_endpoint_id"
    ):
        op.create_index("ix_webhook_deliveries_endpoint_id", "webhook_deliveries", ["endpoint_id"], unique=False)
    if _has_table(inspector, "webhook_deliveries") and not _has_index(
        inspector, "webhook_deliveries", "ix_webhook_deliveries_status_next_attempt"
    ):
        op.create_index(
            "ix_webhook_deliveries_status_next_attempt",
            "webhook_deliveries",
            ["status", "next_attempt_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "webhook_deliveries"):
        if _has_index(inspector, "webhook_deliveries", "ix_webhook_deliveries_status_next_attempt"):
            op.drop_index("ix_webhook_deliveries_status_next_attempt", table_name="webhook_deliveries")
        if _has_index(inspector, "webhook_deliveries", "ix_webhook_deliveries_endpoint_id"):
            op.drop_index("ix_webhook_deliveries_endpoint_id", table_name="webhook_deliveries")
        if _has_index(inspector, "webhook_deliveries", "ix_webhook_deliveries_tenant_id"):
            op.drop_index("ix_webhook_deliveries_tenant_id", table_name="webhook_deliveries")
        op.drop_table("webhook_deliveries")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "webhook_endpoints"):
        if _has_index(inspector, "webhook_endpoints", "ix_webhook_endpoints_tenant_id"):
            op.drop_index("ix_webhook_endpoints_tenant_id", table_name="webhook_endpoints")
        op.drop_table("webhook_endpoints")

    # Do not drop enum type automatically (safe for shared DBs / partial runs).
