from __future__ import annotations

from core.canonical import canonical_json_bytes
from core.ed25519 import sign_hex, verify_hex


def canonical_assertion_payload(payload: dict) -> bytes:
    return canonical_json_bytes(payload)


def sign_assertion(private_key_hex: str, message_bytes: bytes) -> str:
    return sign_hex(private_key_hex, message_bytes)


def verify_assertion_signature(public_key_hex: str, message_bytes: bytes, signature_hex: str) -> bool:
    return verify_hex(public_key_hex, message_bytes, signature_hex)

