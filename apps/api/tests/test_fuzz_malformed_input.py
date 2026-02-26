import random
import unittest
import uuid

from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from core.external_anchor import verify_anchor_snapshot
from core.lineage_verify import verify_consent_proof, verify_exported_lineage
from routers.anchors import verify_snapshot
from routers.lineage_verify import verify_lineage_export
from routers.proofs import verify_proof


def _random_blob(depth: int = 0):
    if depth > 4:
        return random.choice([None, 1, "x", True, []])
    t = random.choice(["dict", "list", "scalar"])
    if t == "dict":
        return {str(uuid.uuid4()): _random_blob(depth + 1) for _ in range(random.randint(0, 3))}
    if t == "list":
        return [_random_blob(depth + 1) for _ in range(random.randint(0, 3))]
    return random.choice([None, 1, "x", True])


def _request_with_body(body: bytes, path: str) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 14000),
    }
    request = Request(scope)

    async def _body():
        return body

    request.body = _body  # type: ignore[assignment]
    return request


class FuzzMalformedInputTests(unittest.TestCase):
    def test_random_blobs_do_not_crash_verifiers(self) -> None:
        for _ in range(100):
            blob = _random_blob()
            if not isinstance(blob, dict):
                blob = {"value": blob}
            self.assertIn("verified", verify_exported_lineage(blob))
            self.assertIn("verified", verify_consent_proof(blob))
            self.assertIn("verified", verify_anchor_snapshot(blob))

    def test_deep_nesting_and_unicode_are_handled(self) -> None:
        payload = {"ñ": {"深": {"emoji": "😀", "nested": [{"x": "y"}] * 100}}}
        self.assertFalse(verify_exported_lineage(payload)["verified"])
        self.assertFalse(verify_consent_proof(payload)["verified"])
        self.assertFalse(verify_anchor_snapshot(payload)["verified"])

    def test_large_validish_payload_is_validation_safe(self) -> None:
        huge_anchors = ["a" * 64 for _ in range(2000)]
        snapshot = {
            "version": 1,
            "generated_at": "2026-02-25T00:00:00Z",
            "algorithm": "SHA256",
            "anchor_count": len(huge_anchors),
            "digest": "0" * 64,
            "anchors": huge_anchors,
        }
        result = verify_anchor_snapshot(snapshot)
        self.assertFalse(result["verified"])

    def test_invalid_utf8_on_public_endpoints_returns_validation(self) -> None:
        bad_bytes = b"\xff\xfe\xfd"
        req_lineage = _request_with_body(bad_bytes, "/lineage/verify")
        req_proofs = _request_with_body(bad_bytes, "/proofs/verify")
        req_anchors = _request_with_body(bad_bytes, "/anchors/verify")

        async def _run():
            with self.assertRaises(RequestValidationError):
                await verify_lineage_export(request=req_lineage, export={})
            with self.assertRaises(RequestValidationError):
                await verify_proof(request=req_proofs, proof={})
            with self.assertRaises(RequestValidationError):
                await verify_snapshot(request=req_anchors, snapshot={})

        import asyncio

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
