"""Workflow 3 — reply handling.

Polls the vicky@ Gmail inbox, matches senders to leads, classifies each
new reply with Claude, and routes:

  unsubscribe   -> immediate DNC + remove from Apollo sequence (no approval)
  out_of_office -> ignore (Apollo pauses OOO contacts itself)
  not_now       -> snooze + nurture stage, no outbound send
  referral      -> human approval task with the referred-to details
  interested / meeting_request / objection
                -> draft a reply (grounded in scripts, with ET slots when
                   relevant) and queue it for HUMAN APPROVAL. Nothing is
                   sent until `vicky approvals approve <id>` runs.
"""

from __future__ import annotations

import json
import logging

from . import calendar_slots, db
from .apollo_client import ApolloClient
from .config import Config
from .llm import LLM
from .mailer import Mailer

log = logging.getLogger("vicky.replies")

AUTO_SNOOZE = {"not_now"}
IGNORE = {"out_of_office"}


def run(cfg: Config, apollo: ApolloClient | None, llm: LLM,
        mailer: Mailer) -> dict:
    lookback = cfg.s("replies.lookback_days", 4)
    inbound = mailer.fetch_recent_inbound(lookback)
    processed = queued = 0

    with db.connect() as conn:
        for msg in inbound:
            if not msg["message_id"]:
                continue
            seen = conn.execute(
                "SELECT 1 FROM replies WHERE gmail_message_id=?",
                (msg["message_id"],)).fetchone()
            if seen:
                continue
            lead = conn.execute(
                "SELECT * FROM leads WHERE lower(email)=?",
                (msg["from_email"],)).fetchone()
            if not lead:
                continue  # not a tracked prospect (newsletter, internal, ...)

            lead = dict(lead)
            classification = llm.classify_reply(lead, msg["body"])
            cls = classification.get("classification", "other")
            conn.execute(
                "INSERT INTO replies(lead_id, gmail_message_id, direction, "
                "classification, body_excerpt, created_at) VALUES(?,?,?,?,?,?)",
                (lead["id"], msg["message_id"], "in", cls,
                 msg["body"][:500], db.now()))
            db.log(conn, "reply_in",
                   f"classified={cls} sentiment="
                   f"{classification.get('sentiment')}: "
                   f"{classification.get('summary', '')}", lead["id"])
            processed += 1

            if cls == "unsubscribe":
                _handle_unsubscribe(cfg, apollo, conn, lead)
                continue
            if cls in IGNORE:
                continue
            if cls in AUTO_SNOOZE:
                days = cfg.s("nurture.not_now_snooze_days", 42)
                conn.execute(
                    "UPDATE leads SET snooze_until=date('now', ?), "
                    "stage='nurture' WHERE id=?", (f"+{days} days", lead["id"]))
                db.log(conn, "snoozed", f"'not now' — re-engage in {days}d",
                       lead["id"])
                continue

            # Everything else: draft + queue for approval.
            if lead["stage"] in ("new", "sequenced"):
                db.set_stage(conn, lead["id"], "replied",
                             f"inbound reply classified {cls}")
            slots = None
            if cls in ("meeting_request", "interested"):
                slots = calendar_slots.format_slots(
                    calendar_slots.propose_slots(cfg))
            draft = llm.draft_reply(lead, msg["body"], classification, slots)
            payload = {
                "to": lead["email"],
                "subject": f"Re: {msg['subject']}".strip(),
                "body": draft,
                "classification": cls,
                "slots": slots or [],
                "their_message": msg["body"][:1000],
            }
            conn.execute(
                "INSERT INTO approvals(lead_id, kind, payload, reason, "
                "status, created_at) VALUES(?,?,?,?, 'pending', ?)",
                (lead["id"], "reply_draft", json.dumps(payload),
                 f"{cls} reply from {lead['title']} at {lead['company']} — "
                 f"human review required by policy", db.now()))
            db.log(conn, "approval_queued",
                   f"reply draft ({cls}) awaiting approval", lead["id"])
            queued += 1

        db.log(conn, "replies_run",
               f"inbound_scanned={len(inbound)} processed={processed} "
               f"queued_for_approval={queued}")
    return {"scanned": len(inbound), "new": processed, "queued": queued}


def _handle_unsubscribe(cfg: Config, apollo: ApolloClient | None, conn,
                        lead: dict) -> None:
    db.mark_dnc(conn, lead["id"], "unsubscribe request in reply — honored "
                                  "immediately, no further contact")
    if apollo and lead.get("apollo_contact_id") and lead.get("sequence_key"):
        seq_id = cfg.sequence_id(lead["sequence_key"])
        if seq_id:
            try:
                apollo.remove_contacts_from_sequence(
                    seq_id, [lead["apollo_contact_id"]])
                db.log(conn, "sequence_removed",
                       "removed from Apollo sequence after unsubscribe",
                       lead["id"])
            except Exception as exc:  # noqa: BLE001
                db.log(conn, "error",
                       f"failed to remove from sequence: {exc} — "
                       "REMOVE MANUALLY IN APOLLO", lead["id"])
