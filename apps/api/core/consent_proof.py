import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from core.identity_crypto import compute_identity_fingerprint
from core.lineage_export import export_consent_lineage
from core.lineage_signing import sign_bytes


def _parse_rfc3339(ts: str) -> datetime:
    normalized = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _derive_state_from_actions(included_events: list[dict]) -> str:
    if not included_events:
        return "UNKNOWN"
    state = "UNKNOWN"
    for event in included_events:
        action = event.get("action")
        if action == "created":
            state = "ACTIVE"
        elif action == "revoked":
            state = "REVOKED"
        elif action == "updated":
            if state == "ACTIVE":
                state = "REVOKED"
            elif state == "REVOKED":
                state = "ACTIVE"
            else:
                state = "UNKNOWN"
        elif action == "noop":
            continue
        else:
            state = "UNKNOWN"
    return state


def _canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def build_consent_proof(
    consent_id: UUID,
    tenant_id: UUID,
    asserted_at: datetime,
    db: Session,
    *,
    signer_identity_fingerprint: str | None = None,
    signer_public_key: str | None = None,
    signer_private_key_hex: str | None = None,
) -> dict:
    if asserted_at.tzinfo is None:
        asserted_at = asserted_at.replace(tzinfo=timezone.utc)
    asserted_at_utc = asserted_at.astimezone(timezone.utc)

    lineage = export_consent_lineage(consent_id=consent_id, tenant_id=tenant_id, db=db)
    events = lineage.get("events", [])
    latest_event_time = None
    for event in events:
        event_time = _parse_rfc3339(event["created_at"])
        if latest_event_time is None or event_time > latest_event_time:
            latest_event_time = event_time

    now_utc = datetime.now(timezone.utc)
    effective_now = now_utc if latest_event_time is None or latest_event_time < now_utc else latest_event_time
    if asserted_at_utc > effective_now:
        raise ValueError("asserted_at cannot be in the future")

    included_events = []
    for event in events:
        created_at = _parse_rfc3339(event["created_at"])
        if created_at <= asserted_at_utc:
            included_events.append(
                {
                    "action": event["action"],
                    "event_hash": event["event_hash"],
                    "created_at": event["created_at"],
                }
            )

    if not included_events:
        raise ValueError("no lineage events exist at or before asserted_at")

    asserted_state = _derive_state_from_actions(included_events)
    if asserted_state not in {"ACTIVE", "REVOKED"}:
        raise ValueError("unable to derive asserted_state from included events")

    proof = {
        "version": 1,
        "proof_type": "CONSENT_STATE_AT_TIME",
        "tenant_id": str(tenant_id),
        "consent_id": str(consent_id),
        "asserted_at": asserted_at_utc.isoformat().replace("+00:00", "Z"),
        "asserted_state": asserted_state,
        "tenant_anchor": lineage.get("tenant_anchor"),
        "lineage": lineage,
        "included_events": included_events,
    }
    if any(v is not None for v in (signer_identity_fingerprint, signer_public_key, signer_private_key_hex)):
        if not all(v is not None for v in (signer_identity_fingerprint, signer_public_key, signer_private_key_hex)):
            raise ValueError("proof signing requires fingerprint, public_key, and private_key")
        computed_fingerprint = compute_identity_fingerprint(signer_public_key)
        if computed_fingerprint != signer_identity_fingerprint:
            raise ValueError("signer public key does not match signer_identity_fingerprint")
        included_root_hash = included_events[-1]["event_hash"] if included_events else ""
        signable = {
            "asserted_at": proof["asserted_at"],
            "asserted_state": proof["asserted_state"],
            "lineage_root_hash": included_root_hash,
            "signer_identity_fingerprint": signer_identity_fingerprint,
            "signer_public_key": signer_public_key,
        }
        proof["signer_identity_fingerprint"] = signer_identity_fingerprint
        proof["signer_public_key"] = signer_public_key
        proof["proof_signature"] = sign_bytes(signer_private_key_hex, _canonical_bytes(signable))
    return proof
