"""add multi-tenant schema

Revision ID: 7b9f6d5f2d31
Revises: 52a040db7f30
Create Date: 2026-02-22 12:25:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7b9f6d5f2d31"
down_revision: Union[str, Sequence[str], None] = "52a040db7f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_TENANT_NAME = "local-dev"


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _has_fk(inspector: sa.Inspector, table_name: str, fk_name: str) -> bool:
    return any(fk["name"] == fk_name for fk in inspector.get_foreign_keys(table_name))


def _has_unique(inspector: sa.Inspector, table_name: str, unique_name: str) -> bool:
    return any(unique["name"] == unique_name for unique in inspector.get_unique_constraints(table_name))


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- tenants ---
    if not _has_table(inspector, "tenants"):
        op.create_table(
            "tenants",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name", name="uq_tenants_name"),
        )

    inspector = sa.inspect(bind)

    # --- api_keys ---
    if not _has_table(inspector, "api_keys"):
        op.create_table(
            "api_keys",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("key_hash", sa.String(length=128), nullable=False),
            sa.Column("label", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        )
        op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"], unique=False)

    # --- insert default tenant (NO bind params; avoids paramstyle issues) ---
    # Safe because values are constants defined in this migration.
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

    # --- consents ---
    if not _has_table(inspector, "consents"):
        consent_status = sa.Enum("ACTIVE", "REVOKED", name="consentstatus")
        consent_status.create(bind, checkfirst=True)

        op.create_table(
            "consents",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "tenant_id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text(f"'{DEFAULT_TENANT_ID}'::uuid"),
                nullable=False,
            ),
            sa.Column("subject_id", sa.String(length=128), nullable=False),
            sa.Column("purpose", sa.String(length=256), nullable=False),
            sa.Column("status", consent_status, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "subject_id",
                "purpose",
                name="uq_consents_tenant_subject_purpose",
            ),
        )
        op.create_index("ix_consents_subject_id", "consents", ["subject_id"], unique=False)
        op.create_index("ix_consents_tenant_id", "consents", ["tenant_id"], unique=False)
    else:
        if not _has_column(inspector, "consents", "tenant_id"):
            op.add_column(
                "consents",
                sa.Column(
                    "tenant_id",
                    postgresql.UUID(as_uuid=True),
                    nullable=True,
                    server_default=sa.text(f"'{DEFAULT_TENANT_ID}'::uuid"),
                ),
            )
            op.execute(
                sa.text(
                    f"UPDATE consents SET tenant_id = '{DEFAULT_TENANT_ID}'::uuid WHERE tenant_id IS NULL"
                )
            )
            op.alter_column("consents", "tenant_id", nullable=False)

        inspector = sa.inspect(bind)

        if not _has_fk(inspector, "consents", "fk_consents_tenant_id_tenants"):
            op.create_foreign_key(
                "fk_consents_tenant_id_tenants",
                "consents",
                "tenants",
                ["tenant_id"],
                ["id"],
                ondelete="RESTRICT",
            )

        if not _has_index(inspector, "consents", "ix_consents_tenant_id"):
            op.create_index("ix_consents_tenant_id", "consents", ["tenant_id"], unique=False)

        if not _has_unique(inspector, "consents", "uq_consents_tenant_subject_purpose"):
            op.create_unique_constraint(
                "uq_consents_tenant_subject_purpose",
                "consents",
                ["tenant_id", "subject_id", "purpose"],
            )

    inspector = sa.inspect(bind)

    # --- audit_events ---
    if not _has_table(inspector, "audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "tenant_id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text(f"'{DEFAULT_TENANT_ID}'::uuid"),
                nullable=False,
            ),
            sa.Column("consent_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False, server_default=sa.text("'system'")),
            sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_audit_events_consent_id", "audit_events", ["consent_id"], unique=False)
        op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"], unique=False)
    else:
        if not _has_column(inspector, "audit_events", "tenant_id"):
            op.add_column(
                "audit_events",
                sa.Column(
                    "tenant_id",
                    postgresql.UUID(as_uuid=True),
                    nullable=True,
                    server_default=sa.text(f"'{DEFAULT_TENANT_ID}'::uuid"),
                ),
            )
            op.execute(
                sa.text(
                    f"UPDATE audit_events SET tenant_id = '{DEFAULT_TENANT_ID}'::uuid WHERE tenant_id IS NULL"
                )
            )
            op.alter_column("audit_events", "tenant_id", nullable=False)

        inspector = sa.inspect(bind)

        if not _has_fk(inspector, "audit_events", "fk_audit_events_tenant_id_tenants"):
            op.create_foreign_key(
                "fk_audit_events_tenant_id_tenants",
                "audit_events",
                "tenants",
                ["tenant_id"],
                ["id"],
                ondelete="RESTRICT",
            )

        if not _has_index(inspector, "audit_events", "ix_audit_events_tenant_id"):
            op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "audit_events") and _has_column(inspector, "audit_events", "tenant_id"):
        if _has_index(inspector, "audit_events", "ix_audit_events_tenant_id"):
            op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
        if _has_fk(inspector, "audit_events", "fk_audit_events_tenant_id_tenants"):
            op.drop_constraint("fk_audit_events_tenant_id_tenants", "audit_events", type_="foreignkey")
        op.drop_column("audit_events", "tenant_id")

    inspector = sa.inspect(bind)

    if _has_table(inspector, "consents") and _has_column(inspector, "consents", "tenant_id"):
        if _has_unique(inspector, "consents", "uq_consents_tenant_subject_purpose"):
            op.drop_constraint("uq_consents_tenant_subject_purpose", "consents", type_="unique")
        if _has_index(inspector, "consents", "ix_consents_tenant_id"):
            op.drop_index("ix_consents_tenant_id", table_name="consents")
        if _has_fk(inspector, "consents", "fk_consents_tenant_id_tenants"):
            op.drop_constraint("fk_consents_tenant_id_tenants", "consents", type_="foreignkey")
        op.drop_column("consents", "tenant_id")

    inspector = sa.inspect(bind)

    if _has_table(inspector, "api_keys"):
        op.drop_index("ix_api_keys_tenant_id", table_name="api_keys")
        op.drop_table("api_keys")

    inspector = sa.inspect(bind)

    if _has_table(inspector, "tenants"):
        op.drop_table("tenants")