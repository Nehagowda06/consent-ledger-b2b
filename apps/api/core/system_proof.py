from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.system_forensics import export_system_ledger, verify_system_ledger


def _rfc3339_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def export_system_proof(db: Session) -> dict[str, Any]:
    ledger = export_system_ledger(db)
    events = ledger["events"]
    return {
        "version": 1,
        "generated_at": _rfc3339_now(),
        "event_count": len(events),
        "last_event_hash": events[-1]["event_hash"] if events else None,
        "events": [
            {
                "event_type": event["event_type"],
                "tenant_id": event["tenant_id"],
                "resource_type": event["resource_type"],
                "resource_id": event["resource_id"],
                "payload_hash": event["payload_hash"],
                "prev_hash": event["prev_hash"],
                "event_hash": event["event_hash"],
            }
            for event in events
        ],
    }


def verify_system_proof(proof: dict[str, Any]) -> dict[str, Any]:
    for key in ("version", "generated_at", "event_count", "last_event_hash", "events"):
        if key not in proof:
            return {"verified": False, "failure_reason": f"missing key: {key}"}
    if proof["version"] != 1:
        return {"verified": False, "failure_reason": "unsupported version"}
    if not isinstance(proof["events"], list):
        return {"verified": False, "failure_reason": "events must be a list"}
    if not isinstance(proof["event_count"], int):
        return {"verified": False, "failure_reason": "event_count must be an integer"}
    if proof["event_count"] != len(proof["events"]):
        return {"verified": False, "failure_reason": "event_count mismatch"}

    if proof["events"]:
        expected_last = proof["events"][-1].get("event_hash")
        if not isinstance(expected_last, str):
            return {"verified": False, "failure_reason": "invalid event_hash in last event"}
        declared_last = proof.get("last_event_hash")
        if not isinstance(declared_last, str) or not hmac.compare_digest(declared_last, expected_last):
            return {"verified": False, "failure_reason": "last_event_hash mismatch"}
    elif proof.get("last_event_hash") is not None:
        return {"verified": False, "failure_reason": "last_event_hash must be null when no events"}

    chain_result = verify_system_ledger(proof["events"])
    if not chain_result.get("verified"):
        return {
            "verified": False,
            "failure_reason": (
                f"chain verification failed at index {chain_result.get('failure_index')}: "
                f"{chain_result.get('failure_reason')}"
            ),
        }

    return {"verified": True, "failure_reason": None}

