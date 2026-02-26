import hashlib
import unittest
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.identity_crypto import verify_public_key_format
from core.db import Base
from models.identity_key import IdentityKey, IdentityKeyScope


def _generate_public_key_hex() -> str:
    private_key = Ed25519PrivateKey.generate()
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return public_key_bytes.hex()


def _fingerprint(public_key_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()


class IdentityKeyTests(unittest.TestCase):
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

    def test_fingerprint_deterministic(self) -> None:
        pub = _generate_public_key_hex()
        fp_a = _fingerprint(pub)
        fp_b = _fingerprint(pub)
        self.assertEqual(fp_a, fp_b)

    def test_fingerprint_changes_with_key(self) -> None:
        pub_a = _generate_public_key_hex()
        pub_b = _generate_public_key_hex()
        self.assertNotEqual(_fingerprint(pub_a), _fingerprint(pub_b))

    def test_invalid_public_key_rejected(self) -> None:
        with self.assertRaises(ValueError):
            verify_public_key_format("zz" * 32)
        with self.assertRaises(ValueError):
            verify_public_key_format("ab" * 31)

    def test_identity_key_append_only(self) -> None:
        pub = _generate_public_key_hex()
        row = IdentityKey(
            scope=IdentityKeyScope.TENANT,
            owner_id=uuid.uuid4(),
            public_key=pub,
            fingerprint=_fingerprint(pub),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)

        persisted = self.db.scalar(select(IdentityKey).where(IdentityKey.id == row.id))
        self.assertIsNotNone(persisted)

        persisted.revoked_at = self.db.scalar(text("SELECT CURRENT_TIMESTAMP"))
        self.db.add(persisted)
        with self.assertRaisesRegex(Exception, "append-only"):
            self.db.commit()
        self.db.rollback()

        with self.assertRaisesRegex(Exception, "append-only"):
            self.db.delete(persisted)
            self.db.commit()
        self.db.rollback()

    def test_scope_isolation(self) -> None:
        pub_tenant = _generate_public_key_hex()
        pub_system = _generate_public_key_hex()
        pub_admin = _generate_public_key_hex()

        tenant_key = IdentityKey(
            scope=IdentityKeyScope.TENANT,
            owner_id=uuid.uuid4(),
            public_key=pub_tenant,
            fingerprint=_fingerprint(pub_tenant),
        )
        system_key = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key=pub_system,
            fingerprint=_fingerprint(pub_system),
        )
        admin_key = IdentityKey(
            scope=IdentityKeyScope.ADMIN,
            owner_id=None,
            public_key=pub_admin,
            fingerprint=_fingerprint(pub_admin),
        )
        self.db.add_all([tenant_key, system_key, admin_key])
        self.db.commit()

        rows = list(self.db.scalars(select(IdentityKey).order_by(IdentityKey.created_at.asc())).all())
        self.assertEqual(len(rows), 3)
        by_scope = {row.scope: row for row in rows}
        self.assertIsNotNone(by_scope[IdentityKeyScope.TENANT].owner_id)
        self.assertIsNone(by_scope[IdentityKeyScope.SYSTEM].owner_id)
        self.assertIsNone(by_scope[IdentityKeyScope.ADMIN].owner_id)

    def test_invalid_scope_owner_combinations_rejected_by_orm(self) -> None:
        pub_a = _generate_public_key_hex()
        invalid_tenant = IdentityKey(
            scope=IdentityKeyScope.TENANT,
            owner_id=None,
            public_key=pub_a,
            fingerprint=_fingerprint(pub_a),
        )
        self.db.add(invalid_tenant)
        with self.assertRaisesRegex(ValueError, "tenant scope requires owner_id"):
            self.db.commit()
        self.db.rollback()

        pub_b = _generate_public_key_hex()
        invalid_system = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=uuid.uuid4(),
            public_key=pub_b,
            fingerprint=_fingerprint(pub_b),
        )
        self.db.add(invalid_system)
        with self.assertRaisesRegex(ValueError, "system/admin scope requires owner_id to be null"):
            self.db.commit()
        self.db.rollback()

    def test_db_check_constraint_rejects_invalid_rows_when_orm_bypassed(self) -> None:
        with self.assertRaises(IntegrityError):
            self.db.execute(
                text(
                    """
                    INSERT INTO identity_keys (
                        id, scope, owner_id, public_key, fingerprint, created_at, revoked_at
                    ) VALUES (
                        :id, :scope, :owner_id, :public_key, :fingerprint, CURRENT_TIMESTAMP, NULL
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "scope": "tenant",
                    "owner_id": None,
                    "public_key": _generate_public_key_hex(),
                    "fingerprint": _fingerprint(_generate_public_key_hex()),
                },
            )
            self.db.commit()
        self.db.rollback()

    def test_migration_and_model_invariants_agree(self) -> None:
        inspector = inspect(self.engine)
        checks = {c["name"]: c["sqltext"] for c in inspector.get_check_constraints("identity_keys")}
        self.assertIn("ck_identity_keys_scope_owner", checks)
        model_check = checks["ck_identity_keys_scope_owner"]
        self.assertIn("scope = 'tenant'", model_check)
        self.assertIn("owner_id IS NOT NULL", model_check)
        self.assertIn("scope IN ('system', 'admin')", model_check)
        self.assertIn("owner_id IS NULL", model_check)

        migration_path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "d1a7c5e4f902_add_identity_keys.py"
        migration_source = migration_path.read_text(encoding="utf-8")
        self.assertIn("ck_identity_keys_scope_owner", migration_source)
        self.assertIn("(scope = 'tenant' AND owner_id IS NOT NULL)", migration_source)
        self.assertIn("(scope IN ('system', 'admin') AND owner_id IS NULL)", migration_source)


if __name__ == "__main__":
    unittest.main()
