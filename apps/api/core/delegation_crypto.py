from __future__ import annotations

import hmac

from core.lineage import canonical_json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical_delegation_message(parent_fp: str, child_fp: str, delegation_type: str) -> bytes:
    payload = {
        "parent_fingerprint": str(parent_fp),
        "child_fingerprint": str(child_fp),
        "delegation_type": str(delegation_type),
    }
    return canonical_json(payload).encode("utf-8")


def sign_delegation(private_key_hex: str, message_bytes: bytes) -> str:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    return private_key.sign(message_bytes).hex()


def verify_delegation(public_key_hex: str, message_bytes: bytes, signature_hex: str) -> bool:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        signature = bytes.fromhex(signature_hex)
        public_key.verify(signature, message_bytes)
        return hmac.compare_digest(signature.hex(), signature_hex.lower())
    except Exception:
        return False

