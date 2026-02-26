from __future__ import annotations

import hashlib


def verify_public_key_format(public_key_hex: str) -> None:
    if not isinstance(public_key_hex, str):
        raise ValueError("public_key must be a hex string")
    if len(public_key_hex) != 64:
        raise ValueError("public_key must be 32 bytes encoded as 64 hex characters")
    try:
        raw = bytes.fromhex(public_key_hex)
    except ValueError as exc:
        raise ValueError("public_key must be valid lowercase/uppercase hex") from exc
    if len(raw) != 32:
        raise ValueError("public_key must decode to exactly 32 bytes")


def compute_identity_fingerprint(public_key_hex: str) -> str:
    verify_public_key_format(public_key_hex)
    return hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()

