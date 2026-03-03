from __future__ import annotations

from core.canonical import canonical_json_bytes
from core.ed25519 import sign_hex, verify_hex


def canonical_delegation_message(parent_fp: str, child_fp: str, delegation_type: str) -> bytes:
    payload = {
        "parent_fingerprint": str(parent_fp),
        "child_fingerprint": str(child_fp),
        "delegation_type": str(delegation_type),
    }
    return canonical_json_bytes(payload)


def sign_delegation(private_key_hex: str, message_bytes: bytes) -> str:
    return sign_hex(private_key_hex, message_bytes)


def verify_delegation(public_key_hex: str, message_bytes: bytes, signature_hex: str) -> bool:
    return verify_hex(public_key_hex, message_bytes, signature_hex)

