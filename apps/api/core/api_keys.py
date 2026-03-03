import hashlib
import hmac
import secrets

from core.config import get_settings

API_KEY_PREFIX = "clb2b"
API_KEY_HEADER = "Authorization: Bearer <api_key>"


def generate_api_key() -> str:
    token = secrets.token_urlsafe(32)
    return f"{API_KEY_PREFIX}_{token}"


def _get_hash_secret() -> str:
    return get_settings().api_key_hash_secret


def hash_api_key(raw_key: str) -> str:
    secret = _get_hash_secret().encode("utf-8")
    return hmac.new(secret, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()
