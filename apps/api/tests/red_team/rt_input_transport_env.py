from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from core.config import Settings
from routers.anchors import verify_snapshot
from routers.lineage_verify import verify_lineage_export
from routers.proofs import verify_proof
from routers.system_verify import verify_system_proof_endpoint
from tests.red_team._helpers import make_request


class RedTeamInputTransportEnvTests(unittest.TestCase):
    def test_verify_endpoints_reject_oversized_payload(self) -> None:
        big = b"{" + b"\"x\":" + b"\"" + (b"a" * 300_000) + b"\"}"
        req_lineage = make_request(path="/lineage/verify")
        req_proof = make_request(path="/proofs/verify")
        req_anchor = make_request(path="/anchors/verify")
        req_system = make_request(path="/system/verify")

        async def _body() -> bytes:
            return big

        req_lineage.body = _body  # type: ignore[assignment]
        req_proof.body = _body  # type: ignore[assignment]
        req_anchor.body = _body  # type: ignore[assignment]
        req_system.body = _body  # type: ignore[assignment]

        async def _run() -> None:
            with self.assertRaises(HTTPException) as e1:
                await verify_lineage_export(request=req_lineage, export={})
            with self.assertRaises(HTTPException) as e2:
                await verify_proof(request=req_proof, proof={})
            with self.assertRaises(HTTPException) as e3:
                await verify_snapshot(request=req_anchor, snapshot={})
            with self.assertRaises(HTTPException) as e4:
                await verify_system_proof_endpoint(request=req_system, proof={})
            self.assertEqual(e1.exception.status_code, 413)
            self.assertEqual(e2.exception.status_code, 413)
            self.assertEqual(e3.exception.status_code, 413)
            self.assertEqual(e4.exception.status_code, 413)

        asyncio.run(_run())

    def test_prod_missing_secret_fails_closed(self) -> None:
        env = {
            "ENV": "prod",
            "DATABASE_URL": "postgresql://u:p@localhost:5433/db",
            "API_KEY_HASH_SECRET": "k",
            "WEBHOOK_SIGNING_SECRET": "",
            "ADMIN_API_KEY": "admin",
        }
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(RuntimeError):
                Settings()


if __name__ == "__main__":
    unittest.main()
