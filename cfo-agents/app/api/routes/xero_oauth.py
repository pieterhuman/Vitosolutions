"""Xero OAuth2 connect / callback. Tokens are encrypted at rest."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.security import encrypt_token
from app.db.models import XeroConnection
from app.integrations.xero_client import RealXeroClient

router = APIRouter(prefix="/xero", tags=["xero"])

# In-memory state store for the OAuth dance. In production, persist with TTL.
_STATE: set[str] = set()


@router.get("/connect")
def connect():
    state = secrets.token_urlsafe(24)
    _STATE.add(state)
    return RedirectResponse(RealXeroClient.authorize_url(state))


@router.get("/callback")
def callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    if state not in _STATE:
        raise HTTPException(400, "invalid state")
    _STATE.discard(state)
    token = RealXeroClient.exchange_code(code)
    db.add(
        XeroConnection(
            tenant_id=token.tenant_id,
            tenant_name=token.tenant_name,
            access_token_encrypted=encrypt_token(token.access_token),
            refresh_token_encrypted=encrypt_token(token.refresh_token),
            expires_at=token.expires_at,
        )
    )
    return {"status": "connected", "tenant_id": token.tenant_id, "tenant_name": token.tenant_name}
