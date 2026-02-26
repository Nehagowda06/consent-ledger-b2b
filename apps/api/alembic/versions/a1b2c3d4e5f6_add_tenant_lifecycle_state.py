"""add tenant lifecycle state

Revision ID: a1b2c3d4e5f6
Revises: f4c8a1d2e9b3
Create Date: 2026-02-26 03:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f4c8a1d2e9b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_check_constraint(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    return any(c["name"] == constraint_name for c in inspector.get_check_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_column(inspector, "tenants", "lifecycle_state"):
        op.add_column(
            "tenants",
            sa.Column(
                "lifecycle_state",
                sa.String(length=32),
                nullable=False,
                server_default="active",
            ),
        )
        op.execute("UPDATE tenants SET lifecycle_state='disabled' WHERE is_active = false")
        op.execute("UPDATE tenants SET lifecycle_state='active' WHERE lifecycle_state IS NULL")
        inspector = sa.inspect(bind)

    if not _has_check_constraint(inspector, "tenants", "ck_tenants_lifecycle_state"):
        op.create_check_constraint(
            "ck_tenants_lifecycle_state",
            "tenants",
            "lifecycle_state IN ('active', 'suspended', 'disabled')",
        )


def downgrade() -> None:
    # Non-destructive by design.
    pass

