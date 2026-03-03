import argparse
import uuid

from sqlalchemy import select

from core.api_keys import API_KEY_HEADER, generate_api_key, hash_api_key
from core.db import SessionLocal
from models.api_key import ApiKey
from models.tenant import Tenant


DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create (or fetch) a tenant and generate a new API key."
    )
    parser.add_argument(
        "--tenant-name",
        default="local-dev",
        help="Tenant name to create or reuse (default: local-dev).",
    )
    parser.add_argument(
        "--label",
        default="local-dev-key",
        help="API key label (default: local-dev-key).",
    )
    parser.add_argument(
        "--use-default-tenant-id",
        action="store_true",
        help="Force the default demo tenant UUID when creating the tenant.",
    )
    return parser.parse_args()


def get_or_create_tenant(db, tenant_name: str, use_default_tenant_id: bool) -> Tenant:
    existing = db.scalar(select(Tenant).where(Tenant.name == tenant_name))
    if existing:
        return existing

    tenant = Tenant(name=tenant_name)
    if use_default_tenant_id and tenant_name == "local-dev":
        tenant.id = DEFAULT_TENANT_ID

    db.add(tenant)
    db.flush()
    return tenant


def main() -> None:
    args = parse_args()
    db = SessionLocal()
    try:
        tenant = get_or_create_tenant(db, args.tenant_name, args.use_default_tenant_id)

        plaintext_key = generate_api_key()
        key_hash = hash_api_key(plaintext_key)

        api_key = ApiKey(
            tenant_id=tenant.id,
            key_hash=key_hash,
            label=args.label,
        )
        db.add(api_key)
        db.commit()

        print("Tenant ID:", tenant.id)
        print("Tenant Name:", tenant.name)
        print("API Key Label:", api_key.label)
        print("API Key (shown once):", plaintext_key)
        print("Future header format:", API_KEY_HEADER)
    finally:
        db.close()


if __name__ == "__main__":
    main()
