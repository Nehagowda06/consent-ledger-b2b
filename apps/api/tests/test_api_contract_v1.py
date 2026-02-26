import hashlib
import json
import unittest
import uuid

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.contracts import (
    API_VERSION_HEADER,
    API_VERSION_V1,
    DEFAULT_API_VERSION,
    ErrorCode,
    frozen_contract,
    paginated,
    resolve_api_version,
    success,
    error_body,
)
from core.db import Base
from core.idempotency import build_request_hash, check_idempotency, store_idempotency_result


class ApiContractV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant_id = uuid.uuid4()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_v1_response_envelopes_match_frozen_schema_exactly(self) -> None:
        self.assertEqual(success({"ok": True}), {"data": {"ok": True}})
        self.assertEqual(
            error_body(ErrorCode.NOT_FOUND, "Not found", "req-1"),
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Not found",
                    "request_id": "req-1",
                }
            },
        )
        self.assertEqual(
            paginated([{"id": 1}], limit=50, offset=0, count=1),
            {
                "data": [{"id": 1}],
                "meta": {
                    "limit": 50,
                    "offset": 0,
                    "count": 1,
                },
            },
        )

    def test_contract_snapshot_v1_is_frozen(self) -> None:
        expected = {
            "version": "v1",
            "envelopes": {
                "success": {
                    "type": "object",
                    "required": ["data"],
                    "properties": {"data": {"type": "any"}},
                    "additionalProperties": False,
                },
                "error": {
                    "type": "object",
                    "required": ["error"],
                    "properties": {
                        "error": {
                            "type": "object",
                            "required": ["code", "message", "request_id"],
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "request_id": {"type": "string"},
                            },
                            "additionalProperties": False,
                        }
                    },
                    "additionalProperties": False,
                },
                "pagination": {
                    "type": "object",
                    "required": ["data", "meta"],
                    "properties": {
                        "data": {"type": "array"},
                        "meta": {
                            "type": "object",
                            "required": ["limit", "offset", "count"],
                            "properties": {
                                "limit": {"type": "integer"},
                                "offset": {"type": "integer"},
                                "count": {"type": "integer"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "headers": {
                "auth": ["Authorization: Bearer <api_key>", "X-Api-Key (optional fallback)"],
                "admin_auth": ["X-Admin-Api-Key: <admin_api_key>"],
                "version": ["X-API-Version: v1"],
                "idempotency": ["Idempotency-Key: <opaque-string>"],
                "webhook_signing": [
                    "X-Webhook-Timestamp: <unix-seconds>",
                    "X-Webhook-Signature: <hex-hmac-sha256>",
                ],
            },
            "idempotency": {
                "request_hash": "SHA256(UPPER(method) + '|' + path + '|' + canonical_json(body))",
                "replay_status": "original_status_code",
                "mismatch_status": 409,
            },
        }
        self.assertEqual(frozen_contract(API_VERSION_V1), expected)

    def test_version_selection_is_deterministic(self) -> None:
        self.assertEqual(DEFAULT_API_VERSION, API_VERSION_V1)
        self.assertEqual(resolve_api_version(None), "v1")
        self.assertEqual(resolve_api_version("V1"), "v1")
        with self.assertRaisesRegex(ValueError, "Unsupported API version: v2"):
            resolve_api_version("v2")
        with self.assertRaisesRegex(ValueError, "API version header is empty"):
            resolve_api_version("   ")

    def test_idempotency_semantics_unchanged(self) -> None:
        body = {"b": "x", "a": 1}
        request_hash = build_request_hash("PUT", "/consents", body)
        self.assertEqual(request_hash, "cc65f4cdef6ecb44da2fffee412c13b140f83bcc9a7bb7799d4fb1681675ed4d")

        store_idempotency_result(
            self.db,
            tenant_id=self.tenant_id,
            key="idem-1",
            request_hash=request_hash,
            response_json={"ok": True},
            status_code=200,
        )
        self.db.commit()

        replay = check_idempotency(self.db, self.tenant_id, "idem-1", request_hash)
        self.assertIsNotNone(replay)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.response_json, {"ok": True})

        different_hash = hashlib.sha256(json.dumps({"changed": True}).encode("utf-8")).hexdigest()
        with self.assertRaises(HTTPException) as exc:
            check_idempotency(self.db, self.tenant_id, "idem-1", different_hash)
        self.assertEqual(exc.exception.status_code, 409)

    def test_contract_header_name_is_frozen(self) -> None:
        self.assertEqual(API_VERSION_HEADER, "X-API-Version")


if __name__ == "__main__":
    unittest.main()
