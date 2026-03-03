from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.consent_proof import build_consent_proof
from core.identity_crypto import compute_identity_fingerprint, verify_public_key_format
from core.lineage_verify import verify_consent_proof
from models.tenant import Tenant
from routers.consents import upsert_consent
from schemas.consent import ConsentUpsert
from tests.red_team._helpers import make_memory_session


class RedTeamCryptoIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self.engine = make_memory_session()
        self.tenant = Tenant(
            id=uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
            name="rt-crypto-tenant",
        )
        self.db.add(self.tenant)
        self.db.commit()
        self.consent = upsert_consent(
            payload=ConsentUpsert(subject_id="rt-crypto-subj", purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        fixed_private_bytes = bytes.fromhex("11" * 32)
        self.private_key = Ed25519PrivateKey.from_private_bytes(fixed_private_bytes)
        self.private_key_hex = fixed_private_bytes.hex()
        self.public_key_hex = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()
        self.fingerprint = compute_identity_fingerprint(self.public_key_hex)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_rejects_truncated_and_non_hex_public_keys(self) -> None:
        with self.assertRaises(ValueError):
            verify_public_key_format(self.public_key_hex[:-2])
        with self.assertRaises(ValueError):
            verify_public_key_format("zz" * 32)

    def test_signed_proof_rejects_cross_context_replay(self) -> None:
        proof = build_consent_proof(
            consent_id=self.consent.id,
            tenant_id=self.tenant.id,
            asserted_at=datetime.now(timezone.utc),
            db=self.db,
            signer_identity_fingerprint=self.fingerprint,
            signer_public_key=self.public_key_hex,
            signer_private_key_hex=self.private_key_hex,
        )
        proof["tenant_id"] = "00000000-0000-0000-0000-0000000000bb"
        result = verify_consent_proof(proof)
        self.assertFalse(result["verified"])
        self.assertIn("tenant", str(result["failure_reason"]).lower())

    def test_signed_proof_rejects_signer_confusion(self) -> None:
        proof = build_consent_proof(
            consent_id=self.consent.id,
            tenant_id=self.tenant.id,
            asserted_at=datetime.now(timezone.utc),
            db=self.db,
            signer_identity_fingerprint=self.fingerprint,
            signer_public_key=self.public_key_hex,
            signer_private_key_hex=self.private_key_hex,
        )
        other_private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("22" * 32))
        other_public = other_private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()
        proof["signer_public_key"] = other_public
        result = verify_consent_proof(proof)
        self.assertFalse(result["verified"])
        self.assertIn("signer", str(result["failure_reason"]).lower())


if __name__ == "__main__":
    unittest.main()
