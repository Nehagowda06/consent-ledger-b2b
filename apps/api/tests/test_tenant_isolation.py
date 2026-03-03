import unittest
import uuid

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from models.tenant import Tenant
from routers.consents import create_consent, get_consent, list_consents, revoke_consent
from schemas.consent import ConsentCreate


class TenantIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tenant_a = Tenant(id=uuid.uuid4(), name="tenant-a")
        self.tenant_b = Tenant(id=uuid.uuid4(), name="tenant-b")
        self.db.add(self.tenant_a)
        self.db.add(self.tenant_b)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_create_under_tenant_a_not_visible_under_tenant_b(self) -> None:
        created = create_consent(
            payload=ConsentCreate(subject_id="user-1", purpose="marketing_emails"),
            db=self.db,
            tenant=self.tenant_a,
        )

        list_a = list_consents(db=self.db, tenant=self.tenant_a)
        list_b = list_consents(db=self.db, tenant=self.tenant_b)

        self.assertEqual(created.tenant_id, self.tenant_a.id)
        self.assertEqual(len(list_a["data"]), 1)
        self.assertEqual(len(list_b["data"]), 0)

    def test_revoke_under_tenant_b_cannot_affect_tenant_a(self) -> None:
        created = create_consent(
            payload=ConsentCreate(subject_id="user-2", purpose="product_updates"),
            db=self.db,
            tenant=self.tenant_a,
        )

        with self.assertRaises(HTTPException) as exc:
            revoke_consent(consent_id=created.id, db=self.db, tenant=self.tenant_b)
        self.assertEqual(exc.exception.status_code, 404)

        fetched = get_consent(consent_id=created.id, db=self.db, tenant=self.tenant_a)
        self.assertEqual(fetched.status.value, "ACTIVE")


if __name__ == "__main__":
    unittest.main()
