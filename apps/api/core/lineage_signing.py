from __future__ import annotations

import hmac

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def sign_bytes(private_key_hex: str, message: bytes) -> str:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    return private_key.sign(message).hex()


def verify_bytes(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        signature = bytes.fromhex(signature_hex)
        public_key.verify(signature, message)
        return hmac.compare_digest(signature.hex(), signature_hex.lower())
    except Exception:
        return False

