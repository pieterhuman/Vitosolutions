"""Heartbeat job: verify the digest job recorded a success recently.

If not, emit the log line the Azure Monitor scheduled-query alert keys
on. The operator wires the action group; we only emit the signal.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..telemetry import get_logger

log = get_logger(__name__)

ALERT_LINE = "DONNA_HEARTBEAT_MISSED"


def run_heartbeat(store, now: datetime) -> dict:
    window = timedelta(hours=int(store.config_get("heartbeat_window_hours")))
    last = store.last_success_utc("digest")
    missed = last is None or (now - last) > window
    if missed:
        log.critical("%s job=digest last_success=%s window_hours=%s",
                     ALERT_LINE, last.isoformat() if last else "never",
                     int(window.total_seconds() // 3600))
    else:
        log.info("DONNA_HEARTBEAT_OK job=digest last_success=%s",
                 last.isoformat())
    store.record_job_run("heartbeat", "success", now,
                         detail="missed" if missed else "ok")
    return {"missed": missed, "last_success": last}
