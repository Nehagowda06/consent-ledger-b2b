import asyncio
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
from core.webhook_worker import start_webhook_worker, stop_webhook_worker
from models.api_key import ApiKey
from models.tenant import Tenant


def make_request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
        "client": ("127.0.0.1", 12345),
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


class RateLimitGuardrailTests(unittest.TestCase):
    def test_rate_limiting_blocks_after_threshold(self) -> None:
        tenant = Tenant(id=uuid.uuid4(), name="tenant-rate-limit", is_active=True)
        raw_key = "clb2b_rate_limit_test"
        api_key = ApiKey(tenant_id=tenant.id, key_hash=hash_api_key(raw_key), label="rl")
        db = _FakeDB(api_key=api_key, tenant=tenant)

        tmpdir = Path(tempfile.mkdtemp())
        try:
            limiter = SQLiteRateLimiter(db_path=str(tmpdir / "rl.sqlite3"), limit_per_minute=1)
            request = make_request({"Authorization": f"Bearer {raw_key}"})
            with patch("core.auth.RATE_LIMITER", limiter):
                require_tenant(request=request, db=db)
                with self.assertRaises(HTTPException) as exc:
                    require_tenant(request=request, db=db)
                self.assertEqual(exc.exception.status_code, 429)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class WebhookWorkerGuardrailTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_does_not_start_when_disabled(self) -> None:
        app = types.SimpleNamespace(state=types.SimpleNamespace())
        with patch("core.webhook_worker.get_settings", return_value=types.SimpleNamespace(webhook_worker_enabled=False)):
            start_webhook_worker(app)
        self.assertIsNone(getattr(app.state, "webhook_worker_task", None))

    async def test_worker_starts_when_enabled(self) -> None:
        app = types.SimpleNamespace(state=types.SimpleNamespace())

        async def _dummy_loop(_app):
            await asyncio.sleep(60)

        with patch("core.webhook_worker._worker_loop", _dummy_loop):
            with patch("core.webhook_worker.get_settings", return_value=types.SimpleNamespace(webhook_worker_enabled=True)):
                start_webhook_worker(app)
                task = getattr(app.state, "webhook_worker_task", None)
                self.assertIsNotNone(task)
                await stop_webhook_worker(app)
                self.assertIsNone(getattr(app.state, "webhook_worker_task", None))


if __name__ == "__main__":
    unittest.main()
