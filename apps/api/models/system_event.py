import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, event, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base
from core.observability import (
    METRIC_APPEND_ONLY_VIOLATION_ATTEMPT,
    best_effort_system_event,
    increment_metric,
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def compute_event_hash(
    tenant_id: str | None,
    event_type: str,
    resource_type: str | None,
    resource_id: str | None,
    payload_hash: str,
    prev_event_hash: str | None,
    created_at: datetime,
) -> str:
    ts = created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    material = (
        f"{tenant_id or ''}|"
        f"{event_type}|"
        f"{resource_type or ''}|"
        f"{resource_id or ''}|"
        f"{payload_hash}|"
        f"{prev_event_hash or ''}|"
        f"{ts}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class SystemEvent(Base):
    __tablename__ = "system_event_ledger"
    __table_args__ = (
        UniqueConstraint("event_hash", name="uq_system_event_ledger_event_hash"),
        Index("ix_system_event_ledger_event_type_created_at", "event_type", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False).with_variant(String(36), "sqlite"),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


@event.listens_for(SystemEvent, "before_update", propagate=True)
def _prevent_update(_mapper, _connection, _target) -> None:
    increment_metric(METRIC_APPEND_ONLY_VIOLATION_ATTEMPT, reason="system_event_update")
    best_effort_system_event(
        event_type="security.append_only_violation_attempt",
        resource_type="system_event_ledger",
        payload={"reason": "update_attempt"},
    )
    raise ValueError("system_event_ledger is append-only")


@event.listens_for(SystemEvent, "before_delete", propagate=True)
def _prevent_delete(_mapper, _connection, _target) -> None:
    increment_metric(METRIC_APPEND_ONLY_VIOLATION_ATTEMPT, reason="system_event_delete")
    best_effort_system_event(
        event_type="security.append_only_violation_attempt",
        resource_type="system_event_ledger",
        payload={"reason": "delete_attempt"},
    )
    raise ValueError("system_event_ledger is append-only")
