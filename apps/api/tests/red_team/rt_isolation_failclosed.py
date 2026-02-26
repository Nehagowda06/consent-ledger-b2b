from __future__ import annotations

import types
import unittest
import uuid
from unittest.mock import patch

from fastapi import HTTPException

from core.api_keys import hash_api_key
from core.auth import require_tenant
from models.tenant import Tenant, TenantLifecycleState
from tests.red_team._helpers import make_memory_session, make_request, seed_api_key


class _BoomLimiter:
    def allow(self, _identity: str) -> bool:
        raise RuntimeError("limiter unavailable")


class RedTeamIsolationFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self.engine = make_memory_session()
        self.tenant = Tenant(
            id=uuid.UUID("00000000-0000-0000-0000-00000000bb01"),
            name="rt-iso-tenant",
            is_active=True,
            lifecycle_state=TenantLifecycleState.ACTIVE,
        )
        self.db.add(self.tenant)
        self.db.commit()
        self.raw_key = "rt_key_primary"
        seed_api_key(self.db, self.tenant, key_hash=hash_api_key(self.raw_key), label="rt")

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_rate_limiter_failure_is_503_in_prod(self) -> None:
        req = make_request(headers={"Authorization": f"Bearer {self.raw_key}"})
        with patch("core.auth.settings", new=types.SimpleNamespace(env="prod")):
            with patch("core.auth.RATE_LIMITER", new=_BoomLimiter()):
                with self.assertRaises(HTTPException) as exc:
                    require_tenant(request=req, db=self.db)
        self.assertEqual(exc.exception.status_code, 503)

    def test_rate_limiter_failure_is_fail_open_in_dev(self) -> None:
        req = make_request(headers={"Authorization": f"Bearer {self.raw_key}"})
        with patch("core.auth.settings", new=types.SimpleNamespace(env="dev")):
            with patch("core.auth.RATE_LIMITER", new=_BoomLimiter()):
                tenant = require_tenant(request=req, db=self.db)
        self.assertEqual(str(tenant.id), str(self.tenant.id))

    def test_disabled_tenant_forbidden_even_with_valid_key(self) -> None:
        self.tenant.lifecycle_state = TenantLifecycleState.DISABLED
        self.tenant.is_active = False
        self.db.add(self.tenant)
        self.db.commit()
        req = make_request(headers={"Authorization": f"Bearer {self.raw_key}"})
        with self.assertRaises(HTTPException) as exc:
            require_tenant(request=req, db=self.db)
        self.assertEqual(exc.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
