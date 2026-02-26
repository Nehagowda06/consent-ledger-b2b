import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from core.external_anchor import export_anchor_snapshot, verify_anchor_snapshot
from models.tenant import Tenant
from routers.admin import create_anchor_snapshot
from routers.consents import upsert_consent
from schemas.consent import ConsentUpsert


class ExternalAnchorAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-ext-adv")
        self.db.add(self.tenant)
        self.db.commit()
        upsert_consent(
            payload=ConsentUpsert(subject_id="ea", purpose="mail", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        tenant2 = Tenant(id=uuid.uuid4(), name="tenant-ext-adv-2")
        self.db.add(tenant2)
        self.db.commit()
        upsert_consent(
            payload=ConsentUpsert(subject_id="ea2", purpose="mail2", status="ACTIVE"),
            db=self.db,
            tenant=tenant2,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_snapshot_missing_or_extra_anchors_detected(self) -> None:
        snapshot = export_anchor_snapshot(self.db)
        missing = dict(snapshot)
        missing["anchors"] = []
        self.assertFalse(verify_anchor_snapshot(missing)["verified"])

        extra = dict(snapshot)
        extra["anchors"] = snapshot["anchors"] + ["f" * 64]
        self.assertFalse(verify_anchor_snapshot(extra)["verified"])

    def test_reordered_and_metadata_mismatch_detected(self) -> None:
        snapshot = export_anchor_snapshot(self.db)
        bad = dict(snapshot)
        bad["anchors"] = list(reversed(snapshot["anchors"]))
        self.assertFalse(verify_anchor_snapshot(bad)["verified"])

        bad_alg = dict(snapshot)
        bad_alg["algorithm"] = "SHA1"
        self.assertFalse(verify_anchor_snapshot(bad_alg)["verified"])

    def test_digest_collision_attempt_with_modified_payload_fails(self) -> None:
        snapshot = export_anchor_snapshot(self.db)
        forged = dict(snapshot)
        forged["anchors"] = [a[:-1] + ("0" if a[-1] != "0" else "1") for a in snapshot["anchors"]]
        forged["digest"] = snapshot["digest"]
        result = verify_anchor_snapshot(forged)
        self.assertFalse(result["verified"])
        self.assertIn("digest mismatch", result["failure_reason"])

    def test_commit_file_write_failures_are_non_fatal(self) -> None:
        fake_response = type("R", (), {"headers": {}})()
        with patch("routers.admin.settings", new=type("Cfg", (), {"external_anchor_commit_path": "/no/access"})()):
            with patch("routers.admin.append_anchor_commit", side_effect=PermissionError("denied")):
                snapshot = create_anchor_snapshot(response=fake_response, db=self.db)
        self.assertIn("digest", snapshot)
        self.assertEqual(fake_response.headers.get("Cache-Control"), "no-store")


if __name__ == "__main__":
    unittest.main()
