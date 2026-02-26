import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.routing import APIRoute
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.admin_auth import require_admin
from core.db import Base
from core.external_anchor import compute_anchor_digest, export_anchor_snapshot, verify_anchor_snapshot
from models.tenant import Tenant
from routers.admin import create_anchor_snapshot, router as admin_router
from routers.consents import upsert_consent
from schemas.consent import ConsentUpsert


class ExternalAnchorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant_a = Tenant(id=uuid.uuid4(), name="tenant-ext-anchor-a")
        self.tenant_b = Tenant(id=uuid.uuid4(), name="tenant-ext-anchor-b")
        self.db.add(self.tenant_a)
        self.db.add(self.tenant_b)
        self.db.commit()

        upsert_consent(
            payload=ConsentUpsert(subject_id="user-a", purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="user-b", purpose="sms", status="REVOKED"),
            db=self.db,
            tenant=self.tenant_b,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_snapshot_digest_verifies(self) -> None:
        snapshot = export_anchor_snapshot(self.db)
        result = verify_anchor_snapshot(snapshot)
        self.assertTrue(result["verified"])

    def test_tampered_anchor_fails(self) -> None:
        snapshot = export_anchor_snapshot(self.db)
        snapshot["anchors"][0] = "0" * 64
        result = verify_anchor_snapshot(snapshot)
        self.assertFalse(result["verified"])
        self.assertIn("digest mismatch", result["failure_reason"])

    def test_reordered_anchors_fail(self) -> None:
        snapshot = export_anchor_snapshot(self.db)
        snapshot["anchors"] = list(reversed(snapshot["anchors"]))
        result = verify_anchor_snapshot(snapshot)
        self.assertFalse(result["verified"])
        self.assertIn("sorted", result["failure_reason"])

    def test_offline_verification_without_db(self) -> None:
        anchors = sorted(["a" * 64, "b" * 64])
        snapshot = {
            "version": 1,
            "generated_at": "2026-02-25T00:00:00Z",
            "algorithm": "SHA256",
            "anchor_count": len(anchors),
            "digest": compute_anchor_digest(anchors),
            "anchors": anchors,
        }
        result = verify_anchor_snapshot(snapshot)
        self.assertTrue(result["verified"])

    def test_admin_only_access_enforced(self) -> None:
        for route in admin_router.routes:
            if not isinstance(route, APIRoute):
                continue
            if route.path != "/admin/anchors/snapshot":
                continue
            dependencies = [d.dependency for d in route.dependencies]
            self.assertIn(require_admin, dependencies)
            return
        self.fail("snapshot route not found")

    def test_commit_hook_failure_does_not_break_snapshot(self) -> None:
        with patch("routers.admin.settings", new=type("S", (), {"external_anchor_commit_path": "C:/invalid/path"})()):
            with patch("routers.admin.append_anchor_commit", side_effect=OSError("disk error")):
                snapshot = create_anchor_snapshot(response=type("R", (), {"headers": {}})(), db=self.db)
        self.assertIn("digest", snapshot)
        self.assertIn("anchors", snapshot)


if __name__ == "__main__":
    unittest.main()
