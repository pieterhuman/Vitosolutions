"""Mark-as-done endpoint logic. STUB — fails the suite."""
from __future__ import annotations

from datetime import datetime


def handle_close(store, token: str, key: bytes,
                 now: datetime) -> tuple[int, dict]:
    """Return (http_status, response_body)."""
    raise NotImplementedError("stub engine")
