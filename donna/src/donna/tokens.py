"""Signed single-use mark-as-done tokens.

Token = base64url("{item_id}.{principal_id}.{expiry_epoch}.{hmac}")
where hmac = HMAC-SHA256(key, "{item_id}.{principal_id}.{expiry_epoch}").
The signing key lives in Key Vault; it reaches this module as bytes via
donna.config. TTL is 36 hours. Single use is enforced by the close
endpoint: a token for an item that is no longer open/uncertain is spent.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

TOKEN_TTL_SECONDS = 36 * 3600


class TokenError(Exception):
    pass


def _sign(payload: str, key: bytes) -> str:
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_token(item_id: int, principal_id: int, expiry_epoch: int,
               key: bytes) -> str:
    payload = f"{item_id}.{principal_id}.{expiry_epoch}"
    raw = f"{payload}.{_sign(payload, key)}"
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii")


def verify_token(token: str, key: bytes, now_epoch: int) -> tuple[int, int]:
    """Return (item_id, principal_id) or raise TokenError."""
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("ascii")
        item_id, principal_id, expiry, signature = raw.split(".")
        payload = f"{item_id}.{principal_id}.{expiry}"
    except Exception as exc:
        raise TokenError("malformed token") from exc
    if not hmac.compare_digest(signature, _sign(payload, key)):
        raise TokenError("bad signature")
    if now_epoch > int(expiry):
        raise TokenError("token expired")
    return int(item_id), int(principal_id)
