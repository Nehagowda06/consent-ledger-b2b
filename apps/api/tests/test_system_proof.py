import unittest

from fastapi.routing import APIRoute
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from core.db import Base
from core.system_proof import export_system_proof, verify_system_proof
from routers.admin import create_api_key, create_tenant, disable_tenant
from schemas.admin import ApiKeyCreateIn, TenantCreateIn


class SystemProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        tenant = create_tenant(payload=TenantCreateIn(name="tenant-system-proof"), db=self.db)
        create_api_key(tenant_id=tenant.id, payload=ApiKeyCreateIn(label="proof-key"), db=self.db)
        disable_tenant(tenant_id=tenant.id, db=self.db)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_proof_verification_success(self) -> None:
        proof = export_system_proof(self.db)
        result = verify_system_proof(proof)
        self.assertTrue(result["verified"])
        self.assertIsNone(result["failure_reason"])

    def test_tampering_detection(self) -> None:
        proof = export_system_proof(self.db)
        proof["events"][0]["event_hash"] = "0" * 64
        result = verify_system_proof(proof)
        self.assertFalse(result["verified"])
        self.assertIsNotNone(result["failure_reason"])

    def test_offline_use(self) -> None:
        proof = export_system_proof(self.db)
        self.db.close()
        self.engine.dispose()
        result = verify_system_proof(proof)
        self.assertTrue(result["verified"])
        self.assertIsNone(result["failure_reason"])

    def test_public_verify_route_exists_without_auth_dependency(self) -> None:
        for route in main.app.routes:
            if not isinstance(route, APIRoute):
                continue
            if route.path == "/system/verify" and "POST" in route.methods:
                self.assertEqual(len(route.dependencies), 0)
                return
        self.fail("POST /system/verify route not found")


if __name__ == "__main__":
    unittest.main()
