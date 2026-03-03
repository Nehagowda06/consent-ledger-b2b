import types
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.admin_auth import require_admin
from core.api_keys import hash_api_key
from core.auth import require_tenant
from core.db import Base
from models.api_key import ApiKey
from models.tenant import Tenant
from routers.admin import router as admin_router


def make_request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


class AdminSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-sec", is_active=True)
        self.db.add(self.tenant)
        self.tenant_key = "clb2b_tenant_security"
        self.admin_key = "admin-security-key"
        self.db.add(
            ApiKey(
                tenant_id=self.tenant.id,
                key_hash=hash_api_key(self.tenant_key),
                label="tenant-key",
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_disabled_tenant_cannot_access_tenant_endpoints(self) -> None:
        self.tenant.is_active = False
        self.db.add(self.tenant)
        self.db.commit()

        request = make_request({"Authorization": f"Bearer {self.tenant_key}"})
        with self.assertRaises(HTTPException) as exc:
            require_tenant(request=request, db=self.db)
        self.assertEqual(exc.exception.status_code, 403)

    def test_revoked_key_fails_immediately(self) -> None:
        api_key = self.db.query(ApiKey).filter(ApiKey.tenant_id == self.tenant.id).first()
        api_key.revoked_at = datetime.now(timezone.utc)
        self.db.add(api_key)
        self.db.commit()

        request = make_request({"Authorization": f"Bearer {self.tenant_key}"})
        with self.assertRaises(HTTPException) as exc:
            require_tenant(request=request, db=self.db)
        self.assertEqual(exc.exception.status_code, 401)

    def test_admin_key_cannot_access_tenant_routes(self) -> None:
        request = make_request({"Authorization": f"Bearer {self.admin_key}"})
        with self.assertRaises(HTTPException) as exc:
            require_tenant(request=request, db=self.db)
        self.assertEqual(exc.exception.status_code, 401)

    def test_tenant_key_cannot_access_admin_routes(self) -> None:
        with patch("core.admin_auth.settings", new=types.SimpleNamespace(admin_api_key=self.admin_key)):
            with self.assertRaises(HTTPException) as exc:
                require_admin(self.tenant_key)
        self.assertEqual(exc.exception.status_code, 401)

    def test_admin_key_required_for_all_admin_routes(self) -> None:
        from core.admin_auth import require_admin as dep

        for route in admin_router.routes:
            if not isinstance(route, APIRoute):
                continue
            dependencies = [d.dependency for d in route.dependencies]
            self.assertIn(dep, dependencies, msg=f"missing require_admin for route {route.path}")

    def test_admin_key_allows_admin_dependency(self) -> None:
        with patch("core.admin_auth.settings", new=types.SimpleNamespace(admin_api_key=self.admin_key)):
            actor = require_admin(self.admin_key)
        self.assertEqual(actor, "admin")


if __name__ == "__main__":
    unittest.main()
