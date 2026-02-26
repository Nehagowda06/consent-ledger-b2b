import types
import unittest
import uuid
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from core.auth import require_tenant
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


class AuthDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = object()
        tenant_id = uuid.uuid4()
        self.tenant = Tenant(id=tenant_id, name="tenant-a", is_active=True)
        self.api_key_record = ApiKey(
            tenant_id=tenant_id,
            key_hash="irrelevant-for-test",
            label="test-key",
            revoked_at=None,
        )

    def test_missing_key_returns_401(self) -> None:
        request = make_request({})
        with self.assertRaises(HTTPException) as exc:
            require_tenant(request, self.db)
        self.assertEqual(exc.exception.status_code, 401)

    @patch("core.auth.hash_api_key", return_value="hash123")
    @patch("core.auth._get_api_key_record", return_value=None)
    def test_invalid_key_returns_401(self, _mock_get_key, _mock_hash) -> None:
        request = make_request({"Authorization": "Bearer invalid-key"})
        with self.assertRaises(HTTPException) as exc:
            require_tenant(request, self.db)
        self.assertEqual(exc.exception.status_code, 401)

    @patch("core.auth.hash_api_key", return_value="hash123")
    @patch("core.auth.hmac.compare_digest", return_value=True)
    @patch("core.auth._get_api_key_record")
    def test_revoked_key_returns_401(self, mock_get_key, _mock_compare, _mock_hash) -> None:
        revoked_record = types.SimpleNamespace(
            key_hash="hash123",
            tenant_id=self.tenant.id,
            revoked_at="2026-01-01T00:00:00Z",
        )
        mock_get_key.return_value = revoked_record
        request = make_request({"Authorization": "Bearer revoked-key"})
        with self.assertRaises(HTTPException) as exc:
            require_tenant(request, self.db)
        self.assertEqual(exc.exception.status_code, 401)

    @patch("core.auth.hash_api_key", return_value="hash123")
    @patch("core.auth.hmac.compare_digest", return_value=True)
    @patch("core.auth._get_tenant")
    @patch("core.auth._get_api_key_record")
    def test_valid_key_returns_tenant(
        self,
        mock_get_key,
        mock_get_tenant,
        _mock_compare,
        _mock_hash,
    ) -> None:
        record = types.SimpleNamespace(
            key_hash="hash123",
            tenant_id=self.tenant.id,
            revoked_at=None,
        )
        mock_get_key.return_value = record
        mock_get_tenant.return_value = self.tenant
        request = make_request({"Authorization": "Bearer valid-key"})

        result = require_tenant(request, self.db)

        self.assertEqual(result.id, self.tenant.id)
        self.assertEqual(request.state.tenant_id, self.tenant.id)


if __name__ == "__main__":
    unittest.main()
