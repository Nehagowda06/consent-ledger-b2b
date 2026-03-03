import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from core.logging_utils import log_structured
from core.system_lineage import canonical_json, compute_system_event_hash
from models.system_event import SystemEvent


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def record_system_event(
    db: Session,
    *,
    event_type: str,
    tenant_id: str | uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    payload: dict[str, Any] | None = None,
    fail_open: bool = False,
) -> SystemEvent | None:
    payload = payload or {}
    try:
        payload_hash = _payload_hash(payload)
        pending_events = [obj for obj in getattr(db, "new", set()) if isinstance(obj, SystemEvent)]
        if pending_events:
            referenced = {row.prev_event_hash for row in pending_events if row.prev_event_hash}
            pending_tips = [row for row in pending_events if row.event_hash and row.event_hash not in referenced]
            source = pending_tips or pending_events
            previous = sorted(
                source,
                key=lambda row: (
                    row.created_at or datetime.min.replace(tzinfo=timezone.utc),
                    str(row.id) if row.id else "",
                ),
            )[-1]
        else:
            child = SystemEvent.__table__.alias("child")
            previous = db.scalar(
                select(SystemEvent)
                .where(
                    ~exists(
                        select(1).where(child.c.prev_event_hash == SystemEvent.event_hash)
                    )
                )
                .order_by(SystemEvent.created_at.desc(), SystemEvent.id.desc())
                .limit(1)
            )
        prev_hash = previous.event_hash if previous else None
        event_hash = compute_system_event_hash(
            event_type=event_type,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            payload={"payload_hash": payload_hash},
            prev_hash=prev_hash,
        )
        event = SystemEvent(
            tenant_id=_as_uuid(tenant_id),
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            payload_hash=payload_hash,
            prev_event_hash=prev_hash,
            event_hash=event_hash,
            created_at=datetime.now(timezone.utc),
        )
        db.add(event)
        return event
    except Exception:
        if fail_open:
            log_structured("system_event.record_failed", event_type=event_type)
            return None
        raise
