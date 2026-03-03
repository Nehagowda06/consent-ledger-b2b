import hashlib
import hmac
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.lineage_export import export_consent_lineage
from models.consent_lineage import ConsentLineageEvent


def _rfc3339_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def compute_anchor_digest(tenant_anchors: list[str]) -> str:
    ordered = sorted(tenant_anchors)
    material = "\n".join(ordered)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def export_anchor_snapshot(db: Session) -> dict:
    pairs = list(
        db.execute(
            select(
                ConsentLineageEvent.tenant_id,
                ConsentLineageEvent.consent_id,
            ).distinct()
        ).all()
    )

    anchors = sorted(
        {
            export_consent_lineage(consent_id=consent_id, tenant_id=tenant_id, db=db)["tenant_anchor"]
            for tenant_id, consent_id in pairs
        }
    )

    return {
        "version": 1,
        "generated_at": _rfc3339_now(),
        "algorithm": "SHA256",
        "anchor_count": len(anchors),
        "digest": compute_anchor_digest(anchors),
        "anchors": anchors,
    }


def append_anchor_commit(commit_path: str, snapshot: dict) -> None:
    line = f"{snapshot['generated_at']} | {snapshot['digest']}\n"
    with open(commit_path, "a", encoding="utf-8") as fh:
        fh.write(line)


def verify_anchor_snapshot(snapshot: dict) -> dict:
    required = ["version", "generated_at", "algorithm", "anchor_count", "digest", "anchors"]
    missing = [k for k in required if k not in snapshot]
    if missing:
        return {"verified": False, "failure_reason": f"missing keys: {', '.join(missing)}"}
    if snapshot["version"] != 1:
        return {"verified": False, "failure_reason": "unsupported version"}
    if snapshot["algorithm"] != "SHA256":
        return {"verified": False, "failure_reason": "unsupported algorithm"}
    if not isinstance(snapshot["anchors"], list):
        return {"verified": False, "failure_reason": "anchors must be a list"}
    if snapshot["anchors"] != sorted(snapshot["anchors"]):
        return {"verified": False, "failure_reason": "anchors must be sorted"}
    if snapshot["anchor_count"] != len(snapshot["anchors"]):
        return {"verified": False, "failure_reason": "anchor_count mismatch"}

    expected = compute_anchor_digest(snapshot["anchors"])
    if not hmac.compare_digest(str(snapshot["digest"]), expected):
        return {"verified": False, "failure_reason": "digest mismatch"}
    return {"verified": True, "failure_reason": None}
