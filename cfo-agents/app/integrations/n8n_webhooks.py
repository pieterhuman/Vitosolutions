"""Outbound webhooks to n8n. Used for notifications and triggering downstream flows."""

from __future__ import annotations

import hmac
import hashlib
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def fire_webhook(path: str, payload: dict[str, Any]) -> bool:
    s = get_settings()
    if not s.n8n_webhook_base:
        log.info("n8n.skip", reason="no_base", path=path)
        return False
    url = s.n8n_webhook_base.rstrip("/") + "/" + path.lstrip("/")
    body = httpx.Request("POST", url, json=payload).read()
    headers = {"Content-Type": "application/json"}
    if s.n8n_webhook_secret:
        headers["X-Signature"] = _sign(body, s.n8n_webhook_secret)
    try:
        with httpx.Client(timeout=10) as c:
            r = c.post(url, content=body, headers=headers)
            r.raise_for_status()
        return True
    except Exception as e:
        log.warning("n8n.fail", path=path, error=str(e))
        return False
