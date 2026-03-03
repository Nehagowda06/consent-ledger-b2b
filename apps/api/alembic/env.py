import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, pool
from alembic import context

# --- path setup (kept, but deduplicated) ---
BASE_DIR = Path(__file__).resolve().parents[1]  # apps/api
sys.path.insert(0, str(BASE_DIR))

from core.db import Base
from models import (  # noqa: F401
    ApiKey,
    AuditEvent,
    Consent,
    ConsentLineageEvent,
    IdentityDelegation,
    IdentityKey,
    IdempotencyKey,
    SignedAssertion,
    SystemEvent,
    Tenant,
    WebhookDelivery,
    WebhookEndpoint,
)

# Alembic Config object
config = context.config

# ⛔ REMOVED: fileConfig(config.config_file_name)
# This was the main reason the process stayed alive

target_metadata = Base.metadata


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL must be set for Alembic")
    return url


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""
    engine = create_engine(get_database_url(), poolclass=pool.NullPool)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()