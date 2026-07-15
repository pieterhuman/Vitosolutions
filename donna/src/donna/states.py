"""Item states and the allowed transitions between them.

closed_human is reachable ONLY through the signed mark-as-done link
(donna.http_close); no job may write it.
"""
from __future__ import annotations

OPEN = "open"
UNCERTAIN = "uncertain"
CLOSED_EVIDENCE = "closed_evidence"
CLOSED_HUMAN = "closed_human"
CLOSED_EXCLUDED = "closed_excluded"

KIND_INBOUND = "inbound_unanswered"
KIND_SENT_AWAITING = "sent_awaiting_reply"

ACTIVE_STATES = (OPEN, UNCERTAIN)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    OPEN: frozenset({UNCERTAIN, CLOSED_EVIDENCE, CLOSED_HUMAN, CLOSED_EXCLUDED}),
    UNCERTAIN: frozenset({CLOSED_EVIDENCE, CLOSED_HUMAN, CLOSED_EXCLUDED}),
    CLOSED_EVIDENCE: frozenset(),
    CLOSED_HUMAN: frozenset(),
    CLOSED_EXCLUDED: frozenset(),
}


class IllegalTransition(Exception):
    pass


def check_transition(from_state: str, to_state: str) -> None:
    if to_state not in ALLOWED_TRANSITIONS.get(from_state, frozenset()):
        raise IllegalTransition(f"{from_state} -> {to_state}")
