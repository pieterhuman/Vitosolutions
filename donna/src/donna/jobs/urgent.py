"""Urgent job: VIP items past their threshold, alerted exactly once.

Payload discipline (hard constraint 3): the Teams Workflows webhook
receives counts and VIP category labels ONLY. Never subjects, never
bodies, never addresses.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from .. import states
from ..store import Store
from ..telemetry import get_logger

log = get_logger(__name__)


def _in_quiet_hours(now: datetime, window: str) -> bool:
    """window is "HH:MM-HH:MM" UTC and may wrap midnight."""
    try:
        start_s, end_s = window.split("-")
        start = time.fromisoformat(start_s.strip())
        end = time.fromisoformat(end_s.strip())
    except ValueError:
        return False
    t = now.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def run_urgent(store: Store, webhook_post, now: datetime) -> dict:
    quiet = store.config_get("quiet_hours_utc")
    if _in_quiet_hours(now, quiet):
        # Not marked as alerted, so the alert fires after quiet hours end.
        return {"alerted": 0, "suppressed_quiet_hours": True}

    label_counts: dict[str, int] = {}
    due_ids: list[int] = []
    for item in store.items(item_states=states.ACTIVE_STATES):
        if item.urgent_alerted_utc is not None:
            continue
        vip = store.vip_match(item.counterparty_smtp)
        if vip is None:
            continue
        if now <= item.anchor_utc + timedelta(hours=item.threshold_hours):
            continue
        label_counts[vip.label] = label_counts.get(vip.label, 0) + 1
        due_ids.append(item.id)

    if not due_ids:
        store.record_job_run("urgent", "success", now, detail="none_due")
        return {"alerted": 0}

    webhook_post(_adaptive_card(label_counts))
    for item_id in due_ids:
        store.mark_urgent_alerted(item_id, now)
    store.record_job_run("urgent", "success", now,
                         detail=f"alerted={len(due_ids)}")
    log.info("urgent alert sent items=%d categories=%d",
             len(due_ids), len(label_counts))
    return {"alerted": len(due_ids)}


def _adaptive_card(label_counts: dict[str, int]) -> dict:
    total = sum(label_counts.values())
    facts = [{"title": label, "value": str(count)}
             for label, count in sorted(label_counts.items())]
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {"type": "TextBlock", "weight": "Bolder",
                     "text": f"Donna: {total} VIP item(s) past threshold"},
                    {"type": "FactSet", "facts": facts},
                    {"type": "TextBlock", "isSubtle": True, "wrap": True,
                     "text": "Details are in your next briefing email."},
                ],
            },
        }],
    }
