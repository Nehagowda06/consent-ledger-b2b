import hashlib
import unittest
import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.consent_proof import build_consent_proof
from core.db import Base
from core.lineage_export import export_consent_lineage
from core.lineage_verify import verify_consent_proof, verify_exported_lineage
from models.tenant import Tenant
from routers.consents import upsert_consent
from schemas.consent import ConsentUpsert


def _generate_keypair_hex() -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return public_bytes.hex(), private_bytes.hex()


def _fingerprint(public_key_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()


class LineageSignatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-lineage-sign")
        self.db.add(self.tenant)
        self.db.commit()
        self.consent = upsert_consent(
            payload=ConsentUpsert(subject_id="sig-subj", purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        self.public_key_hex, self.private_key_hex = _generate_keypair_hex()
        self.fingerprint = _fingerprint(self.public_key_hex)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_signed_lineage_verifies(self) -> None:
        artifact = export_consent_lineage(
            self.consent.id,
            self.tenant.id,
            self.db,
            signer_identity_fingerprint=self.fingerprint,
            signer_public_key=self.public_key_hex,
            signer_private_key_hex=self.private_key_hex,
        )
        result = verify_exported_lineage(artifact)
        self.assertTrue(result["verified"])

    def test_tampered_lineage_fails_signature_verification(self) -> None:
        artifact = export_consent_lineage(
            self.consent.id,
            self.tenant.id,
            self.db,
            signer_identity_fingerprint=self.fingerprint,
            signer_public_key=self.public_key_hex,
            signer_private_key_hex=self.private_key_hex,
        )
        artifact["events"][0]["action"] = "revoked"
        result = verify_exported_lineage(artifact)
        self.assertFalse(result["verified"])
        self.assertIn("signature", str(result["failure_reason"]))

    def test_wrong_public_key_fails_signature_verification(self) -> None:
        artifact = export_consent_lineage(
            self.consent.id,
            self.tenant.id,
            self.db,
            signer_identity_fingerprint=self.fingerprint,
            signer_public_key=self.public_key_hex,
            signer_private_key_hex=self.private_key_hex,
        )
        wrong_public, _ = _generate_keypair_hex()
        artifact["signer_public_key"] = wrong_public
        result = verify_exported_lineage(artifact)
        self.assertFalse(result["verified"])

    def test_unsigned_lineage_still_verifies(self) -> None:
        artifact = export_consent_lineage(self.consent.id, self.tenant.id, self.db)
        result = verify_exported_lineage(artifact)
        self.assertTrue(result["verified"])

    def test_proof_signature_survives_round_trip(self) -> None:
        proof = build_consent_proof(
            consent_id=self.consent.id,
            tenant_id=self.tenant.id,
            asserted_at=datetime.now(timezone.utc),
            db=self.db,
            signer_identity_fingerprint=self.fingerprint,
            signer_public_key=self.public_key_hex,
            signer_private_key_hex=self.private_key_hex,
        )
        self.assertIn("proof_signature", proof)
        result = verify_consent_proof(dict(proof))
        self.assertTrue(result["verified"])

    def test_signed_proof_rejects_timestamp_tampering(self) -> None:
        proof = build_consent_proof(
            consent_id=self.consent.id,
            tenant_id=self.tenant.id,
            asserted_at=datetime.now(timezone.utc),
            db=self.db,
            signer_identity_fingerprint=self.fingerprint,
            signer_public_key=self.public_key_hex,
            signer_private_key_hex=self.private_key_hex,
        )
        proof["lineage"]["events"][0]["created_at"] = "1999-01-01T00:00:00Z"
        proof["included_events"][0]["created_at"] = "1999-01-01T00:00:00Z"
        result = verify_consent_proof(dict(proof))
        self.assertFalse(result["verified"])
        self.assertIn("signature", str(result["failure_reason"]).lower())


if __name__ == "__main__":
    unittest.main()

