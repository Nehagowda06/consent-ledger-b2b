import hashlib
import hmac
from typing import Any

from core.canonical import canonical_json


def compute_system_event_hash(
    event_type: str,
    tenant_id: str | None,
    resource_type: str | None,
    resource_id: str | None,
    payload: dict[str, Any],
    prev_hash: str | None,
) -> str:
    material = (
        "SYSTEM|"
        + str(event_type)
        + "|"
        + (str(tenant_id) if tenant_id else "")
        + "|"
        + (str(resource_type) if resource_type else "")
        + "|"
        + (str(resource_id) if resource_id else "")
        + "|"
        + canonical_json(payload)
        + "|"
        + (prev_hash or "")
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verify_system_chain(events: list[dict[str, Any]]) -> dict[str, Any]:
    prev_hash = None
    for idx, event in enumerate(events):
        for key in ("event_type", "tenant_id", "resource_type", "resource_id", "payload", "prev_hash", "event_hash"):
            if key not in event:
                return {"verified": False, "failure_index": idx, "failure_reason": f"missing key: {key}"}

        declared_prev = event.get("prev_hash")
        if declared_prev != prev_hash:
            return {"verified": False, "failure_index": idx, "failure_reason": "prev_hash continuity failure"}

        expected = compute_system_event_hash(
            event_type=str(event["event_type"]),
            tenant_id=str(event["tenant_id"]) if event["tenant_id"] is not None else None,
            resource_type=str(event["resource_type"]) if event["resource_type"] is not None else None,
            resource_id=str(event["resource_id"]) if event["resource_id"] is not None else None,
            payload=event["payload"] if isinstance(event["payload"], dict) else {},
            prev_hash=declared_prev,
        )
        event_hash = event.get("event_hash")
        if not isinstance(event_hash, str) or not hmac.compare_digest(event_hash, expected):
            return {"verified": False, "failure_index": idx, "failure_reason": "event_hash mismatch"}
        prev_hash = event_hash

    return {"verified": True, "failure_index": None, "failure_reason": None}
