"""add identity keys

Revision ID: d1a7c5e4f902
Revises: c9d2b74a11ef
Create Date: 2026-02-26 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d1a7c5e4f902"
down_revision: Union[str, Sequence[str], None] = "c9d2b74a11ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "identity_keys"
SCOPE_ENUM_NAME = "identitykeyscope"
UNIQUE_FINGERPRINT = "uq_identity_keys_fingerprint"
CHECK_SCOPE_OWNER = "ck_identity_keys_scope_owner"
IDX_SCOPE = "ix_identity_keys_scope"
IDX_OWNER = "ix_identity_keys_owner_id"


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _has_constraint(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    if any(c["name"] == constraint_name for c in inspector.get_unique_constraints(table_name)):
        return True
    pk = inspector.get_pk_constraint(table_name)
    if pk and pk.get("name") == constraint_name:
        return True
    return False


def _has_check_constraint(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    return any(c["name"] == constraint_name for c in inspector.get_check_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{SCOPE_ENUM_NAME}') THEN
                    CREATE TYPE {SCOPE_ENUM_NAME} AS ENUM ('tenant', 'system', 'admin');
                END IF;
            END $$;
            """
        )
    )

    if not _has_table(inspector, TABLE_NAME):
        op.create_table(
            TABLE_NAME,
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "scope",
                postgresql.ENUM(
                    "tenant",
                    "system",
                    "admin",
                    name=SCOPE_ENUM_NAME,
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("public_key", sa.Text(), nullable=False),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            # Fingerprint is scope-exclusive by design: one public key may bind to exactly
            # one identity scope forever, preventing cross-scope assertion ambiguity.
            sa.UniqueConstraint("fingerprint", name=UNIQUE_FINGERPRINT),
            sa.CheckConstraint(
                "(scope = 'tenant' AND owner_id IS NOT NULL) OR "
                "(scope IN ('system', 'admin') AND owner_id IS NULL)",
                name=CHECK_SCOPE_OWNER,
            ),
        )
        inspector = sa.inspect(bind)

    if not _has_constraint(inspector, TABLE_NAME, UNIQUE_FINGERPRINT):
        op.create_unique_constraint(UNIQUE_FINGERPRINT, TABLE_NAME, ["fingerprint"])

    if not _has_check_constraint(inspector, TABLE_NAME, CHECK_SCOPE_OWNER):
        op.create_check_constraint(
            CHECK_SCOPE_OWNER,
            TABLE_NAME,
            "(scope = 'tenant' AND owner_id IS NOT NULL) OR (scope IN ('system', 'admin') AND owner_id IS NULL)",
        )

    if not _has_index(inspector, TABLE_NAME, IDX_SCOPE):
        op.create_index(IDX_SCOPE, TABLE_NAME, ["scope"], unique=False)
    if not _has_index(inspector, TABLE_NAME, IDX_OWNER):
        op.create_index(IDX_OWNER, TABLE_NAME, ["owner_id"], unique=False)


def downgrade() -> None:
    # Intentionally non-destructive.
    pass
