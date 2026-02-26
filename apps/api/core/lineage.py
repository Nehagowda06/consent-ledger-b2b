import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.consent import Consent
from models.consent_lineage import ConsentLineageEvent


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_event_hash(payload: dict[str, Any], prev_hash: str | None) -> str:
    tenant_id = str(payload.get("tenant_id", ""))
    consent_id = str(payload.get("consent_id", ""))
    action = str(payload.get("action", ""))
    body = payload.get("payload", {})
    material = (
        tenant_id
        + "|"
        + consent_id
        + "|"
        + action
        + "|"
        + canonical_json(body)
        + "|"
        + (prev_hash or "")
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def add_lineage_event(
    db: Session,
    consent: Consent,
    action: str,
) -> ConsentLineageEvent:
    previous = db.scalar(
        select(ConsentLineageEvent)
        .where(
            ConsentLineageEvent.tenant_id == consent.tenant_id,
            ConsentLineageEvent.consent_id == consent.id,
        )
        .order_by(ConsentLineageEvent.created_at.desc(), ConsentLineageEvent.id.desc())
        .limit(1)
    )
    prev_hash = previous.event_hash if previous else None

    created_at = datetime.now(timezone.utc)
    if previous and previous.created_at:
        previous_created_at = previous.created_at
        if previous_created_at.tzinfo is None:
            previous_created_at = previous_created_at.replace(tzinfo=timezone.utc)
        if created_at <= previous_created_at:
            created_at = previous_created_at + timedelta(microseconds=1)
    payload = {
        "subject_id": consent.subject_id,
        "purpose": consent.purpose,
        "status": consent.status.value if hasattr(consent.status, "value") else str(consent.status),
    }
    hash_payload = {
        "tenant_id": str(consent.tenant_id),
        "consent_id": str(consent.id),
        "action": action,
        "payload": payload,
    }
    event_hash = compute_event_hash(hash_payload, prev_hash)

    lineage_event = ConsentLineageEvent(
        tenant_id=consent.tenant_id,
        consent_id=consent.id,
        action=action,
        event_hash=event_hash,
        prev_event_hash=prev_hash,
        created_at=created_at,
    )
    db.add(lineage_event)
    return lineage_event


def _derive_event_statuses(events: list[ConsentLineageEvent], current_status: str) -> list[str] | None:
    if not events:
        return []
    statuses: list[str] = [""] * len(events)
    status_at_event = current_status
    for idx in range(len(events) - 1, -1, -1):
        statuses[idx] = status_at_event
        if idx == 0:
            break
        action = events[idx].action
        if action == "updated":
            status_at_event = "ACTIVE" if status_at_event == "REVOKED" else "REVOKED"
        elif action == "revoked":
            status_at_event = "ACTIVE"
        elif action in {"noop", "created"}:
            continue
        else:
            return None
    return statuses


def verify_lineage_chain(events: list[ConsentLineageEvent], consent: Consent) -> bool:
    statuses = _derive_event_statuses(
        events,
        consent.status.value if hasattr(consent.status, "value") else str(consent.status),
    )
    if statuses is None:
        return False

    prev_hash: str | None = None
    for idx, event in enumerate(events):
        payload = {
            "subject_id": consent.subject_id,
            "purpose": consent.purpose,
            "status": statuses[idx],
        }
        hash_payload = {
            "tenant_id": str(consent.tenant_id),
            "consent_id": str(consent.id),
            "action": event.action,
            "payload": payload,
        }
        expected_hash = compute_event_hash(hash_payload, prev_hash)
        if not hmac.compare_digest(event.event_hash, expected_hash):
            return False
        if event.prev_event_hash != prev_hash:
            return False
        prev_hash = event.event_hash
    return True
