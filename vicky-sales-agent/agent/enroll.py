"""Workflow 2/3 — enroll scored leads into the right Apollo sequence,
respecting daily budgets, warm-up, and suppression."""

from __future__ import annotations

import logging

from . import db, guardrails
from .apollo_client import ApolloClient
from .config import Config

log = logging.getLogger("vicky.enroll")


def _ensure_contact(apollo: ApolloClient, conn, lead) -> str | None:
    """Return an Apollo contact id, creating the contact if needed."""
    if lead["apollo_contact_id"]:
        return lead["apollo_contact_id"]
    try:
        created = apollo.create_contact(
            first_name=lead["first_name"], last_name=lead["last_name"],
            title=lead["title"], email=lead["email"],
            organization_name=lead["company"],
        )
        contact = created.get("contact") or {}
        if contact.get("id"):
            conn.execute("UPDATE leads SET apollo_contact_id=? WHERE id=?",
                         (contact["id"], lead["id"]))
            return contact["id"]
    except Exception as exc:  # noqa: BLE001
        db.log(conn, "error", f"contact creation failed: {exc}", lead["id"])
    return None


def run(cfg: Config, apollo: ApolloClient, sequence_key: str = "primary",
        limit: int | None = None) -> dict:
    """Enroll the highest-scoring un-sequenced leads. Returns counts."""
    sender_id = cfg.apollo.get("send_email_account_id")
    if not sender_id:
        log.error("no send_email_account_id — link %s in Apollo, then run "
                  "`vicky doctor`", cfg.sender_email)
        return {"enrolled": 0, "blocked": "mailbox not linked in Apollo"}

    seq = (cfg.apollo.get("sequences") or {}).get(sequence_key) or {}
    if not seq.get("id"):
        return {"enrolled": 0, "blocked": f"sequence '{sequence_key}' has no id"}
    if not seq.get("active"):
        return {"enrolled": 0,
                "blocked": f"sequence '{sequence_key}' is inactive — review "
                           f"it in Apollo and run `vicky activate {sequence_key}`"}

    enrolled = 0
    with db.connect() as conn:
        ok, reason = guardrails.check_can_run(cfg, conn)
        if not ok:
            return {"enrolled": 0, "blocked": reason}

        budget = guardrails.emails_remaining_today(cfg, conn)
        if limit is not None:
            budget = min(budget, limit)
        if budget <= 0:
            return {"enrolled": 0, "blocked": "daily email budget exhausted"}

        threshold = cfg.s("scoring.enroll_threshold", 60)
        rows = conn.execute(
            "SELECT * FROM leads WHERE stage='new' AND do_not_contact=0 "
            "AND score >= ? AND (snooze_until IS NULL OR snooze_until <= date('now')) "
            "ORDER BY score DESC, created_at ASC LIMIT ?",
            (threshold, budget),
        ).fetchall()

        for lead in rows:
            if guardrails.is_suppressed(cfg, lead["email"],
                                        lead["company_domain"]):
                db.log(conn, "skipped", "suppressed domain", lead["id"])
                continue
            contact_id = _ensure_contact(apollo, conn, lead)
            if not contact_id:
                continue
            try:
                apollo.add_contacts_to_sequence(seq["id"], [contact_id],
                                                sender_id)
            except Exception as exc:  # noqa: BLE001
                db.log(conn, "error", f"enrollment failed: {exc}", lead["id"])
                continue
            db.set_stage(conn, lead["id"], "sequenced",
                         f"enrolled in '{seq['name']}' (score {lead['score']}: "
                         f"{lead['score_reasons']})")
            conn.execute(
                "UPDATE leads SET sequence_key=?, enrolled_at=datetime('now') "
                "WHERE id=?", (sequence_key, lead["id"]))
            db.log(conn, "enrolled",
                   f"sequence={sequence_key} sender={cfg.sender_email}",
                   lead["id"])
            enrolled += 1

        if enrolled:
            guardrails.bump_warmup(conn)
        db.log(conn, "enroll_run", f"enrolled={enrolled} budget_was={budget}")
    return {"enrolled": enrolled}
