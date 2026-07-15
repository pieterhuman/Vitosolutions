"""Typed view over a Microsoft Graph message resource.

Only the fields Donna needs; everything else in the Graph payload is
ignored. Header names are case-insensitive per RFC 5322, so they are
folded to lowercase at parse time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def parse_graph_datetime(value: str) -> datetime:
    """Graph emits ISO-8601 with a trailing Z."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _smtp(recipient: dict) -> str:
    return recipient.get("emailAddress", {}).get("address", "").casefold()


def _name(recipient: dict) -> str:
    return recipient.get("emailAddress", {}).get("name", "")


@dataclass(frozen=True)
class Message:
    graph_id: str
    internet_message_id: str
    conversation_id: str
    subject: str
    from_smtp: str
    from_name: str
    to: tuple[str, ...]
    cc: tuple[str, ...]
    sent: datetime
    received: datetime
    web_link: str = ""
    headers: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_graph(cls, payload: dict) -> "Message":
        headers: dict[str, list[str]] = {}
        for h in payload.get("internetMessageHeaders") or []:
            headers.setdefault(h["name"].casefold(), []).append(h["value"])
        frm = payload.get("from") or payload.get("sender") or {}
        return cls(
            graph_id=payload["id"],
            internet_message_id=payload.get("internetMessageId", ""),
            conversation_id=payload.get("conversationId", ""),
            subject=payload.get("subject", ""),
            from_smtp=_smtp(frm),
            from_name=_name(frm),
            to=tuple(_smtp(r) for r in payload.get("toRecipients") or []),
            cc=tuple(_smtp(r) for r in payload.get("ccRecipients") or []),
            sent=parse_graph_datetime(payload["sentDateTime"]),
            received=parse_graph_datetime(payload["receivedDateTime"]),
            web_link=payload.get("webLink", ""),
            headers={k: tuple(v) for k, v in headers.items()},
        )

    def header(self, name: str) -> str | None:
        values = self.headers.get(name.casefold())
        return values[0] if values else None

    def has_header(self, name: str) -> bool:
        return name.casefold() in self.headers
