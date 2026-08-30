"""Safety rails: volume caps, warm-up ramp, suppression, pause switch,
spam-language lint, deliverability circuit breaker.

Every check returns (ok, reason) so callers can log WHY something was
blocked — the audit log is part of the guardrail.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from . import db
from .config import Config

SPAM_PATTERNS = [
    r"\bfree\b", r"\bguarantee[d]?\b", r"\blimited time\b", r"\bact now\b",
    r"\bbuy now\b", r"\bno obligation\b", r"\brisk[- ]free\b", r"100%",
    r"\bwinner\b", r"!!+", r"\bcheap\b", r"\bclick here\b", r"\burgent\b",
]


def is_paused(conn) -> bool:
    return db.kv_get(conn, "paused", "0") == "1"


def set_paused(conn, paused: bool, reason: str) -> None:
    db.kv_set(conn, "paused", "1" if paused else "0")
    db.log(conn, "pause" if paused else "resume", reason)


def is_weekday() -> bool:
    return datetime.now(timezone.utc).weekday() < 5


def check_can_run(cfg: Config, conn) -> tuple[bool, str]:
    if is_paused(conn):
        return False, "agent is paused (vicky resume to continue)"
    if cfg.s("guardrails.weekdays_only", True) and not is_weekday():
        return False, "weekend: outbound is weekdays-only"
    return True, "ok"


def emails_remaining_today(cfg: Config, conn) -> int:
    """Daily NEW-enrollment budget, honoring the warm-up ramp."""
    cap = cfg.s("volumes.max_emails_per_day", 40)
    warm = cfg.s("volumes.warmup", {})
    if warm.get("enabled", True):
        days = int(db.kv_get(conn, "warmup_days_elapsed", "0"))
        ramp = warm.get("start_per_day", 15) + days * warm.get("increment_per_day", 5)
        cap = min(cap, ramp)
    used = db.count_events_today(conn, "enrolled")
    return max(cap - used, 0)


def linkedin_remaining_today(cfg: Config, conn) -> int:
    cap = cfg.s("volumes.max_linkedin_touches_per_day", 50)
    used = db.count_events_today(conn, "linkedin_task")
    return max(cap - used, 0)


def bump_warmup(conn) -> None:
    """Call once per successful send day."""
    today = datetime.now(timezone.utc).date().isoformat()
    if db.kv_get(conn, "warmup_last_day") != today:
        days = int(db.kv_get(conn, "warmup_days_elapsed", "0"))
        db.kv_set(conn, "warmup_days_elapsed", str(days + 1))
        db.kv_set(conn, "warmup_last_day", today)


def is_suppressed(cfg: Config, email: str | None, domain: str | None) -> bool:
    blocked = [d.lower() for d in cfg.s("guardrails.suppression_domains", [])]
    if email and email.split("@")[-1].lower() in blocked:
        return True
    if domain and domain.lower() in blocked:
        return True
    return False


def lint_copy(text: str) -> list[str]:
    """Return spam-language violations found in outbound copy."""
    hits = []
    for pattern in SPAM_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            hits.append(pattern)
    words = len(re.findall(r"\S+", text))
    if words > 160:
        hits.append(f"too long ({words} words)")
    return hits


def check_deliverability(cfg: Config, stats: dict) -> tuple[bool, str]:
    """stats: {'delivered': n, 'bounced': n, 'spam_blocked': n} over the
    trailing window. Returns (healthy, reason); unhealthy should auto-pause."""
    delivered = stats.get("delivered", 0)
    if delivered < 20:  # not enough volume to judge
        return True, "insufficient volume for a verdict"
    bounce_rate = stats.get("bounced", 0) / delivered
    spam_rate = stats.get("spam_blocked", 0) / delivered
    if bounce_rate > cfg.s("guardrails.max_bounce_rate", 0.03):
        return False, f"bounce rate {bounce_rate:.1%} over limit"
    if spam_rate > cfg.s("guardrails.max_spam_block_rate", 0.01):
        return False, f"spam-block rate {spam_rate:.1%} over limit"
    return True, "healthy"
