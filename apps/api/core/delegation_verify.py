from __future__ import annotations

from datetime import datetime

from core.delegation_crypto import canonical_delegation_message, verify_delegation
from core.identity_crypto import compute_identity_fingerprint
from core.observability import (
    METRIC_DELEGATION_VERIFICATION_FAILED,
    best_effort_system_event,
    increment_metric,
)


def _parse_rfc3339(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _would_create_cycle(children_by_parent: dict[str, set[str]], parent: str, child: str) -> bool:
    if parent == child:
        return True
    stack = [child]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == parent:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(children_by_parent.get(node, set()))
    return False


def _delegation_failure(reason: str) -> bool:
    increment_metric(METRIC_DELEGATION_VERIFICATION_FAILED, reason=reason)
    best_effort_system_event(
        event_type="security.delegation_verification_failed",
        resource_type="identity_delegation",
        payload={"reason": reason},
    )
    return False


def verify_delegation_chain(delegations: list[dict], root_identity_fingerprint: str) -> bool:
    if not isinstance(delegations, list):
        return _delegation_failure("delegations_not_list")

    reachable: set[str] = {str(root_identity_fingerprint)}
    children_by_parent: dict[str, set[str]] = {}
    last_time: datetime | None = None

    for delegation in delegations:
        if not isinstance(delegation, dict):
            return _delegation_failure("delegation_not_object")
        required = (
            "parent_fingerprint",
            "child_fingerprint",
            "delegation_type",
            "parent_public_key",
            "child_public_key",
            "signature",
            "created_at",
        )
        if any(key not in delegation for key in required):
            return _delegation_failure("delegation_missing_fields")

        parent_fp = str(delegation["parent_fingerprint"])
        child_fp = str(delegation["child_fingerprint"])
        delegation_type = str(delegation["delegation_type"])
        parent_pub = str(delegation["parent_public_key"])
        child_pub = str(delegation["child_public_key"])
        signature = str(delegation["signature"])
        created_at = _parse_rfc3339(str(delegation["created_at"]))

        if created_at is None:
            return _delegation_failure("invalid_created_at")
        if last_time is not None and created_at < last_time:
            return _delegation_failure("non_monotonic_created_at")
        last_time = created_at

        if compute_identity_fingerprint(parent_pub) != parent_fp:
            return _delegation_failure("parent_fingerprint_mismatch")
        if compute_identity_fingerprint(child_pub) != child_fp:
            return _delegation_failure("child_fingerprint_mismatch")

        if parent_fp not in reachable:
            return _delegation_failure("parent_not_reachable")

        if _would_create_cycle(children_by_parent, parent_fp, child_fp):
            return _delegation_failure("cycle_detected")

        message = canonical_delegation_message(parent_fp, child_fp, delegation_type)
        if not verify_delegation(parent_pub, message, signature):
            return _delegation_failure("signature_verification_failed")

        children_by_parent.setdefault(parent_fp, set()).add(child_fp)
        reachable.add(child_fp)

    return True
