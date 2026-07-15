"""Deterministic message classification rules. STUB — fails the suite."""
from __future__ import annotations

from ..model import Message


def is_auto_reply(msg: Message) -> bool:
    raise NotImplementedError("stub engine")


def is_bulk(msg: Message) -> bool:
    raise NotImplementedError("stub engine")


def normalize_subject(subject: str) -> str:
    raise NotImplementedError("stub engine")


def matches_exclusion(msg: Message, rules) -> bool:
    raise NotImplementedError("stub engine")


def addressed_in_to(msg: Message, smtp: str) -> bool:
    raise NotImplementedError("stub engine")


def external_counterparty(msg: Message, internal_domains) -> tuple[str, str] | None:
    raise NotImplementedError("stub engine")
