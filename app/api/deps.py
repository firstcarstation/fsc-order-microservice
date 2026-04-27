from typing import Annotated, Optional

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.config import settings
from app.core.exceptions import AppException

bearer_scheme = HTTPBearer(auto_error=False)


class AuthContext(BaseModel):
    user_id: str
    role_id: Optional[str] = None
    role_type: str = ""
    hub_id: Optional[str] = None


def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer_scheme)],
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppException("Not authenticated", status_code=401)
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        raise AppException("Could not validate credentials", status_code=401)
    if payload.get("typ") != "access":
        raise AppException("Invalid access token", status_code=401)
    sub = payload.get("sub")
    if not sub:
        raise AppException("Not authenticated", status_code=401)
    rt = payload.get("role_type")
    return AuthContext(
        user_id=str(sub),
        role_id=str(payload["role_id"]) if payload.get("role_id") else None,
        role_type=str(rt) if rt else "",
        hub_id=str(payload["hub_id"]) if payload.get("hub_id") else None,
    )


def require_admin(ctx: Annotated[AuthContext, Depends(get_current_user)]) -> AuthContext:
    if ctx.role_type not in ("admin", "hub_manager"):
        raise AppException("Admin only", status_code=403)
    return ctx
