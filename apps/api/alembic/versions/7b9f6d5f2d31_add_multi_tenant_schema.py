"""add multi-tenant schema

Revision ID: 7b9f6d5f2d31
Revises: 52a040db7f30
Create Date: 2026-02-22 12:25:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "7b9f6d5f2d31"
down_revision: Union[str, Sequence[str], None] = "52a040db7f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_TENANT_NAME = "local-dev"


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(i["name"] == index_name for i in inspector.get_indexes(table_name))


def _has_fk(inspector: sa.Inspector, table_name: str, fk_name: str) -> bool:
    return any(fk["name"] == fk_name for fk in inspector.get_foreign_keys(table_name))


def _has_unique(inspector: sa.Inspector, table_name: str, unique_name: str) -> bool:
    return any(u["name"] == unique_name for u in inspector.get_unique_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- tenants ---
    if not _has_table(inspector, "tenants"):
        op.create_table(
            "tenants",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("name", name="uq_tenants_name"),
        )

    # default tenant
    op.execute(
        sa.text(
            f"""
            INSERT INTO tenants (id, name)
            VALUES ('{DEFAULT_TENANT_ID}'::uuid, '{DEFAULT_TENANT_NAME}')
            ON CONFLICT (id) DO NOTHING
            """
        )
    )

    inspector = sa.inspect(bind)

    # --- api_keys ---
    if not _has_table(inspector, "api_keys"):
        op.create_table(
            "api_keys",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("key_hash", sa.String(128), nullable=False),
            sa.Column("label", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        )
        op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])

    inspector = sa.inspect(bind)

    # --- consents ---
    if not _has_table(inspector, "consents"):
        consent_status = postgresql.ENUM(
            "ACTIVE",
            "REVOKED",
            name="consentstatus",
            create_type=False,   # 🔑 critical fix
        )

        op.create_table(
            "consents",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "tenant_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text(f"'{DEFAULT_TENANT_ID}'::uuid"),
            ),
            sa.Column("subject_id", sa.String(128), nullable=False),
            sa.Column("purpose", sa.String(256), nullable=False),
            sa.Column("status", consent_status, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint(
                "tenant_id", "subject_id", "purpose",
                name="uq_consents_tenant_subject_purpose",
            ),
        )

        op.create_index("ix_consents_subject_id", "consents", ["subject_id"])
        op.create_index("ix_consents_tenant_id", "consents", ["tenant_id"])

    inspector = sa.inspect(bind)

    # --- audit_events ---
    if not _has_table(inspector, "audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "tenant_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
                server_default=sa.text(f"'{DEFAULT_TENANT_ID}'::uuid"),
            ),
            sa.Column("consent_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False, server_default=sa.text("'system'")),
            sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        )
        op.create_index("ix_audit_events_consent_id", "audit_events", ["consent_id"])
        op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("consents")
    op.drop_table("api_keys")
    op.drop_table("tenants")