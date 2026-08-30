"""Workflow 5 — follow-up & nurture.

- Un-snoozes 'not now' leads whose snooze expired -> back to 'new' so the
  daily loop re-enrolls them (warm sequence, fresh angle).
- Re-engages leads that finished the primary sequence without replying
  after nurture.reengage_after_days.
- Queues referral-ask drafts after positive interactions.
"""

from __future__ import annotations

import json
import logging

from . import db
from .config import Config
from .llm import LLM

log = logging.getLogger("vicky.nurture")


def run(cfg: Config, llm: LLM | None = None) -> dict:
    reengage_days = cfg.s("nurture.reengage_after_days", 35)
    woken = requeued = referrals = 0

    with db.connect() as conn:
        # 1. Wake snoozed leads.
        rows = conn.execute(
            "SELECT id FROM leads WHERE stage='nurture' AND do_not_contact=0 "
            "AND snooze_until IS NOT NULL AND snooze_until <= date('now')"
        ).fetchall()
        for row in rows:
            db.set_stage(conn, row["id"], "new",
                         "snooze expired — eligible for warm re-engagement")
            conn.execute("UPDATE leads SET snooze_until=NULL, "
                         "sequence_key='warm' WHERE id=?", (row["id"],))
            woken += 1

        # 2. Re-engage sequenced leads that went quiet.
        rows = conn.execute(
            "SELECT id FROM leads WHERE stage='sequenced' AND do_not_contact=0 "
            "AND enrolled_at IS NOT NULL "
            "AND enrolled_at <= datetime('now', ?)",
            (f"-{reengage_days} days",),
        ).fetchall()
        for row in rows:
            db.set_stage(conn, row["id"], "nurture",
                         f"no reply {reengage_days}d after enrollment — "
                         "moved to nurture pool")
            conn.execute(
                "UPDATE leads SET snooze_until=date('now', '+7 days') "
                "WHERE id=?", (row["id"],))
            requeued += 1

        # 3. Referral asks after positive interactions.
        if llm and cfg.s("nurture.referral_ask_after_positive", True):
            rows = conn.execute(
                "SELECT l.* FROM leads l WHERE l.stage IN "
                "('discovery_booked','pilot_active','expanded') "
                "AND l.do_not_contact=0 AND NOT EXISTS ("
                "  SELECT 1 FROM events e WHERE e.lead_id=l.id "
                "  AND e.kind='referral_ask_queued')"
            ).fetchall()
            for lead in rows:
                lead = dict(lead)
                draft = llm.referral_ask(
                    lead, f"stage: {lead['stage']}")
                payload = {"to": lead["email"],
                           "subject": "one quick ask",
                           "body": draft}
                conn.execute(
                    "INSERT INTO approvals(lead_id, kind, payload, reason, "
                    "status, created_at) VALUES(?,?,?,?, 'pending', ?)",
                    (lead["id"], "reply_draft", json.dumps(payload),
                     "referral ask after positive interaction", db.now()))
                db.log(conn, "referral_ask_queued",
                       "referral ask drafted, awaiting approval", lead["id"])
                referrals += 1

        db.log(conn, "nurture_run",
               f"woken={woken} moved_to_nurture={requeued} "
               f"referral_asks={referrals}")
    return {"woken": woken, "moved_to_nurture": requeued,
            "referral_asks": referrals}
