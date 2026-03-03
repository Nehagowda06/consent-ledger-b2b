from __future__ import annotations

import unittest

from core.canonical import canonical_json
from core.external_anchor import compute_anchor_digest
from core.idempotency import MAX_IDEMPOTENCY_KEY_LENGTH
from core.identity_crypto import compute_identity_fingerprint
from core.lineage import compute_event_hash
from core.lineage_anchor import compute_tenant_anchor
from core.lineage_verify import verify_exported_lineage
from core.system_proof import verify_system_proof
from routers.anchors import MAX_SNAPSHOT_VERIFY_BODY_BYTES
from routers.lineage_verify import MAX_VERIFY_BODY_BYTES
from routers.proofs import MAX_PROOF_VERIFY_BODY_BYTES
from routers.system_verify import MAX_SYSTEM_VERIFY_BODY_BYTES


class RedTeamSecurityBaselineFreezeTests(unittest.TestCase):
    def test_frozen_canonical_serialization(self) -> None:
        payload = {"z": 1, "a": {"b": 2, "a": 1}, "n": [3, 2, 1]}
        self.assertEqual(canonical_json(payload), '{"a":{"a":1,"b":2},"n":[3,2,1],"z":1}')

    def test_frozen_hash_and_anchor_formats(self) -> None:
        event_hash = compute_event_hash(
            {"tenant_id": "t", "consent_id": "c", "action": "created", "payload": {}},
            None,
        )
        self.assertEqual(len(event_hash), 64)
        self.assertEqual(event_hash, "add0bc7b3376b67b13d04e96d6bb89e717f5c62ddc3b972bb349fdc8cce69a2b")

        anchor = compute_tenant_anchor("tenant-1", "a" * 64)
        self.assertEqual(anchor, "a13e2793c9b48461b84689417e3ff76db66c8d1b597ab7cff88ebbfbca8e821f")

        digest = compute_anchor_digest(["b" * 64, "a" * 64])
        self.assertEqual(digest, "5e9ae866add9a85d69c3481d059bb9f158a39e5670ba11f95112fc409630894e")

    def test_frozen_public_payload_limits(self) -> None:
        self.assertEqual(MAX_VERIFY_BODY_BYTES, 262_144)
        self.assertEqual(MAX_PROOF_VERIFY_BODY_BYTES, 262_144)
        self.assertEqual(MAX_SNAPSHOT_VERIFY_BODY_BYTES, 262_144)
        self.assertEqual(MAX_SYSTEM_VERIFY_BODY_BYTES, 262_144)
        self.assertEqual(MAX_IDEMPOTENCY_KEY_LENGTH, 255)

    def test_frozen_signature_precedence_over_hash_mismatch(self) -> None:
        signer_public = "ab" * 32
        export = {
            "version": 1,
            "tenant_id": "tenant-x",
            "consent_id": "consent-y",
            "algorithm": "SHA256",
            "canonicalization": "sorted-json-no-whitespace",
            "tenant_anchor": "0" * 64,
            "events": [
                {
                    "action": "created",
                    "event_hash": "0" * 64,
                    "prev_event_hash": None,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
            "signer_identity_fingerprint": compute_identity_fingerprint(signer_public),
            "signer_public_key": signer_public,
            "signature": "0" * 128,
        }
        result = verify_exported_lineage(export)
        self.assertFalse(result["verified"])
        self.assertIn("signature", str(result["failure_reason"]).lower())

    def test_frozen_system_proof_failure_classification(self) -> None:
        result = verify_system_proof(
            {
                "version": 1,
                "generated_at": "2026-02-26T00:00:00Z",
                "event_count": 1,
                "last_event_hash": "a" * 64,
                "events": [
                    {
                        "event_type": "x",
                        "tenant_id": None,
                        "resource_type": None,
                        "resource_id": None,
                        "payload_hash": None,
                        "prev_hash": None,
                        "event_hash": "a" * 64,
                    }
                ],
            }
        )
        self.assertFalse(result["verified"])
        self.assertIn("invalid payload_hash", str(result["failure_reason"]).lower())


if __name__ == "__main__":
    unittest.main()
