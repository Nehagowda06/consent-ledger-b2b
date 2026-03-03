import hashlib
import unittest
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.assertion_crypto import canonical_assertion_payload, sign_assertion, verify_assertion_signature
from core.db import Base
from models.identity_key import IdentityKey, IdentityKeyScope
from models.signed_assertion import SignedAssertion


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


class SignedAssertionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.public_key_hex, self.private_key_hex = _generate_keypair_hex()
        self.identity_key = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key=self.public_key_hex,
            fingerprint=_fingerprint(self.public_key_hex),
        )
        self.db.add(self.identity_key)
        self.db.commit()
        self.db.refresh(self.identity_key)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_valid_signature_verifies(self) -> None:
        payload = {"asserted": True, "state": "ACTIVE"}
        message = canonical_assertion_payload(payload)
        signature = sign_assertion(self.private_key_hex, message)
        self.assertTrue(verify_assertion_signature(self.public_key_hex, message, signature))

    def test_tampered_payload_fails_verification(self) -> None:
        payload = {"asserted": True, "state": "ACTIVE"}
        message = canonical_assertion_payload(payload)
        signature = sign_assertion(self.private_key_hex, message)
        tampered_message = canonical_assertion_payload({"asserted": True, "state": "REVOKED"})
        self.assertFalse(verify_assertion_signature(self.public_key_hex, tampered_message, signature))

    def test_wrong_key_fails_verification(self) -> None:
        other_public, _ = _generate_keypair_hex()
        payload = {"asserted": True, "type": "exists"}
        message = canonical_assertion_payload(payload)
        signature = sign_assertion(self.private_key_hex, message)
        self.assertFalse(verify_assertion_signature(other_public, message, signature))

    def test_append_only_enforcement(self) -> None:
        payload = {"asserted": True, "kind": "state_at_time"}
        message = canonical_assertion_payload(payload)
        signature = sign_assertion(self.private_key_hex, message)
        row = SignedAssertion(
            identity_key_id=self.identity_key.id,
            subject_type="consent",
            subject_id=str(uuid.uuid4()),
            assertion_type="state_at_time",
            payload=payload,
            signature=signature,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)

        row.signature = "00" * 64
        self.db.add(row)
        with self.assertRaisesRegex(Exception, "append-only"):
            self.db.commit()
        self.db.rollback()

        with self.assertRaisesRegex(Exception, "append-only"):
            self.db.delete(row)
            self.db.commit()
        self.db.rollback()

    def test_assertion_round_trip_unchanged(self) -> None:
        payload = {"a": 1, "b": "two", "nested": {"k": "v"}}
        message = canonical_assertion_payload(payload)
        signature = sign_assertion(self.private_key_hex, message)
        subject_id = str(uuid.uuid4())
        row = SignedAssertion(
            identity_key_id=self.identity_key.id,
            subject_type="tenant",
            subject_id=subject_id,
            assertion_type="exists",
            payload=payload,
            signature=signature,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)

        fetched = self.db.scalar(select(SignedAssertion).where(SignedAssertion.id == row.id))
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.identity_key_id, self.identity_key.id)
        self.assertEqual(fetched.subject_type, "tenant")
        self.assertEqual(fetched.subject_id, subject_id)
        self.assertEqual(fetched.assertion_type, "exists")
        self.assertEqual(fetched.payload, payload)
        self.assertEqual(fetched.signature, signature)


if __name__ == "__main__":
    unittest.main()

