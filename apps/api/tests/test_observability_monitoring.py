import json
import sys
import types
import unittest
import uuid
from unittest.mock import MagicMock, patch


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
    sys.modules["cryptography.hazmat.primitives.asymmetric"] = asym_mod
    sys.modules["cryptography.hazmat.primitives.asymmetric.ed25519"] = ed_mod


_install_cryptography_stub()

from starlette.requests import Request

from core.identity_crypto import compute_identity_fingerprint
from core.observability import (
    COUNTERS,
    METRIC_SIGNATURE_VERIFICATION_FAILED,
    METRIC_TENANT_WRITE_DENIED,
)
from core.logging_utils import log_structured
from core.lineage_verify import verify_exported_lineage
from models.tenant import Tenant, TenantLifecycleState
from routers.consents import _ensure_tenant_writable
from routers.health import ready


class ObservabilityMonitoringTests(unittest.TestCase):
    def setUp(self) -> None:
        COUNTERS.reset()

    def _request(self, app) -> Request:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/ready",
            "headers": [],
            "app": app,
        }
        return Request(scope)

    def test_readiness_fails_when_db_unavailable(self) -> None:
        app = types.SimpleNamespace(state=types.SimpleNamespace(webhook_worker_task=None))
        req = self._request(app)
        with patch("routers.health.engine.connect", side_effect=RuntimeError("db down")):
            resp = ready(req)
        self.assertEqual(resp.status_code, 503)
        body = json.loads(resp.body.decode("utf-8"))
        self.assertEqual(body["status"], "not_ready")
        self.assertEqual(body["checks"]["db"], "failed")

    def test_readiness_fails_on_migration_mismatch(self) -> None:
        app = types.SimpleNamespace(state=types.SimpleNamespace(webhook_worker_task=None))
        req = self._request(app)

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def execute(self, _q):
                return 1

        with patch("routers.health.engine.connect", return_value=_Ctx()):
            with patch("routers.health.settings.expected_alembic_head", "abc123"):
                with patch("routers.health._current_alembic_heads", return_value="def456"):
                    resp = ready(req)
        self.assertEqual(resp.status_code, 503)
        body = json.loads(resp.body.decode("utf-8"))
        self.assertEqual(body["checks"]["migration_head"], "failed")

    def test_signature_failure_emits_metric_and_system_event(self) -> None:
        tenant_id = str(uuid.uuid4())
        consent_id = str(uuid.uuid4())
        signer_public_key = "ab" * 32
        signer_fingerprint = compute_identity_fingerprint(signer_public_key)

        import hashlib

        event_hash = hashlib.sha256(f"{tenant_id}|{consent_id}|created|{{}}|".encode("utf-8")).hexdigest()
        export = {
            "version": 1,
            "tenant_id": tenant_id,
            "consent_id": consent_id,
            "algorithm": "SHA256",
            "canonicalization": "sorted-json-no-whitespace",
            "tenant_anchor": hashlib.sha256(f"ANCHOR|{tenant_id}|{event_hash}".encode("utf-8")).hexdigest(),
            "events": [
                {
                    "action": "created",
                    "event_hash": event_hash,
                    "prev_event_hash": None,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
            "signer_identity_fingerprint": signer_fingerprint,
            "signer_public_key": signer_public_key,
            "signature": "00" * 64,
        }

        with patch("core.lineage_verify.verify_bytes", return_value=False):
            with patch("core.lineage_verify.best_effort_system_event") as event_mock:
                result = verify_exported_lineage(export)

        self.assertFalse(result["verified"])
        self.assertEqual(result["failure_reason"], "lineage signature verification failed")
        self.assertGreater(COUNTERS.value(METRIC_SIGNATURE_VERIFICATION_FAILED), 0)
        event_mock.assert_called_once()

    def test_forbidden_tenant_write_emits_audit_signal(self) -> None:
        tenant = Tenant(
            id=uuid.uuid4(),
            name="tenant-blocked",
            is_active=False,
            lifecycle_state=TenantLifecycleState.SUSPENDED,
        )
        with patch("routers.consents.best_effort_system_event") as event_mock:
            with self.assertRaises(Exception):
                _ensure_tenant_writable(tenant)
        self.assertGreater(COUNTERS.value(METRIC_TENANT_WRITE_DENIED), 0)
        event_mock.assert_called_once()

    def test_secrets_never_appear_in_logs(self) -> None:
        with self.assertLogs("consent_ledger.api", level="INFO") as capture:
            log_structured(
                "security.test",
                request_id="req-1",
                reason="private_key=super-secret-material",
                ignored_field="should_not_log",
            )
        joined = "\n".join(capture.output)
        self.assertNotIn("super-secret-material", joined)
        self.assertNotIn("ignored_field", joined)


if __name__ == "__main__":
    unittest.main()
