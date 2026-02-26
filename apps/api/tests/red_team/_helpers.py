from __future__ import annotations

import uuid

from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from models.api_key import ApiKey
from models.tenant import Tenant


def make_request(path: str = "/", method: str = "GET", headers: dict[str, str] | None = None) -> Request:
    headers = headers or {}
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
        "client": ("127.0.0.1", 18000),
    }
    return Request(scope)


def make_memory_session() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    return session, engine


def seed_tenant(session: Session, *, name: str) -> Tenant:
    tenant = Tenant(id=uuid.uuid5(uuid.NAMESPACE_DNS, name), name=name)
    session.add(tenant)
    session.commit()
    return tenant


def seed_api_key(session: Session, tenant: Tenant, *, key_hash: str, label: str = "k") -> ApiKey:
    api_key = ApiKey(tenant_id=tenant.id, key_hash=key_hash, label=label)
    session.add(api_key)
    session.commit()
    return api_key
