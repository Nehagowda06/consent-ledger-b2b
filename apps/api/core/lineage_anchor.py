import hashlib


def compute_tenant_anchor(tenant_id: str, lineage_root_hash: str) -> str:
    # Anchor is bound only to tenant identity + lineage root.
    # It remains stable across API key rotation because keys are not part of input.
    material = f"ANCHOR|{tenant_id}|{lineage_root_hash}"
    # SHA256 over UTF-8 bytes keeps anchor deterministic and portable.
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
