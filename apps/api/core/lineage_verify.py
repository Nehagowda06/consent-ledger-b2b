import hmac
from datetime import datetime

from core.identity_crypto import compute_identity_fingerprint
from core.lineage_anchor import compute_tenant_anchor
from core.lineage import canonical_json
from core.lineage_signing import verify_bytes
from core.observability import (
    METRIC_SIGNATURE_VERIFICATION_FAILED,
    best_effort_system_event,
    increment_metric,
)


def _canonical_bytes(obj: dict) -> bytes:
    return canonical_json(obj).encode("utf-8")


def _failure(index: int | None, reason: str) -> dict:
    if "signature" in reason:
        increment_metric(METRIC_SIGNATURE_VERIFICATION_FAILED, reason=reason)
    return {"verified": False, "failure_index": index, "failure_reason": reason, "anchor_verified": False}


def verify_exported_lineage(export: dict) -> dict:
    has_sig_fields = any(k in export for k in ("signer_identity_fingerprint", "signer_public_key", "signature"))
    if has_sig_fields:
        if not all(k in export for k in ("signer_identity_fingerprint", "signer_public_key", "signature")):
            return _failure(None, "incomplete lineage signature fields")
        signer_fingerprint = str(export["signer_identity_fingerprint"])
        signer_public_key = str(export["signer_public_key"])
        signature = str(export["signature"])
        try:
            computed_fingerprint = compute_identity_fingerprint(signer_public_key)
        except Exception:
            return _failure(None, "lineage signer fingerprint mismatch")
        if not hmac.compare_digest(computed_fingerprint, signer_fingerprint):
            return _failure(None, "lineage signer fingerprint mismatch")
        signable = dict(export)
        signable.pop("signature", None)
        if not verify_bytes(signer_public_key, _canonical_bytes(signable), signature):
            best_effort_system_event(
                event_type="security.signature_verification_failed",
                tenant_id=str(export.get("tenant_id")),
                resource_type="lineage_export",
                resource_id=str(export.get("consent_id")),
                payload={"reason": "lineage_signature_verification_failed"},
            )
            return _failure(None, "lineage signature verification failed")

    required_top = [
        "version",
        "tenant_id",
        "consent_id",
        "algorithm",
        "canonicalization",
        "tenant_anchor",
        "events",
    ]
    missing = [k for k in required_top if k not in export]
    if missing:
        return _failure(None, f"missing keys: {', '.join(missing)}")

    if export.get("version") != 1:
        return _failure(None, "unsupported version")
    if export.get("algorithm") != "SHA256":
        return _failure(None, "unsupported algorithm")
    if export.get("canonicalization") != "sorted-json-no-whitespace":
        return _failure(None, "unsupported canonicalization")
    if not isinstance(export.get("events"), list):
        return _failure(None, "events must be a list")

    tenant_id = str(export.get("tenant_id"))
    consent_id = str(export.get("consent_id"))
    prev_hash = None

    for idx, event in enumerate(export["events"]):
        if not isinstance(event, dict):
            return _failure(idx, "event must be an object")
        for key in ("action", "event_hash", "prev_event_hash", "created_at"):
            if key not in event:
                return _failure(idx, f"missing event field: {key}")

        action = str(event["action"])
        event_hash = event["event_hash"]
        event_prev = event["prev_event_hash"]

        if not isinstance(event_hash, str) or len(event_hash) != 64:
            return _failure(idx, "event_hash must be a 64-character hex string")
        if event_prev is not None and not isinstance(event_prev, str):
            return _failure(idx, "prev_event_hash must be string or null")
        if event_prev is not None and len(event_prev) != 64:
            return _failure(idx, "prev_event_hash must be a 64-character hex string")
        if event_prev != prev_hash:
            return _failure(idx, "prev_event_hash does not match chain")

        material = (
            tenant_id
            + "|"
            + consent_id
            + "|"
            + action
            + "|"
            + canonical_json({})
            + "|"
            + (prev_hash or "")
        )

        import hashlib

        expected_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(expected_hash, event_hash):
            return _failure(idx, "event_hash mismatch")
        prev_hash = event_hash

    # Anchor check binds the full lineage root to the claimed tenant.
    # This prevents swapping in a valid chain from another tenant.
    expected_anchor = compute_tenant_anchor(tenant_id, prev_hash or "")
    anchor_matches = hmac.compare_digest(str(export.get("tenant_anchor", "")), expected_anchor)
    if not anchor_matches:
        return _failure(None, "tenant_anchor mismatch")

    return {"verified": True, "failure_index": None, "failure_reason": None, "anchor_verified": True}


def _parse_rfc3339(ts: str) -> datetime | None:
    try:
        normalized = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def _derive_state(included_events: list[dict]) -> str:
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
                return "UNKNOWN"
        elif action == "noop":
            continue
        else:
            return "UNKNOWN"
    return state


