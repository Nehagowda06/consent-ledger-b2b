import asyncio
import hashlib
import sys
import types
import unittest
import uuid
from unittest.mock import patch


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

from core.lineage_anchor import compute_tenant_anchor
from core.lineage_verify import verify_consent_proof
from core.release import validate_release_startup


def _settings(**overrides):
    base = {
        "env": "prod",
        "log_level": "INFO",
        "auto_create_schema": False,
        "database_url": "sqlite:///test.db",
        "api_key_hash_secret": "x",
        "webhook_signing_secret": "y",
        "admin_api_key": "z",
        "cors_allowed_origins": ["https://example.com"],
        "api_key_rate_limit_per_min": 10,
        "expected_alembic_head": "head1",
        "release_supported_api_versions": ["v1"],
        "release_feature_flags": [],
        "signing_mode": "disabled",
        "signing_required": False,
        "signing_enabled": False,
        "version_hash": "sha-1",
    }
    base.update(overrides)
    return types.SimpleNamespace(**base)


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def execute(self, _query):
        return 1


class _FakeDB:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class ReleaseUpgradeManagementTests(unittest.TestCase):
    def test_startup_fails_on_alembic_mismatch(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Alembic head mismatch"):
            validate_release_startup(_settings(expected_alembic_head="expected"), "actual")

    def test_forbidden_prod_configs_fail_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "LOG_LEVEL=DEBUG is not allowed in prod"):
            validate_release_startup(_settings(log_level="DEBUG"), "head1")
        with self.assertRaisesRegex(RuntimeError, "AUTO_CREATE_SCHEMA must be false in prod"):
            validate_release_startup(_settings(auto_create_schema=True), "head1")

    def test_startup_records_release_metadata_event(self) -> None:
        import main as main_module

        fake_settings = _settings(signing_mode="disabled", signing_enabled=False)
        with patch.object(main_module, "settings", fake_settings):
            with patch.object(main_module, "_current_alembic_heads", return_value="head1"):
                with patch.object(main_module, "SessionLocal", return_value=_FakeDB()):
                    with patch.object(main_module.engine, "connect", return_value=_Conn()):
                        with patch.object(main_module, "record_system_event") as event_mock:
                            with patch.object(main_module, "start_webhook_worker", return_value=None):
                                asyncio.run(main_module.on_startup())
        self.assertTrue(event_mock.called)
        payload = event_mock.call_args.kwargs["payload"]
        self.assertEqual(payload["code_sha"], "sha-1")
        self.assertIn("release", payload)
        self.assertEqual(payload["release"]["supported_api_versions"], ("v1",))

    def test_upgrade_does_not_change_verification_results_for_existing_proofs(self) -> None:
        tenant_id = str(uuid.uuid4())
        consent_id = str(uuid.uuid4())
        event_hash = hashlib.sha256(f"{tenant_id}|{consent_id}|created|{{}}|".encode("utf-8")).hexdigest()
        lineage = {
            "version": 1,
            "tenant_id": tenant_id,
            "consent_id": consent_id,
            "algorithm": "SHA256",
            "canonicalization": "sorted-json-no-whitespace",
            "tenant_anchor": compute_tenant_anchor(tenant_id, event_hash),
            "events": [
                {
                    "action": "created",
                    "event_hash": event_hash,
                    "prev_event_hash": None,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        }
        proof = {
            "version": 1,
            "proof_type": "CONSENT_STATE_AT_TIME",
            "tenant_id": tenant_id,
            "consent_id": consent_id,
            "asserted_at": "2026-01-01T00:00:00Z",
            "asserted_state": "ACTIVE",
            "tenant_anchor": lineage["tenant_anchor"],
            "lineage": lineage,
            "included_events": [
                {
                    "action": "created",
                    "event_hash": event_hash,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        }
        before = verify_consent_proof(proof)
        validate_release_startup(_settings(version_hash="sha-old"), "head1")
        validate_release_startup(_settings(version_hash="sha-new", release_feature_flags=["x"]), "head1")
        after = verify_consent_proof(proof)
        self.assertEqual(before, after)
        self.assertTrue(after["verified"])


if __name__ == "__main__":
    unittest.main()
