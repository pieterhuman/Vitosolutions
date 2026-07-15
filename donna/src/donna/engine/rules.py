"""Deterministic message classification rules.

These rules ARE the decision path. There is no model, no scoring, no
heuristic confidence anywhere in here — every function returns a fact
derived from headers, addresses, or configured rules, and nothing else.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..model import Message

# RFC 3834 Auto-Submitted values. "auto-replied" marks OOO-style
# auto-responses; "auto-generated" marks machine-generated notices.
_AUTO_REPLIED = "auto-replied"
_AUTO_GENERATED = "auto-generated"

_BULK_PRECEDENCE = {"bulk", "list", "junk"}

# Iteratively stripped reply/forward prefixes across the locales this
# tenant sees (EN, AF/NL, DE, FR, SE/FI).
_PREFIX_RE = re.compile(
    r"^\s*(re|fw|fwd|aw|antw|antwoord|wg|tr|rv|sv|vs)\s*:\s*",
    re.IGNORECASE,
)


def is_auto_reply(msg: Message) -> bool:
    """OOO and similar auto-responses: never closure evidence, never an
    item, and never grounds for uncertainty."""
    value = msg.header("Auto-Submitted")
    return value is not None and value.strip().casefold().startswith(
        _AUTO_REPLIED)


def is_bulk(msg: Message) -> bool:
    """Newsletter / no-reply traffic: excluded before item creation."""
    if msg.has_header("List-Unsubscribe"):
        return True
    precedence = msg.header("Precedence")
    if precedence and precedence.strip().casefold() in _BULK_PRECEDENCE:
        return True
    auto = msg.header("Auto-Submitted")
    if auto and auto.strip().casefold().startswith(_AUTO_GENERATED):
        return True
    if msg.has_header("X-Auto-Response-Suppress"):
        return True
    return False


def normalize_subject(subject: str) -> str:
    s = subject
    while True:
        stripped = _PREFIX_RE.sub("", s, count=1)
        if stripped == s:
            break
        s = stripped
    return re.sub(r"\s+", " ", s).strip().casefold()


def matches_exclusion(msg: Message, rules: Iterable) -> bool:
    """ExclusionRule rows: kind in sender|domain|header|subject_regex.

    header pattern is "Name" (presence) or "Name:regex" (value match).
    """
    sender = msg.from_smtp
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    for rule in rules:
        pattern = rule.pattern
        if rule.kind == "sender":
            if sender == pattern.casefold():
                return True
        elif rule.kind == "domain":
            p = pattern.casefold().lstrip("@")
            if domain == p or domain.endswith("." + p):
                return True
        elif rule.kind == "header":
            name, _, value_re = pattern.partition(":")
            values = msg.headers.get(name.strip().casefold())
            if values is None:
                continue
            if not value_re.strip():
                return True
            if any(re.search(value_re.strip(), v, re.IGNORECASE)
                   for v in values):
                return True
        elif rule.kind == "subject_regex":
            if re.search(pattern, msg.subject, re.IGNORECASE):
                return True
    return False


def addressed_in_to(msg: Message, smtp: str) -> bool:
    """True only when the principal is a To recipient. CC-only mail never
    becomes an item."""
    return smtp.casefold() in msg.to


def external_counterparty(msg: Message,
                          internal_domains: set[str],
                          ) -> tuple[str, str] | None:
    """First To recipient outside the tenant's internal domains, as
    (smtp, display name). None for purely internal mail."""
    internal = {d.casefold().lstrip("@") for d in internal_domains}

    def is_internal(smtp: str) -> bool:
        dom = smtp.rsplit("@", 1)[-1]
        return any(dom == d or dom.endswith("." + d) for d in internal)

    for recipient in msg.to:
        if recipient and not is_internal(recipient):
            return recipient, ""
    return None
