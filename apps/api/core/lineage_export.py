from datetime import timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.canonical import canonical_json_bytes
from core.identity_crypto import compute_identity_fingerprint
from core.lineage_anchor import compute_tenant_anchor
from core.lineage import compute_event_hash
from core.lineage_signing import sign_bytes
from models.consent_lineage import ConsentLineageEvent


def _to_rfc3339(dt) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(obj: dict) -> bytes:
    return canonical_json_bytes(obj)


def export_consent_lineage(
    consent_id: UUID,
    tenant_id: UUID,
    db: Session,
    *,
    signer_identity_fingerprint: str | None = None,
    signer_public_key: str | None = None,
    signer_private_key_hex: str | None = None,
) -> dict:
    raw_events = list(
        db.scalars(
            select(ConsentLineageEvent)
            .where(
                ConsentLineageEvent.tenant_id == tenant_id,
                ConsentLineageEvent.consent_id == consent_id,
            )
            .order_by(ConsentLineageEvent.created_at.asc(), ConsentLineageEvent.id.asc())
        ).all()
    )
    by_prev = {}
    for event in raw_events:
        by_prev[event.prev_event_hash] = event
    ordered_events = []
    current = by_prev.get(None)
    seen = set()
    while current and current.id not in seen:
        ordered_events.append(current)
        seen.add(current.id)
        current = by_prev.get(current.event_hash)
    if len(ordered_events) != len(raw_events):
        ordered_events = raw_events

    export_events = []
    prev_hash = None
    for event in ordered_events:
        public_hash = compute_event_hash(
            {
                "tenant_id": str(tenant_id),
                "consent_id": str(consent_id),
                "action": event.action,
                "payload": {},
            },
            prev_hash,
        )
        export_events.append(
            {
                "action": event.action,
                "event_hash": public_hash,
                "prev_event_hash": prev_hash,
                "created_at": _to_rfc3339(event.created_at),
            }
        )
        prev_hash = public_hash

    lineage_root_hash = export_events[-1]["event_hash"] if export_events else ""
    # Tenant anchor ties exported lineage root to a tenant-scoped cryptographic commitment.
    # This blocks lineage substitution across tenants without exposing any secret material.
    tenant_anchor = compute_tenant_anchor(str(tenant_id), lineage_root_hash)

    export_obj = {
        "version": 1,
        "tenant_id": str(tenant_id),
        "consent_id": str(consent_id),
        "algorithm": "SHA256",
        "canonicalization": "sorted-json-no-whitespace",
        "tenant_anchor": tenant_anchor,
        "events": export_events,
    }
    if any(v is not None for v in (signer_identity_fingerprint, signer_public_key, signer_private_key_hex)):
        if not all(v is not None for v in (signer_identity_fingerprint, signer_public_key, signer_private_key_hex)):
            raise ValueError("lineage signing requires fingerprint, public_key, and private_key")
        computed_fingerprint = compute_identity_fingerprint(signer_public_key)
        if computed_fingerprint != signer_identity_fingerprint:
            raise ValueError("signer public key does not match signer_identity_fingerprint")
        signable = dict(export_obj)
        signable["signer_identity_fingerprint"] = signer_identity_fingerprint
        signable["signer_public_key"] = signer_public_key
        export_obj["signer_identity_fingerprint"] = signer_identity_fingerprint
        export_obj["signer_public_key"] = signer_public_key
        export_obj["signature"] = sign_bytes(signer_private_key_hex, _canonical_bytes(signable))
    return export_obj
