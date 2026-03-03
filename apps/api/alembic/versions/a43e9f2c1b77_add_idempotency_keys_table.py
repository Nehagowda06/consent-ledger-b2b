"""add idempotency keys table

Revision ID: a43e9f2c1b77
Revises: 7b9f6d5f2d31
Create Date: 2026-02-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a43e9f2c1b77"
down_revision: Union[str, Sequence[str], None] = "7b9f6d5f2d31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # If a previous run already created the table (partial migration run),
    # skip creation to make migration re-runnable safely.
    if not _has_table(inspector, "idempotency_keys"):
        op.create_table(
            "idempotency_keys",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("key", sa.String(length=255), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=False),
            sa.Column("response_json", sa.JSON(), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("tenant_id", "key", name="uq_idempotency_keys_tenant_key"),
        )

    # Create helpful index if missing (safe even if table pre-existed).
    inspector = sa.inspect(bind)
    if _has_table(inspector, "idempotency_keys") and not _has_index(
        inspector, "idempotency_keys", "ix_idempotency_keys_tenant_id"
    ):
        op.create_index(
            "ix_idempotency_keys_tenant_id",
            "idempotency_keys",
            ["tenant_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "idempotency_keys"):
        if _has_index(inspector, "idempotency_keys", "ix_idempotency_keys_tenant_id"):
            op.drop_index("ix_idempotency_keys_tenant_id", table_name="idempotency_keys")
        op.drop_table("idempotency_keys")