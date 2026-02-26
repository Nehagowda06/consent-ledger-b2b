"""add signed assertions

Revision ID: e5b9d3a4c7f1
Revises: d1a7c5e4f902
Create Date: 2026-02-26 00:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e5b9d3a4c7f1"
down_revision: Union[str, Sequence[str], None] = "d1a7c5e4f902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "signed_assertions"):
        op.create_table(
            "signed_assertions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("identity_key_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("subject_type", sa.String(length=64), nullable=False),
            sa.Column("subject_id", sa.String(length=128), nullable=True),
            sa.Column("assertion_type", sa.String(length=64), nullable=False),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("signature", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(
                ["identity_key_id"],
                ["identity_keys.id"],
                name="fk_signed_assertions_identity_key_id_identity_keys",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        inspector = sa.inspect(bind)

    fk_names = {fk["name"] for fk in inspector.get_foreign_keys("signed_assertions")}
    if "fk_signed_assertions_identity_key_id_identity_keys" not in fk_names:
        op.create_foreign_key(
            "fk_signed_assertions_identity_key_id_identity_keys",
            "signed_assertions",
            "identity_keys",
            ["identity_key_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    if not _has_index(inspector, "signed_assertions", "ix_signed_assertions_subject_type_subject_id"):
        op.create_index(
            "ix_signed_assertions_subject_type_subject_id",
            "signed_assertions",
            ["subject_type", "subject_id"],
            unique=False,
        )
    if not _has_index(inspector, "signed_assertions", "ix_signed_assertions_assertion_type"):
        op.create_index(
            "ix_signed_assertions_assertion_type",
            "signed_assertions",
            ["assertion_type"],
            unique=False,
        )


def downgrade() -> None:
    # Non-destructive by design.
    pass
