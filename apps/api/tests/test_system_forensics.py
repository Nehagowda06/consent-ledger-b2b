import types
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from core.system_forensics import verify_system_ledger
from routers.admin import (
    create_api_key,
    create_tenant,
    disable_tenant,
    export_system_events,
    verify_system_events,
)
from schemas.admin import ApiKeyCreateIn, TenantCreateIn


class SystemForensicsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        tenant = create_tenant(payload=TenantCreateIn(name="tenant-forensics"), db=self.db)
        key = create_api_key(tenant_id=tenant.id, payload=ApiKeyCreateIn(label="forensics"), db=self.db)
        disable_tenant(tenant_id=tenant.id, db=self.db)
        self.assertIsNotNone(key.id)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_valid_chain(self) -> None:
        result = verify_system_events(db=self.db)
        self.assertTrue(result["verified"])
        self.assertGreater(result["event_count"], 0)
        self.assertIsNone(result["failure_index"])
        self.assertIsNone(result["failure_reason"])

    def test_tampered_chain(self) -> None:
        response = types.SimpleNamespace(headers={})
        exported = export_system_events(response=response, db=self.db)
        exported["events"][0]["event_hash"] = "0" * 64
        result = verify_system_ledger(exported["events"])
        self.assertFalse(result["verified"])
        self.assertIsNotNone(result["failure_index"])
        self.assertIsNotNone(result["failure_reason"])

    def test_reordered_events_fail(self) -> None:
        response = types.SimpleNamespace(headers={})
        exported = export_system_events(response=response, db=self.db)
        reordered = list(reversed(exported["events"]))
        result = verify_system_ledger(reordered)
        self.assertFalse(result["verified"])
        self.assertIsNotNone(result["failure_index"])


if __name__ == "__main__":
    unittest.main()
