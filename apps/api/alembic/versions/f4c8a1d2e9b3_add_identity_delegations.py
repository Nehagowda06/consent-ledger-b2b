"""add identity delegations

Revision ID: f4c8a1d2e9b3
Revises: e5b9d3a4c7f1
Create Date: 2026-02-26 02:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f4c8a1d2e9b3"
down_revision: Union[str, Sequence[str], None] = "e5b9d3a4c7f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _has_check_constraint(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    return any(c["name"] == constraint_name for c in inspector.get_check_constraints(table_name))


def _has_fk(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    return any(fk["name"] == constraint_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "identity_delegations"):
        op.create_table(
            "identity_delegations",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("parent_identity_key_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("child_identity_key_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("delegation_type", sa.String(length=64), nullable=False),
            sa.Column("signature", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(
                ["parent_identity_key_id"],
                ["identity_keys.id"],
                name="fk_identity_delegations_parent_identity_key_id_identity_keys",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["child_identity_key_id"],
                ["identity_keys.id"],
                name="fk_identity_delegations_child_identity_key_id_identity_keys",
                ondelete="RESTRICT",
            ),
            sa.CheckConstraint(
                "parent_identity_key_id <> child_identity_key_id",
                name="ck_identity_delegations_parent_child_diff",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        inspector = sa.inspect(bind)

    if not _has_fk(inspector, "identity_delegations", "fk_identity_delegations_parent_identity_key_id_identity_keys"):
        op.create_foreign_key(
            "fk_identity_delegations_parent_identity_key_id_identity_keys",
            "identity_delegations",
            "identity_keys",
            ["parent_identity_key_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    if not _has_fk(inspector, "identity_delegations", "fk_identity_delegations_child_identity_key_id_identity_keys"):
        op.create_foreign_key(
            "fk_identity_delegations_child_identity_key_id_identity_keys",
            "identity_delegations",
            "identity_keys",
            ["child_identity_key_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    if not _has_check_constraint(inspector, "identity_delegations", "ck_identity_delegations_parent_child_diff"):
        op.create_check_constraint(
            "ck_identity_delegations_parent_child_diff",
            "identity_delegations",
            "parent_identity_key_id <> child_identity_key_id",
        )

    if not _has_index(inspector, "identity_delegations", "ix_identity_delegations_parent_identity_key_id"):
        op.create_index(
            "ix_identity_delegations_parent_identity_key_id",
            "identity_delegations",
            ["parent_identity_key_id"],
            unique=False,
        )
    if not _has_index(inspector, "identity_delegations", "ix_identity_delegations_child_identity_key_id"):
        op.create_index(
            "ix_identity_delegations_child_identity_key_id",
            "identity_delegations",
            ["child_identity_key_id"],
            unique=False,
        )


def downgrade() -> None:
    # Non-destructive by design.
    pass

