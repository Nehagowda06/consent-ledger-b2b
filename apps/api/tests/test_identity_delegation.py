import hashlib
import unittest
import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.consent_proof import build_consent_proof
from core.db import Base
from core.delegation_crypto import canonical_delegation_message, sign_delegation
from core.delegation_verify import verify_delegation_chain
from core.lineage_verify import verify_consent_proof
from models.identity_delegation import IdentityDelegation
from models.identity_key import IdentityKey, IdentityKeyScope
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


class IdentityDelegationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_valid_rotation_chain_verifies(self) -> None:
        root_pub, root_priv = _generate_keypair_hex()
        child_pub, _ = _generate_keypair_hex()
        root_fp = _fingerprint(root_pub)
        child_fp = _fingerprint(child_pub)
        msg = canonical_delegation_message(root_fp, child_fp, "rotation")
        sig = sign_delegation(root_priv, msg)

        chain = [
            {
                "parent_fingerprint": root_fp,
                "child_fingerprint": child_fp,
                "delegation_type": "rotation",
                "parent_public_key": root_pub,
                "child_public_key": child_pub,
                "signature": sig,
                "created_at": "2026-02-25T00:00:00Z",
            }
        ]
        self.assertTrue(verify_delegation_chain(chain, root_fp))

    def test_tampered_delegation_signature_fails(self) -> None:
        root_pub, root_priv = _generate_keypair_hex()
        child_pub, _ = _generate_keypair_hex()
        root_fp = _fingerprint(root_pub)
        child_fp = _fingerprint(child_pub)
        msg = canonical_delegation_message(root_fp, child_fp, "rotation")
        sig = sign_delegation(root_priv, msg)
        bad_sig = ("0" if sig[0] != "0" else "1") + sig[1:]

        chain = [
            {
                "parent_fingerprint": root_fp,
                "child_fingerprint": child_fp,
                "delegation_type": "rotation",
                "parent_public_key": root_pub,
                "child_public_key": child_pub,
                "signature": bad_sig,
                "created_at": "2026-02-25T00:00:00Z",
            }
        ]
        self.assertFalse(verify_delegation_chain(chain, root_fp))

    def test_cycle_detection_fails(self) -> None:
        root_pub, root_priv = _generate_keypair_hex()
        child_pub, child_priv = _generate_keypair_hex()
        root_fp = _fingerprint(root_pub)
        child_fp = _fingerprint(child_pub)

        sig_a = sign_delegation(root_priv, canonical_delegation_message(root_fp, child_fp, "delegation"))
        sig_b = sign_delegation(child_priv, canonical_delegation_message(child_fp, root_fp, "delegation"))

        chain = [
            {
                "parent_fingerprint": root_fp,
                "child_fingerprint": child_fp,
                "delegation_type": "delegation",
                "parent_public_key": root_pub,
                "child_public_key": child_pub,
                "signature": sig_a,
                "created_at": "2026-02-25T00:00:00Z",
            },
            {
                "parent_fingerprint": child_fp,
                "child_fingerprint": root_fp,
                "delegation_type": "delegation",
                "parent_public_key": child_pub,
                "child_public_key": root_pub,
                "signature": sig_b,
                "created_at": "2026-02-25T00:01:00Z",
            },
        ]
        self.assertFalse(verify_delegation_chain(chain, root_fp))

    def test_old_proofs_remain_verifiable_after_rotation(self) -> None:
        tenant = Tenant(id=uuid.uuid4(), name="tenant-delegation-proof")
        self.db.add(tenant)
        self.db.commit()

        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="deleg-proof-subj", purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=tenant,
        )
        proof = build_consent_proof(
            consent_id=consent.id,
            tenant_id=tenant.id,
            asserted_at=datetime.now(timezone.utc),
            db=self.db,
        )
        before = verify_consent_proof(proof)
        self.assertTrue(before["verified"])

        root_pub, root_priv = _generate_keypair_hex()
        child_pub, _ = _generate_keypair_hex()
        root_key = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key=root_pub,
            fingerprint=_fingerprint(root_pub),
        )
        child_key = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key=child_pub,
            fingerprint=_fingerprint(child_pub),
        )
        self.db.add(root_key)
        self.db.add(child_key)
        self.db.commit()

        delegation = IdentityDelegation(
            parent_identity_key_id=root_key.id,
            child_identity_key_id=child_key.id,
            delegation_type="rotation",
            signature=sign_delegation(
                root_priv,
                canonical_delegation_message(root_key.fingerprint, child_key.fingerprint, "rotation"),
            ),
        )
        self.db.add(delegation)
        self.db.commit()

        after = verify_consent_proof(proof)
        self.assertTrue(after["verified"])

    def test_append_only_enforcement_update_delete_rejected(self) -> None:
        root_pub, root_priv = _generate_keypair_hex()
        child_pub, _ = _generate_keypair_hex()
        root_key = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key=root_pub,
            fingerprint=_fingerprint(root_pub),
        )
        child_key = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key=child_pub,
            fingerprint=_fingerprint(child_pub),
        )
        self.db.add(root_key)
        self.db.add(child_key)
        self.db.commit()

        row = IdentityDelegation(
            parent_identity_key_id=root_key.id,
            child_identity_key_id=child_key.id,
            delegation_type="rotation",
            signature=sign_delegation(
                root_priv,
                canonical_delegation_message(root_key.fingerprint, child_key.fingerprint, "rotation"),
            ),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)

        row.delegation_type = "delegation"
        self.db.add(row)
        with self.assertRaisesRegex(Exception, "append-only"):
            self.db.commit()
        self.db.rollback()

        with self.assertRaisesRegex(Exception, "append-only"):
            self.db.delete(row)
            self.db.commit()
        self.db.rollback()


if __name__ == "__main__":
    unittest.main()

