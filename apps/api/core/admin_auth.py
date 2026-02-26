import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from core.config import get_settings


admin_key_header = APIKeyHeader(name="X-Admin-Api-Key", auto_error=False)
settings = get_settings()


def require_admin(admin_key: str | None = Security(admin_key_header)) -> str:
    if not admin_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials")
    if not hmac.compare_digest(admin_key, settings.admin_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin credentials")
    return "admin"
