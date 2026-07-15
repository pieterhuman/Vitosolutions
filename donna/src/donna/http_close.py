"""Mark-as-done endpoint logic — the ONLY path to closed_human.

Token rules: HMAC-SHA256 over itemId+principalId+expiry, 36h TTL,
single-use, and the token's principal must own the item. Single use is
structural: closing moves the item out of the active states, so a
replayed token hits the 409 branch.
"""
from __future__ import annotations

from datetime import datetime

from . import states
from .store import Store
from .telemetry import get_logger
from .tokens import TokenError, TokenExpired, verify_token

log = get_logger(__name__)


def handle_close(store: Store, token: str, key: bytes,
                 now: datetime) -> tuple[int, dict]:
    """Return (http_status, response_body)."""
    try:
        item_id, principal_id = verify_token(token, key,
                                             int(now.timestamp()))
    except TokenExpired:
        return 403, {"error": "token expired"}
    except TokenError:
        return 400, {"error": "invalid token"}

    item = store.get_item(item_id)
    if item is None:
        return 404, {"error": "unknown item"}
    if item.principal_id != principal_id:
        log.warning("close token principal mismatch item=%d", item_id)
        return 403, {"error": "token does not match item owner"}
    if item.state not in states.ACTIVE_STATES:
        return 409, {"error": "already closed", "state": item.state}

    principal = store.principal_by_id(principal_id)
    store.transition(item.id, states.CLOSED_HUMAN,
                     reason="human_marked_done",
                     evidence=f"close_token item={item.id}",
                     actor_upn=principal.upn, now=now)
    log.info("item %d closed_human", item.id)
    return 200, {"result": "closed", "item": item.id}
