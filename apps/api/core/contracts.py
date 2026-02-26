from enum import StrEnum
from typing import Any


API_VERSION_HEADER = "X-API-Version"
API_VERSION_V1 = "v1"
DEFAULT_API_VERSION = API_VERSION_V1
SUPPORTED_API_VERSIONS = frozenset({API_VERSION_V1})


class ErrorCode(StrEnum):
    AUTH_MISSING = "AUTH_MISSING"
    AUTH_INVALID = "AUTH_INVALID"
    AUTH_REVOKED = "AUTH_REVOKED"
    TENANT_DISABLED = "TENANT_DISABLED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    FORBIDDEN = "FORBIDDEN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


FROZEN_CONTRACTS: dict[str, dict[str, Any]] = {
    API_VERSION_V1: {
        "version": API_VERSION_V1,
        "envelopes": {
            "success": {
                "type": "object",
                "required": ["data"],
                "properties": {"data": {"type": "any"}},
                "additionalProperties": False,
            },
            "error": {
                "type": "object",
                "required": ["error"],
                "properties": {
                    "error": {
                        "type": "object",
                        "required": ["code", "message", "request_id"],
                        "properties": {
                            "code": {"type": "string"},
                            "message": {"type": "string"},
                            "request_id": {"type": "string"},
                        },
                        "additionalProperties": False,
                    }
                },
                "additionalProperties": False,
            },
            "pagination": {
                "type": "object",
                "required": ["data", "meta"],
                "properties": {
                    "data": {"type": "array"},
                    "meta": {
                        "type": "object",
                        "required": ["limit", "offset", "count"],
                        "properties": {
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                            "count": {"type": "integer"},
                        },
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            },
        },
        "headers": {
            "auth": ["Authorization: Bearer <api_key>", "X-Api-Key (optional fallback)"],
            "admin_auth": ["X-Admin-Api-Key: <admin_api_key>"],
            "version": [f"{API_VERSION_HEADER}: {API_VERSION_V1}"],
            "idempotency": ["Idempotency-Key: <opaque-string>"],
            "webhook_signing": ["X-Webhook-Timestamp: <unix-seconds>", "X-Webhook-Signature: <hex-hmac-sha256>"],
        },
        "idempotency": {
            "request_hash": "SHA256(UPPER(method) + '|' + path + '|' + canonical_json(body))",
            "replay_status": "original_status_code",
            "mismatch_status": 409,
        },
    }
}


def resolve_api_version(version_header: str | None) -> str:
    if version_header is None:
        return DEFAULT_API_VERSION
    normalized = version_header.strip().lower()
    if not normalized:
        raise ValueError("API version header is empty")
    if normalized not in SUPPORTED_API_VERSIONS:
        raise ValueError(f"Unsupported API version: {normalized}")
    return normalized


def frozen_contract(version: str) -> dict[str, Any]:
    if version not in FROZEN_CONTRACTS:
        raise ValueError(f"Unsupported API contract version: {version}")
    return FROZEN_CONTRACTS[version]


def success(data: Any) -> dict[str, Any]:
    return {"data": data}


def paginated(data: list[Any], *, limit: int, offset: int, count: int) -> dict[str, Any]:
    return {
        "data": data,
        "meta": {
            "limit": limit,
            "offset": offset,
            "count": count,
        },
    }


def error_body(code: ErrorCode, message: str, request_id: str) -> dict[str, Any]:
    return {
        "error": {
            "code": str(code),
            "message": message,
            "request_id": request_id,
        }
    }
