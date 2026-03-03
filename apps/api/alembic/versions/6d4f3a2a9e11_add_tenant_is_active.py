"""add tenant is_active

Revision ID: 6d4f3a2a9e11
Revises: f2e4aab19c31
Create Date: 2026-02-25 23:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6d4f3a2a9e11"
down_revision: Union[str, Sequence[str], None] = "f2e4aab19c31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "tenants", "is_active"):
        op.add_column(
            "tenants",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_column(inspector, "tenants", "is_active"):
        op.drop_column("tenants", "is_active")