def verify_consent_proof(proof: dict) -> dict:
    required = [
        "version",
        "proof_type",
        "tenant_id",
        "consent_id",
        "asserted_at",
        "asserted_state",
        "tenant_anchor",
        "lineage",
        "included_events",
    ]
    missing = [k for k in required if k not in proof]
    if missing:
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": f"missing keys: {', '.join(missing)}"}

    if proof["version"] != 1:
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "unsupported version"}
    if proof["proof_type"] != "CONSENT_STATE_AT_TIME":
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "unsupported proof_type"}
    if proof["asserted_state"] not in {"ACTIVE", "REVOKED"}:
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "invalid asserted_state"}
    if not isinstance(proof.get("included_events"), list):
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "included_events must be a list"}
    if not isinstance(proof.get("lineage"), dict):
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "lineage must be an object"}

    asserted_at = _parse_rfc3339(str(proof["asserted_at"]))
    if asserted_at is None:
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "invalid asserted_at timestamp"}

    lineage_check = verify_exported_lineage(proof["lineage"])
    if not lineage_check["verified"]:
        reason = str(lineage_check.get("failure_reason") or "lineage verification failed")
        if "signature" in reason:
            reason = "lineage signature verification failed"
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": reason}
    if not lineage_check.get("anchor_verified", False):
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "tenant anchor verification failed"}

    lineage = proof["lineage"]
    if not hmac.compare_digest(str(proof.get("tenant_anchor", "")), str(lineage.get("tenant_anchor", ""))):
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "proof tenant_anchor mismatch"}
    if str(lineage.get("tenant_id")) != str(proof.get("tenant_id")):
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "tenant mismatch between proof and lineage"}
    if str(lineage.get("consent_id")) != str(proof.get("consent_id")):
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "consent mismatch between proof and lineage"}

    lineage_events = lineage.get("events", [])
    included = proof.get("included_events", [])
    if len(included) == 0:
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "included_events cannot be empty"}
    if len(included) > len(lineage_events):
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "included_events exceeds lineage length"}

    for idx, event in enumerate(included):
        if not isinstance(event, dict):
            return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": f"included event {idx} must be object"}
        for key in ("action", "event_hash", "created_at"):
            if key not in event:
                return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": f"missing included event field: {key}"}

        if event != {k: lineage_events[idx][k] for k in ("action", "event_hash", "created_at")}:
            return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": f"included event {idx} does not match lineage"}

        event_time = _parse_rfc3339(event["created_at"])
        if event_time is None:
            return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "invalid event timestamp"}
        if event_time > asserted_at:
            return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "included event is after asserted_at"}

    if len(included) < len(lineage_events):
        next_time = _parse_rfc3339(lineage_events[len(included)]["created_at"])
        if next_time is not None and next_time <= asserted_at:
            return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "included_events is incomplete for asserted_at"}

    derived_state = _derive_state(included)
    if derived_state not in {"ACTIVE", "REVOKED"}:
        return {"verified": False, "derived_state": "UNKNOWN", "failure_reason": "unable to derive state from included_events"}
    if not hmac.compare_digest(derived_state, str(proof["asserted_state"])):
        return {"verified": False, "derived_state": derived_state, "failure_reason": "asserted_state mismatch"}

    has_sig_fields = any(k in proof for k in ("signer_identity_fingerprint", "signer_public_key", "proof_signature"))
    if has_sig_fields:
        if not all(k in proof for k in ("signer_identity_fingerprint", "signer_public_key", "proof_signature")):
            return {"verified": False, "derived_state": derived_state, "failure_reason": "incomplete proof signature fields"}
        # LTS invariant: signed proof context must be bound to a signed lineage
        # with the same signer identity/public key.
        if not all(k in lineage for k in ("signer_identity_fingerprint", "signer_public_key", "signature")):
            return {"verified": False, "derived_state": derived_state, "failure_reason": "signed proof requires signed lineage"}
        signer_fingerprint = str(proof["signer_identity_fingerprint"])
        signer_public_key = str(proof["signer_public_key"])
        proof_signature = str(proof["proof_signature"])
        if not hmac.compare_digest(signer_fingerprint, str(lineage.get("signer_identity_fingerprint", ""))):
            return {"verified": False, "derived_state": derived_state, "failure_reason": "proof and lineage signer mismatch"}
        if not hmac.compare_digest(signer_public_key, str(lineage.get("signer_public_key", ""))):
            return {"verified": False, "derived_state": derived_state, "failure_reason": "proof and lineage signer mismatch"}
        try:
            computed_fingerprint = compute_identity_fingerprint(signer_public_key)
        except Exception:
            return {"verified": False, "derived_state": derived_state, "failure_reason": "proof signer fingerprint mismatch"}
        if not hmac.compare_digest(computed_fingerprint, signer_fingerprint):
            return {"verified": False, "derived_state": derived_state, "failure_reason": "proof signer fingerprint mismatch"}
        included_root_hash = included[-1]["event_hash"] if included else ""
        signable = {
            "asserted_at": str(proof["asserted_at"]),
            "asserted_state": str(proof["asserted_state"]),
            "lineage_root_hash": included_root_hash,
            "signer_identity_fingerprint": signer_fingerprint,
            "signer_public_key": signer_public_key,
        }
        if not verify_bytes(signer_public_key, _canonical_bytes(signable), proof_signature):
            best_effort_system_event(
                event_type="security.signature_verification_failed",
                tenant_id=str(proof.get("tenant_id")),
                resource_type="consent_proof",
                resource_id=str(proof.get("consent_id")),
                payload={"reason": "proof_signature_verification_failed"},
            )
            return {"verified": False, "derived_state": derived_state, "failure_reason": "proof signature verification failed"}

    return {"verified": True, "derived_state": derived_state, "failure_reason": None}
