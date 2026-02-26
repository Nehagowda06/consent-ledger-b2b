from __future__ import annotations

from core.ed25519 import sign_hex, verify_hex


def sign_bytes(private_key_hex: str, message: bytes) -> str:
    return sign_hex(private_key_hex, message)


def verify_bytes(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
    return verify_hex(public_key_hex, message, signature_hex)

