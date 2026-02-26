from __future__ import annotations

from datetime import timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.system_lineage import verify_system_chain
from models.system_event import SystemEvent


def _serialize_event(row: SystemEvent) -> dict[str, Any]:
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
        "event_type": row.event_type,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "payload_hash": row.payload_hash,
        "prev_hash": row.prev_event_hash,
        "event_hash": row.event_hash,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }


def export_system_ledger(db: Session) -> dict[str, Any]:
    rows = list(
        db.scalars(select(SystemEvent).order_by(SystemEvent.created_at.asc(), SystemEvent.id.asc())).all()
    )
    by_prev: dict[str | None, SystemEvent] = {}
    for row in rows:
        by_prev[row.prev_event_hash] = row

    ordered: list[SystemEvent] = []
    current = by_prev.get(None)
    seen: set[str] = set()
    while current is not None and current.event_hash not in seen:
        ordered.append(current)
        seen.add(current.event_hash)
        current = by_prev.get(current.event_hash)

    if len(ordered) != len(rows):
        ordered = rows

    return {"events": [_serialize_event(row) for row in ordered]}


def verify_system_ledger(events: list[dict[str, Any]]) -> dict[str, Any]:
    # System events intentionally keep payload hashes only; verification replays
    # the same chain shape by hashing that digest as canonical payload material.
    translated = []
    for event in events:
        translated.append(
            {
                "event_type": event.get("event_type"),
                "tenant_id": event.get("tenant_id"),
                "resource_type": event.get("resource_type"),
                "resource_id": event.get("resource_id"),
                "payload": {"payload_hash": event.get("payload_hash")},
                "prev_hash": event.get("prev_hash"),
                "event_hash": event.get("event_hash"),
            }
        )
    return verify_system_chain(translated)
