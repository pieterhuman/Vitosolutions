"""Telemetry redaction, enforced at the logging boundary.

Constraint: telemetry must never contain email subjects, bodies, or
addresses — SHA-256 hashes only. This module installs a log-record
factory, which is the single choke point every `logging` record in the
process passes through, regardless of which logger or handler produced
it. Call sites therefore do not need to remember to redact.

Call sites that want a stable correlation key for a subject or address
should use `hash_text()` themselves; anything that slips through as a
literal email address is caught here and replaced with its hash.
"""
from __future__ import annotations

import hashlib
import logging
import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def hash_text(value: str) -> str:
    """SHA-256 of the normalized value, truncated for log readability."""
    digest = hashlib.sha256(value.strip().casefold().encode("utf-8"))
    return digest.hexdigest()[:16]


def scrub(text: str) -> str:
    return _EMAIL_RE.sub(lambda m: f"smtp#{hash_text(m.group())}", text)


_installed = False


def install() -> None:
    """Install the redacting record factory. Idempotent."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = scrub(rendered)
        record.args = ()
        return record

    logging.setLogRecordFactory(factory)
    _installed = True


def get_logger(name: str) -> logging.Logger:
    install()
    return logging.getLogger(name)
