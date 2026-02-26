import tempfile
import types
import unittest
import uuid
import shutil
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from core.api_keys import hash_api_key
from core.auth import require_tenant
from core.rate_limit import SQLiteRateLimiter
from models.api_key import ApiKey
from models.tenant import Tenant


def make_request(raw_key: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"authorization", f"Bearer {raw_key}".encode("latin-1"))],
        "client": ("127.0.0.1", 12222),
    }
    return Request(scope)


class _FakeDB:
    def __init__(self, api_key: ApiKey, tenant: Tenant) -> None:
        self.api_key = api_key
        self.tenant = tenant

    def scalar(self, _stmt):
        return self.api_key

    def get(self, _model, _tenant_id):
        return self.tenant


class RateLimitResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-rl", is_active=True)
        self.raw_key = "clb2b_rl_resilience"
        self.api_key = ApiKey(tenant_id=self.tenant.id, key_hash=hash_api_key(self.raw_key), label="rl")
        self.db = _FakeDB(api_key=self.api_key, tenant=self.tenant)

    def test_burst_under_at_and_over_limit(self) -> None:
        tmpdir = Path(tempfile.mkdtemp())
        try:
            limiter = SQLiteRateLimiter(db_path=str(tmpdir / "rl.sqlite3"), limit_per_minute=3)
            identity = "apikey:test"
            self.assertTrue(limiter.allow(identity))
            self.assertTrue(limiter.allow(identity))
            self.assertTrue(limiter.allow(identity))
            self.assertFalse(limiter.allow(identity))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_limiter_backend_failure_fails_closed_in_prod(self) -> None:
        request = make_request(self.raw_key)
        with patch("core.auth.RATE_LIMITER", types.SimpleNamespace(allow=lambda _i: (_ for _ in ()).throw(RuntimeError("db down")))):
            with patch("core.auth.settings", new=types.SimpleNamespace(env="prod")):
                with self.assertRaises(HTTPException) as exc:
                    require_tenant(request=request, db=self.db)
        self.assertEqual(exc.exception.status_code, 503)

    def test_limiter_backend_failure_does_not_unlock_all_in_dev(self) -> None:
        request = make_request(self.raw_key)
        with patch("core.auth.RATE_LIMITER", types.SimpleNamespace(allow=lambda _i: (_ for _ in ()).throw(RuntimeError("db down")))):
            with patch("core.auth.settings", new=types.SimpleNamespace(env="dev")):
                tenant = require_tenant(request=request, db=self.db)
        self.assertEqual(tenant.id, self.tenant.id)

    def test_limiter_restart_mid_traffic_preserves_window(self) -> None:
        tmpdir = Path(tempfile.mkdtemp())
        try:
            path = str(tmpdir / "rl.sqlite3")
            limiter_a = SQLiteRateLimiter(db_path=path, limit_per_minute=2)
            identity = "apikey:restart"
            self.assertTrue(limiter_a.allow(identity))
            self.assertTrue(limiter_a.allow(identity))
            limiter_b = SQLiteRateLimiter(db_path=path, limit_per_minute=2)
            self.assertFalse(limiter_b.allow(identity))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
