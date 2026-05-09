"""Common FastAPI dependencies."""

from __future__ import annotations

from typing import Iterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import Permission, Role, has_permission
from app.core.security import decode_access_token
from app.db.session import get_sessionmaker


def get_db() -> Iterator[Session]:
    SessionLocal = get_sessionmaker()
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_tenant_id(x_tenant_id: str = Header(default="demo")) -> str:
    return x_tenant_id


def get_role(authorization: str | None = Header(default=None)) -> Role:
    """Resolve role from JWT or fall back to OWNER in demo mode.

    Production deployments should remove the demo fallback and require auth.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return Role.OWNER  # demo mode
    try:
        payload = decode_access_token(authorization.split(" ", 1)[1])
        return Role(payload.get("role", "viewer"))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


def require_perm(perm: Permission):
    def dep(role: Role = Depends(get_role)) -> Role:
        if not has_permission(role, perm):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"missing {perm}")
        return role

    return dep
