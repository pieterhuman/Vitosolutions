"""The core daily execution loop. Safe to run multiple times a day — every
step is idempotent and budget-aware. Order matters:

  1. Preflight (pause switch, weekday, mailbox link, deliverability)
  2. Reply handling first — never keep sequencing someone who answered
  3. Nurture transitions (snoozes, re-engagement)
  4. Lead sourcing + scoring
  5. Enrollment into sequences (budget + warm-up capped)
  6. Surface today's LinkedIn tasks for the human
  7. Report
"""

from __future__ import annotations

import logging

from . import db, enroll, guardrails, leadgen, metrics, nurture, replies
from .apollo_client import ApolloClient, ApolloError
from .config import Config
from .llm import LLM
from .mailer import Mailer

log = logging.getLogger("vicky.daily")


def preflight(cfg: Config, apollo: ApolloClient) -> list[str]:
    """Return a list of blocking problems (empty = good to go)."""
    problems = []
    with db.connect() as conn:
        ok, reason = guardrails.check_can_run(cfg, conn)
        if not ok:
            problems.append(reason)

    if not cfg.apollo.get("send_email_account_id"):
        acct = None
        try:
            acct = apollo.find_sender_account(cfg.sender_email)
        except ApolloError as exc:
            problems.append(f"Apollo API unreachable: {exc}")
        if acct:
            cfg.apollo["send_email_account_id"] = acct["id"]
            cfg.save_apollo()
            log.info("resolved sender mailbox id: %s", acct["id"])
        else:
            problems.append(
                f"{cfg.sender_email} is not linked as a mailbox in Apollo "
                "(Settings -> Mailboxes). Sequences cannot send until it is.")

    # Deliverability circuit breaker on our sequences' trailing stats.
    try:
        stats = {"delivered": 0, "bounced": 0, "spam_blocked": 0}
        for seq in apollo.search_sequences(q_name="Vicky ").get(
                "emailer_campaigns", []):
            for key, field in (("delivered", "unique_delivered"),
                               ("bounced", "unique_bounced"),
                               ("spam_blocked", "unique_spam_blocked")):
                value = seq.get(field)
                if isinstance(value, int):
                    stats[key] += value
        healthy, reason = guardrails.check_deliverability(cfg, stats)
        if not healthy:
            with db.connect() as conn:
                guardrails.set_paused(conn, True,
                                      f"AUTO-PAUSE: {reason} ({stats})")
            problems.append(f"auto-paused: {reason}")
    except ApolloError as exc:
        log.warning("could not fetch sequence stats: %s", exc)
    return problems


def surface_linkedin_tasks(cfg: Config, apollo: ApolloClient) -> list[dict]:
    """Fetch open LinkedIn/call tasks from Apollo, capped to today's budget.
    These are for the HUMAN to execute (Apollo shows them in Tasks too)."""
    tasks = []
    with db.connect() as conn:
        budget = guardrails.linkedin_remaining_today(cfg, conn)
        if budget <= 0:
            return []
        try:
            found = apollo.search_tasks().get("tasks", [])
        except ApolloError as exc:
            db.log(conn, "error", f"task fetch failed: {exc}")
            return []
        for task in found:
            if len(tasks) >= budget:
                break
            if "linkedin" in (task.get("type") or "").lower() or \
                    "call" in (task.get("type") or "").lower():
                tasks.append({
                    "id": task.get("id"),
                    "type": task.get("type"),
                    "contact": (task.get("contact") or {}).get("name"),
                    "note": task.get("note"),
                    "due": task.get("due_at"),
                })
                db.log(conn, "linkedin_task",
                       f"{task.get('type')} for "
                       f"{(task.get('contact') or {}).get('name')}")
    return tasks


def run(cfg: Config, *, skip_replies: bool = False) -> dict:
    summary: dict = {}
    apollo = ApolloClient(cfg.apollo_api_key)

    problems = preflight(cfg, apollo)
    summary["preflight"] = problems or ["ok"]
    hard_blocked = any("paused" in p or "weekend" in p for p in problems)
    if hard_blocked:
        log.warning("daily loop blocked: %s", problems)
        return summary

    # 2. Replies first.
    if not skip_replies and cfg.s("replies.poll_gmail", True) \
            and cfg.gmail_app_password:
        llm = LLM(cfg)
        mailer = Mailer(cfg)
        summary["replies"] = replies.run(cfg, apollo, llm, mailer)
    else:
        summary["replies"] = "skipped (no GMAIL_APP_PASSWORD or disabled)"

    # 3. Nurture transitions.
    llm_for_nurture = LLM(cfg) if cfg.anthropic_api_key else None
    summary["nurture"] = nurture.run(cfg, llm_for_nurture)

    # 4. Source new leads.
    summary["leadgen"] = leadgen.run(cfg, apollo)

    # 5. Enroll (blocked internally if mailbox missing or sequence inactive).
    summary["enroll"] = enroll.run(cfg, apollo, "primary")

    # 6. LinkedIn tasks for the human.
    summary["linkedin_tasks"] = surface_linkedin_tasks(cfg, apollo)

    # 7. Report.
    summary["report"] = metrics.render_report(cfg, days=1)

    if cfg.s("reporting.send_email_summary", False) and cfg.gmail_app_password:
        Mailer(cfg).send(cfg.s("reporting.daily_summary_to"),
                         "Vicky — daily summary", summary["report"])
    return summary
