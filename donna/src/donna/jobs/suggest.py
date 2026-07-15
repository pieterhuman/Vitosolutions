"""Suggest job: turn recurring uncertain patterns into a human-reviewed
report of candidate rules.

This is NOT machine learning in the trained-model sense, and it is
deliberately not one: hard constraint 1 (no LLM anywhere in the decision
path, no AI API calls at runtime) rules out anything probabilistic
deciding an item's fate. What this job does instead is count — the same
ambiguous (counterparty, unknown-sender) pair recurring across multiple
threads is a fact about the ledger, not a guess. Once a human reviews a
suggestion and runs its SQL, the result is an ordinary known_alias row:
a plain deterministic rule the poll job already knows how to use. The
"learning" never re-enters the decision path; it only ever proposes
data for a human to approve, same as VipContact and ExclusionRule.
"""
from __future__ import annotations

import html as _html
import pathlib
from datetime import datetime

from ..store import Store
from ..telemetry import get_logger

log = get_logger(__name__)


def run_suggest(store: Store, now: datetime,
                report_dir: str | None = None) -> dict:
    threshold = int(store.config_get("suggestion_min_occurrences"))
    pending = store.pending_suggestions(threshold)

    out_dir = report_dir or store.config_get("suggestion_report_dir")
    path = pathlib.Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    report_path = path / f"suggestions_{now:%Y%m%dT%H%M}.html"
    report_path.write_text(_render(pending, now), encoding="utf-8")

    store.record_job_run("suggest", "success", now,
                         detail=f"pending={len(pending)}")
    log.info("suggest complete pending=%d threshold=%d",
             len(pending), threshold)
    return {"pending": len(pending), "report": str(report_path)}


def _e(text: str) -> str:
    return _html.escape(text, quote=True)


def _render(rows, now: datetime) -> str:
    if not rows:
        body = "<p>No recurring patterns have crossed the review threshold.</p>"
    else:
        items = "".join(
            "<li style='margin-bottom:14px'>"
            f"<b>{_e(r.counterparty_smtp)}</b> — replies keep arriving from "
            f"<b>{_e(r.signal_smtp)}</b> instead "
            f"({r.occurrences} times, e.g. “{_e(r.example_subject)}”).<br>"
            f"If this is a known assistant/alternate address, approve it:<br>"
            f"<code style='display:block;margin-top:4px;padding:6px;"
            f"background:#f1efe8'>{_e(r.suggested_sql)}</code>"
            f"<span style='color:#666'>Otherwise, no action needed — it "
            f"will keep surfacing here and the items stay flagged either way.</span>"
            "</li>"
            for r in rows
        )
        body = f"<ul style='padding-left:20px'>{items}</ul>"
    return (
        "<div style='font-family:Segoe UI,Arial,sans-serif;max-width:720px'>"
        f"<h2 style='margin:0 0 4px'>Recurring pattern review</h2>"
        f"<p style='margin:0 0 16px;color:#666'>{now:%A %d %B %Y} UTC — "
        "advisory only. Nothing here has changed any item's state.</p>"
        f"{body}</div>"
    )
