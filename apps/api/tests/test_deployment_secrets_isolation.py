import os
import sys
import types
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _install_cryptography_stub() -> None:
    if "cryptography.hazmat.primitives.asymmetric.ed25519" in sys.modules:
        return

    class _FakePrivateKey:
        @staticmethod
        def from_private_bytes(_value):
            return _FakePrivateKey()

        def sign(self, message: bytes) -> bytes:
            return (message[:32] + b"\x00" * 32)[:64]

    class _FakePublicKey:
        @staticmethod
        def from_public_bytes(_value):
            return _FakePublicKey()

        def verify(self, signature: bytes, message: bytes) -> None:
            expected = (message[:32] + b"\x00" * 32)[:64]
            if signature != expected:
                raise ValueError("invalid signature")

    serialization_mod = types.ModuleType("cryptography.hazmat.primitives.serialization")

    crypto_mod = types.ModuleType("cryptography")
    hazmat_mod = types.ModuleType("cryptography.hazmat")
    primitives_mod = types.ModuleType("cryptography.hazmat.primitives")
    asym_mod = types.ModuleType("cryptography.hazmat.primitives.asymmetric")
    ed_mod = types.ModuleType("cryptography.hazmat.primitives.asymmetric.ed25519")
    ed_mod.Ed25519PrivateKey = _FakePrivateKey
    ed_mod.Ed25519PublicKey = _FakePublicKey

    sys.modules["cryptography"] = crypto_mod
    sys.modules["cryptography.hazmat"] = hazmat_mod
    sys.modules["cryptography.hazmat.primitives"] = primitives_mod
    sys.modules["cryptography.hazmat.primitives.serialization"] = serialization_mod
    sys.modules["cryptography.hazmat.primitives.asymmetric"] = asym_mod
    sys.modules["cryptography.hazmat.primitives.asymmetric.ed25519"] = ed_mod


_install_cryptography_stub()

from core.config import Settings, reset_settings_cache
from core.db import Base
from core.identity_crypto import compute_identity_fingerprint
from core.lineage import add_lineage_event
from core.lineage_export import export_consent_lineage
from core.logging_utils import log_request
from models.consent import Consent
from models.identity_key import IdentityKey, IdentityKeyScope
from models.tenant import Tenant


class DeploymentSecretsIsolationTests(unittest.TestCase):
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
        reset_settings_cache()

    def test_prod_startup_fails_when_required_secret_missing(self) -> None:
        env = {
            "ENV": "prod",
            "DATABASE_URL": "sqlite:///prod.db",
            "API_KEY_HASH_SECRET": "api",
            "WEBHOOK_SIGNING_SECRET": "webhook",
            "ADMIN_API_KEY": "",
            "CORS_ALLOWED_ORIGINS": "https://example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ADMIN_API_KEY is required in prod"):
                Settings()

    def test_dev_allows_explicit_insecure_defaults(self) -> None:
        with patch.dict(os.environ, {"ENV": "dev"}, clear=True):
            settings = Settings()
        self.assertEqual(settings.env, "dev")
        self.assertTrue(bool(settings.admin_api_key))
        self.assertTrue(bool(settings.api_key_hash_secret))
        self.assertTrue(bool(settings.webhook_signing_secret))

    def test_env_misconfiguration_detected_early(self) -> None:
        with patch.dict(os.environ, {"ENV": "production"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ENV must be one of"):
                Settings()

    def test_private_keys_never_persisted_or_logged(self) -> None:
        private_key_material = "super-secret-private-key"
        key = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key="ab" * 32,
            fingerprint=compute_identity_fingerprint("ab" * 32),
        )
        self.db.add(key)
        self.db.commit()
        self.db.refresh(key)

        column_names = set(IdentityKey.__table__.columns.keys())
        self.assertNotIn("private_key", column_names)
        self.assertNotIn(private_key_material, repr(key))

        with self.assertLogs("consent_ledger.api", level="INFO") as capture:
            log_request("req-1", "GET", "/health", 200, 1.23)
        self.assertTrue(capture.output)
        self.assertNotIn(private_key_material, "\n".join(capture.output))

    def test_signing_impossible_without_explicit_key_material(self) -> None:
        tenant = Tenant(id=uuid.uuid4(), name="tenant-signing-test")
        consent = Consent(tenant_id=tenant.id, subject_id="subject", purpose="email")
        self.db.add(tenant)
        self.db.add(consent)
        self.db.flush()
        add_lineage_event(self.db, consent, "created")
        self.db.commit()

        with self.assertRaisesRegex(ValueError, "lineage signing requires fingerprint, public_key, and private_key"):
            export_consent_lineage(
                consent_id=consent.id,
                tenant_id=tenant.id,
                db=self.db,
                signer_identity_fingerprint="fp",
                signer_public_key="ab" * 32,
                signer_private_key_hex=None,
            )


if __name__ == "__main__":
    unittest.main()
