import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String, Text, UniqueConstraint, event, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import inspect
import sqlalchemy as sa

from core.identity_crypto import compute_identity_fingerprint, verify_public_key_format
from core.observability import (
    METRIC_APPEND_ONLY_VIOLATION_ATTEMPT,
    best_effort_system_event,
    increment_metric,
)
from core.db import Base


class IdentityKeyScope(str, enum.Enum):
    TENANT = "tenant"
    SYSTEM = "system"
    ADMIN = "admin"


class IdentityKey(Base):
    """Root of cryptographic trust material; not used for request authentication."""

    __tablename__ = "identity_keys"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_identity_keys_fingerprint"),
        CheckConstraint(
            "(scope = 'tenant' AND owner_id IS NOT NULL) OR "
            "(scope IN ('system', 'admin') AND owner_id IS NULL)",
            name="ck_identity_keys_scope_owner",
        ),
        Index("ix_identity_keys_scope", "scope"),
        Index("ix_identity_keys_owner_id", "owner_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[IdentityKeyScope] = mapped_column(
        Enum(
            IdentityKeyScope,
            name="identitykeyscope",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

def _validate_scope_owner(target: IdentityKey) -> None:
    if target.scope == IdentityKeyScope.TENANT and target.owner_id is None:
        raise ValueError("identity_keys invariant violation: tenant scope requires owner_id")
    if target.scope in (IdentityKeyScope.SYSTEM, IdentityKeyScope.ADMIN) and target.owner_id is not None:
        raise ValueError("identity_keys invariant violation: system/admin scope requires owner_id to be null")


@event.listens_for(IdentityKey, "before_insert", propagate=True)
def _validate_before_insert(_mapper, connection, target: IdentityKey) -> None:
    _validate_scope_owner(target)
    verify_public_key_format(target.public_key)
    computed = compute_identity_fingerprint(target.public_key)
    if computed != target.fingerprint:
        raise ValueError("public_key does not match fingerprint")
    existing = connection.execute(
        sa.text("SELECT scope FROM identity_keys WHERE fingerprint = :fp LIMIT 1"),
        {"fp": target.fingerprint},
    ).fetchone()
    if existing:
        raise ValueError("identity_keys fingerprint already bound to an identity scope")


@event.listens_for(IdentityKey, "before_update", propagate=True)
def _prevent_update(_mapper, _connection, target: IdentityKey) -> None:
    _validate_scope_owner(target)
    state = inspect(target)
    revoked_history = state.attrs.revoked_at.history
    if revoked_history.has_changes():
        deleted_val = revoked_history.deleted[0] if revoked_history.deleted else None
        added_val = revoked_history.added[0] if revoked_history.added else None
        if deleted_val is not None and added_val is None:
            raise ValueError("identity_keys.revoked_at is immutable once set")
        if deleted_val is not None and added_val is not None and deleted_val != added_val:
            raise ValueError("identity_keys.revoked_at is immutable once set")
    increment_metric(METRIC_APPEND_ONLY_VIOLATION_ATTEMPT, reason="identity_key_update")
    best_effort_system_event(
        event_type="security.append_only_violation_attempt",
        resource_type="identity_keys",
        resource_id=str(target.id),
        payload={"reason": "update_attempt"},
    )
    raise ValueError("identity_keys is append-only")


@event.listens_for(IdentityKey, "before_delete", propagate=True)
def _prevent_delete(_mapper, _connection, _target) -> None:
    increment_metric(METRIC_APPEND_ONLY_VIOLATION_ATTEMPT, reason="identity_key_delete")
    best_effort_system_event(
        event_type="security.append_only_violation_attempt",
        resource_type="identity_keys",
        payload={"reason": "delete_attempt"},
    )
    raise ValueError("identity_keys is append-only")
