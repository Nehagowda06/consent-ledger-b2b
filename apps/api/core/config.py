from functools import lru_cache
import logging
import os


logger = logging.getLogger(__name__)


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "consent-ledger-api")
        self.app_version = os.getenv("APP_VERSION", "0.0.1")
        self.version_hash = os.getenv("VERSION_HASH", os.getenv("GIT_SHA", "unknown"))
        self.env = os.getenv("ENV", "dev").lower()
        if self.env not in {"dev", "test", "staging", "prod"}:
            raise RuntimeError("ENV must be one of: dev, test, staging, prod")
        self.expected_alembic_head = os.getenv("EXPECTED_ALEMBIC_HEAD", "").strip()
        self.log_level = os.getenv("LOG_LEVEL", "DEBUG" if self.env in {"dev", "test"} else "INFO").upper().strip()
        self.release_supported_api_versions = self._parse_csv_values("RELEASE_SUPPORTED_API_VERSIONS", default="v1")
        self.release_feature_flags = self._parse_csv_values("RELEASE_FEATURE_FLAGS", default="")

        self.database_url = os.getenv("DATABASE_URL")
        if not self.database_url:
            if self.env == "prod":
                raise RuntimeError("DATABASE_URL is required in prod")
            self.database_url = "postgresql+psycopg://postgres@localhost:5433/consent_ledger"
            logger.warning("DATABASE_URL not set, using local dev default")

        self.api_key_hash_secret = os.getenv("API_KEY_HASH_SECRET")
        if not self.api_key_hash_secret:
            if self.env == "prod":
                raise RuntimeError("API_KEY_HASH_SECRET is required in prod")
            self.api_key_hash_secret = "dev-only-change-this-secret"
            logger.warning("API_KEY_HASH_SECRET not set, using insecure dev fallback")

        self.webhook_signing_secret = os.getenv("WEBHOOK_SIGNING_SECRET")
        if not self.webhook_signing_secret:
            if self.env == "prod":
                raise RuntimeError("WEBHOOK_SIGNING_SECRET is required in prod")
            self.webhook_signing_secret = "dev-webhook-signing-secret-change-me"
            logger.warning("WEBHOOK_SIGNING_SECRET not set, using insecure dev fallback")

        self.admin_api_key = os.getenv("ADMIN_API_KEY")
        if not self.admin_api_key:
            if self.env == "prod":
                raise RuntimeError("ADMIN_API_KEY is required in prod")
            self.admin_api_key = "dev-admin-key-change-me"
            logger.warning("ADMIN_API_KEY not set, using insecure dev fallback")

        self.webhook_worker_enabled = os.getenv("WEBHOOK_WORKER_ENABLED", "false").lower() == "true"
        self.webhook_max_attempts = int(os.getenv("WEBHOOK_MAX_ATTEMPTS", "8"))
        self.external_anchor_commit_path = os.getenv("EXTERNAL_ANCHOR_COMMIT_PATH", "").strip()
        self.api_key_rate_limit_per_min = int(os.getenv("API_KEY_RATE_LIMIT_PER_MIN", "300"))
        self.rate_limit_db_path = os.getenv("RATE_LIMIT_DB_PATH", "rate_limit.sqlite3")
        self.identity_signing_private_key = os.getenv("IDENTITY_SIGNING_PRIVATE_KEY", "").strip()
        self.signing_enabled = bool(self.identity_signing_private_key)
        self.signing_required = os.getenv("SIGNING_REQUIRED", "false").lower() == "true"
        self.signing_mode = os.getenv("SIGNING_MODE", "required" if self.signing_required else "optional").strip().lower()

        self.db_pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
        self.db_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
        self.db_pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))
        self.db_pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "1800"))

        self.auto_create_schema = os.getenv("AUTO_CREATE_SCHEMA", "false").lower() == "true"
        self.cors_allowed_origins = self._parse_cors_origins()
        self.validate()

    def _parse_csv_values(self, env_name: str, default: str) -> list[str]:
        raw = os.getenv(env_name, default)
        return [item.strip() for item in raw.split(",") if item.strip()]

    def _parse_cors_origins(self) -> list[str]:
        raw = os.getenv("CORS_ALLOWED_ORIGINS", "")
        if raw.strip():
            return [origin.strip() for origin in raw.split(",") if origin.strip()]
        if self.env == "dev":
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        return []

    def validate(self) -> None:
        if self.env == "prod":
            if not self.cors_allowed_origins:
                raise RuntimeError("CORS_ALLOWED_ORIGINS must be explicitly set in prod")
            if self.api_key_rate_limit_per_min <= 0:
                raise RuntimeError("API_KEY_RATE_LIMIT_PER_MIN must be > 0 in prod")
            if self.auto_create_schema:
                raise RuntimeError("AUTO_CREATE_SCHEMA must be false in prod")
            if self.log_level == "DEBUG":
                raise RuntimeError("LOG_LEVEL=DEBUG is not allowed in prod")
            if self.signing_required and not self.signing_enabled:
                raise RuntimeError("SIGNING_REQUIRED=true but IDENTITY_SIGNING_PRIVATE_KEY is missing")
            if not self.release_supported_api_versions:
                raise RuntimeError("RELEASE_SUPPORTED_API_VERSIONS must be explicitly set in prod")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
