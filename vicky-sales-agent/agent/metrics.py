"""Workflow 4/6 — pipeline views and daily/weekly metric rollups."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import db
from .config import REPORTS_DIR, Config


def pipeline_summary(conn) -> dict[str, int]:
    rows = conn.execute(
        "SELECT stage, COUNT(*) AS n FROM leads GROUP BY stage").fetchall()
    return {r["stage"]: r["n"] for r in rows}


def _count(conn, kind: str, since: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE kind=? AND created_at>=?",
        (kind, since)).fetchone()["n"]


def rollup(conn, days: int = 1) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    replies_in = _count(conn, "reply_in", since)
    positive = conn.execute(
        "SELECT COUNT(*) AS n FROM replies WHERE direction='in' AND "
        "classification IN ('interested','meeting_request') AND created_at>=?",
        (since,)).fetchone()["n"]
    return {
        "window_days": days,
        "new_leads": _count(conn, "lead_created", since),
        "enrolled": _count(conn, "enrolled", since),
        "linkedin_tasks": _count(conn, "linkedin_task", since),
        "replies_in": replies_in,
        "positive_replies": positive,
        "replies_sent": _count(conn, "reply_out", since),
        "meetings_booked": conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE kind='stage_change' AND "
            "detail LIKE '-> discovery_booked%' AND created_at>=?",
            (since,)).fetchone()["n"],
        "pilots_proposed": conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE kind='stage_change' AND "
            "detail LIKE '-> pilot_proposed%' AND created_at>=?",
            (since,)).fetchone()["n"],
        "unsubscribes": _count(conn, "do_not_contact", since),
        "errors": _count(conn, "error", since),
    }


def render_report(cfg: Config, days: int = 1) -> str:
    with db.connect() as conn:
        stats = rollup(conn, days)
        stages = pipeline_summary(conn)
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM approvals WHERE status='pending'"
        ).fetchone()["n"]

    label = "Daily" if days == 1 else f"{days}-day"
    active_roles = stages.get("pilot_active", 0) + stages.get("expanded", 0)
    lines = [
        f"# Vicky — {label} summary "
        f"({datetime.now(timezone.utc).date().isoformat()})",
        "",
        "## Activity",
        f"- New leads sourced: {stats['new_leads']}",
        f"- Enrolled in sequences: {stats['enrolled']}",
        f"- LinkedIn tasks created: {stats['linkedin_tasks']}",
        f"- Replies received: {stats['replies_in']} "
        f"({stats['positive_replies']} positive)",
        f"- Replies sent (human-approved): {stats['replies_sent']}",
        f"- Meetings booked: {stats['meetings_booked']}",
        f"- Pilots proposed: {stats['pilots_proposed']}",
        f"- Unsubscribes honored: {stats['unsubscribes']}",
        f"- Errors: {stats['errors']}",
        "",
        "## Pipeline",
    ]
    lines += [f"- {stage}: {stages[stage]}" for stage in sorted(stages)]
    lines += [
        "",
        f"**Active data/AI roles (goal 5): {active_roles}**",
        f"**Pending approvals needing you: {pending}** "
        "(`vicky approvals list`)",
    ]
    report = "\n".join(lines)
    path = REPORTS_DIR / f"summary-{datetime.now(timezone.utc).date()}.md"
    path.write_text(report)
    return report
