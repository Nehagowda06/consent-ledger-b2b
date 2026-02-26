import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from core.identity_crypto import compute_identity_fingerprint
from models.identity_key import IdentityKey, IdentityKeyScope


class IdentityKeyInvariantTests(unittest.TestCase):
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

    def _valid_public_key(self) -> str:
        return "11" * 32

    def test_tenant_scope_requires_owner_id(self) -> None:
        pub = self._valid_public_key()
        row = IdentityKey(
            scope=IdentityKeyScope.TENANT,
            owner_id=None,
            public_key=pub,
            fingerprint=compute_identity_fingerprint(pub),
        )
        self.db.add(row)
        with self.assertRaisesRegex(ValueError, "tenant scope requires owner_id"):
            self.db.commit()
        self.db.rollback()

    def test_system_admin_scope_forbids_owner_id(self) -> None:
        pub_a = self._valid_public_key()
        system_row = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=uuid.uuid4(),
            public_key=pub_a,
            fingerprint=compute_identity_fingerprint(pub_a),
        )
        self.db.add(system_row)
        with self.assertRaisesRegex(ValueError, "system/admin scope requires owner_id to be null"):
            self.db.commit()
        self.db.rollback()

        pub_b = "22" * 32
        admin_row = IdentityKey(
            scope=IdentityKeyScope.ADMIN,
            owner_id=uuid.uuid4(),
            public_key=pub_b,
            fingerprint=compute_identity_fingerprint(pub_b),
        )
        self.db.add(admin_row)
        with self.assertRaisesRegex(ValueError, "system/admin scope requires owner_id to be null"):
            self.db.commit()
        self.db.rollback()

    def test_revoked_at_cannot_be_unset(self) -> None:
        pub = self._valid_public_key()
        initial_ts = datetime.now(timezone.utc)
        row = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key=pub,
            fingerprint=compute_identity_fingerprint(pub),
            revoked_at=initial_ts,
        )
        self.db.add(row)
        self.db.commit()

        stored = self.db.scalar(select(IdentityKey).where(IdentityKey.id == row.id))
        self.assertIsNotNone(stored)
        stored.revoked_at = None
        self.db.add(stored)
        with self.assertRaisesRegex(ValueError, "identity_keys.revoked_at is immutable once set"):
            self.db.commit()
        self.db.rollback()

    def test_revoked_at_cannot_be_modified(self) -> None:
        pub = self._valid_public_key()
        initial_ts = datetime.now(timezone.utc)
        row = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key=pub,
            fingerprint=compute_identity_fingerprint(pub),
            revoked_at=initial_ts,
        )
        self.db.add(row)
        self.db.commit()

        stored = self.db.scalar(select(IdentityKey).where(IdentityKey.id == row.id))
        self.assertIsNotNone(stored)
        stored.revoked_at = initial_ts + timedelta(seconds=1)
        self.db.add(stored)
        with self.assertRaisesRegex(ValueError, "identity_keys.revoked_at is immutable once set"):
            self.db.commit()
        self.db.rollback()

    def test_invalid_public_key_rejected(self) -> None:
        row = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key="xyz-not-hex",
            fingerprint="00" * 32,
        )
        self.db.add(row)
        with self.assertRaises(ValueError):
            self.db.commit()
        self.db.rollback()

    def test_fingerprint_mismatch_rejected(self) -> None:
        pub = self._valid_public_key()
        row = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key=pub,
            fingerprint="ff" * 32,
        )
        self.db.add(row)
        with self.assertRaisesRegex(ValueError, "public_key does not match fingerprint"):
            self.db.commit()
        self.db.rollback()

    def test_public_key_cannot_be_reused_across_scopes(self) -> None:
        pub = self._valid_public_key()
        fingerprint = compute_identity_fingerprint(pub)
        tenant_row = IdentityKey(
            scope=IdentityKeyScope.TENANT,
            owner_id=uuid.uuid4(),
            public_key=pub,
            fingerprint=fingerprint,
        )
        self.db.add(tenant_row)
        self.db.commit()

        system_row = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key=pub,
            fingerprint=fingerprint,
        )
        self.db.add(system_row)
        with self.assertRaisesRegex(ValueError, "fingerprint already bound"):
            self.db.commit()
        self.db.rollback()


if __name__ == "__main__":
    unittest.main()
