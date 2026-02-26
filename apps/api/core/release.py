from __future__ import annotations

from dataclasses import asdict, dataclass

from core.contracts import SUPPORTED_API_VERSIONS


@dataclass(frozen=True)
class ReleaseArtifact:
    code_sha: str
    expected_alembic_head: str
    supported_api_versions: tuple[str, ...]
    enabled_feature_flags: tuple[str, ...]
    signing_mode: str
    signing_required: bool


def build_release_artifact(settings) -> ReleaseArtifact:
    supported_versions = getattr(settings, "release_supported_api_versions", ["v1"])
    feature_flags = getattr(settings, "release_feature_flags", [])
    signing_mode = getattr(settings, "signing_mode", "required" if getattr(settings, "signing_required", False) else "optional")
    return ReleaseArtifact(
        code_sha=settings.version_hash,
        expected_alembic_head=getattr(settings, "expected_alembic_head", ""),
        supported_api_versions=tuple(sorted(supported_versions)),
        enabled_feature_flags=tuple(sorted(feature_flags)),
        signing_mode=signing_mode,
        signing_required=bool(getattr(settings, "signing_required", False)),
    )


def release_artifact_dict(settings) -> dict:
    return asdict(build_release_artifact(settings))


def validate_release_startup(settings, current_alembic_heads: str) -> None:
    release_supported_api_versions = getattr(settings, "release_supported_api_versions", ["v1"])
    unsupported_versions = set(release_supported_api_versions) - set(SUPPORTED_API_VERSIONS)
    if unsupported_versions:
        raise RuntimeError(f"RELEASE_SUPPORTED_API_VERSIONS contains unsupported values: {sorted(unsupported_versions)}")

    expected_head = getattr(settings, "expected_alembic_head", "")
    if expected_head and current_alembic_heads != expected_head:
        raise RuntimeError(
            f"Alembic head mismatch. expected={expected_head} actual={current_alembic_heads}"
        )

    if settings.env == "prod":
        if getattr(settings, "log_level", "INFO") == "DEBUG":
            raise RuntimeError("LOG_LEVEL=DEBUG is not allowed in prod")
        if getattr(settings, "auto_create_schema", False):
            raise RuntimeError("AUTO_CREATE_SCHEMA must be false in prod")
        if not getattr(settings, "database_url", None):
            raise RuntimeError("DATABASE_URL is required in prod")
        if not getattr(settings, "api_key_hash_secret", None):
            raise RuntimeError("API_KEY_HASH_SECRET is required in prod")
        if not getattr(settings, "webhook_signing_secret", None):
            raise RuntimeError("WEBHOOK_SIGNING_SECRET is required in prod")
        if not getattr(settings, "admin_api_key", None):
            raise RuntimeError("ADMIN_API_KEY is required in prod")
        if not getattr(settings, "cors_allowed_origins", []):
            raise RuntimeError("CORS_ALLOWED_ORIGINS must be explicitly set in prod")
        if getattr(settings, "api_key_rate_limit_per_min", 0) <= 0:
            raise RuntimeError("API_KEY_RATE_LIMIT_PER_MIN must be > 0 in prod")

    signing_required = bool(getattr(settings, "signing_required", False))
    signing_enabled = bool(getattr(settings, "signing_enabled", False))
    signing_mode = getattr(settings, "signing_mode", "required" if signing_required else "optional")

    if signing_mode not in {"required", "optional", "disabled"}:
        raise RuntimeError("SIGNING_MODE must be one of: required, optional, disabled")
    if signing_required and signing_mode != "required":
        raise RuntimeError("SIGNING_REQUIRED=true requires SIGNING_MODE=required")
    if signing_mode == "required" and not signing_enabled:
        raise RuntimeError("SIGNING_MODE=required but signing material is unavailable")
    if signing_mode == "disabled" and signing_enabled:
        raise RuntimeError("SIGNING_MODE=disabled is incompatible with configured signing key material")
    if settings.env == "prod" and not signing_enabled and signing_mode != "disabled":
        raise RuntimeError("Unsigned mode in prod requires explicit SIGNING_MODE=disabled")
