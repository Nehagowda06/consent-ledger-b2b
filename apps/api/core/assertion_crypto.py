from __future__ import annotations

import hmac
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical_assertion_payload(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_assertion(private_key_hex: str, message_bytes: bytes) -> str:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    signature = private_key.sign(message_bytes)
    return signature.hex()


def verify_assertion_signature(public_key_hex: str, message_bytes: bytes, signature_hex: str) -> bool:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        signature = bytes.fromhex(signature_hex)
        public_key.verify(signature, message_bytes)
        # Constant-time length check on normalized signature representation.
        return hmac.compare_digest(signature.hex(), signature_hex.lower())
    except Exception:
        return False

