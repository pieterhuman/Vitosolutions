"""CLI — the human control surface. `python -m agent <command>` or the
`vicky` entrypoint after `pip install -e .`."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from . import approvals, daily_loop, db, enroll, guardrails, leadgen, \
    metrics, nurture, replies, sequences
from .apollo_client import ApolloClient
from .config import load
from .llm import LLM
from .mailer import Mailer

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")


def _apollo(cfg):
    return ApolloClient(cfg.apollo_api_key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vicky", description="Unicorn Club outbound sales agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the local database")
    sub.add_parser("doctor", help="check Apollo/Gmail/LLM wiring")
    sub.add_parser("sync-sequences",
                   help="create/verify Apollo sequences from templates")

    p = sub.add_parser("activate", help="activate a sequence (starts sending!)")
    p.add_argument("key", choices=["primary", "warm", "pilot"])
    p = sub.add_parser("deactivate", help="pause a sequence in Apollo")
    p.add_argument("key", choices=["primary", "warm", "pilot"])

    p = sub.add_parser("leadgen", help="source + score new leads")
    p.add_argument("--max", type=int, default=None)
    p = sub.add_parser("enroll", help="enroll scored leads into a sequence")
    p.add_argument("--sequence", default="primary",
                   choices=["primary", "warm", "pilot"])
    p.add_argument("--limit", type=int, default=None)
    sub.add_parser("check-replies", help="poll Gmail, classify, queue drafts")
    sub.add_parser("nurture", help="run snooze/re-engagement transitions")
    sub.add_parser("daily", help="run the full daily loop")

    sub.add_parser("pipeline", help="show pipeline by stage")
    p = sub.add_parser("leads", help="list leads")
    p.add_argument("--stage", default=None)
    p.add_argument("--limit", type=int, default=25)
    p = sub.add_parser("note", help="attach a note to a lead")
    p.add_argument("email")
    p.add_argument("text", nargs="+")
    p = sub.add_parser("dnc", help="mark a lead do-not-contact")
    p.add_argument("email")

    p = sub.add_parser("approvals", help="human approval queue")
    p.add_argument("action", choices=["list", "show", "approve", "reject"])
    p.add_argument("id", nargs="?", type=int)
    p.add_argument("--reason", default="")

    p = sub.add_parser("pause", help="pause all outbound immediately")
    p.add_argument("--reason", default="manual pause")
    sub.add_parser("resume", help="resume outbound")

    p = sub.add_parser("report", help="print daily/weekly summary")
    p.add_argument("--days", type=int, default=1)

    args = parser.parse_args(argv)
    cfg = load()
    db.init()

    if args.cmd == "init":
        print(f"database ready at data/vicky.db")

    elif args.cmd == "doctor":
        problems = []
        if not cfg.apollo_api_key:
            problems.append("APOLLO_API_KEY not set")
        else:
            try:
                apollo = _apollo(cfg)
                acct = apollo.find_sender_account(cfg.sender_email)
                if acct:
                    cfg.apollo["send_email_account_id"] = acct["id"]
                    cfg.save_apollo()
                    print(f"OK  Apollo mailbox linked: {cfg.sender_email} "
                          f"({acct['id']})")
                else:
                    problems.append(
                        f"{cfg.sender_email} not linked in Apollo — "
                        "Apollo Settings -> Mailboxes -> Link mailbox")
            except Exception as exc:  # noqa: BLE001
                problems.append(f"Apollo API error: {exc}")
        if not cfg.anthropic_api_key:
            print("..  ANTHROPIC_API_KEY not set (SDK may still resolve an "
                  "`ant auth login` profile)")
        if not cfg.gmail_app_password:
            problems.append("GMAIL_APP_PASSWORD not set — reply polling and "
                            "approved sends disabled")
        for key in ("primary", "warm", "pilot"):
            seq = (cfg.apollo.get("sequences") or {}).get(key) or {}
            state = "ACTIVE" if seq.get("active") else "inactive"
            print(f"OK  sequence {key}: {seq.get('id', 'MISSING')} [{state}]")
        for problem in problems:
            print(f"FIX {problem}")
        return 1 if problems else 0

    elif args.cmd == "sync-sequences":
        print(json.dumps(sequences.sync(cfg, _apollo(cfg)), indent=2))

    elif args.cmd in ("activate", "deactivate"):
        active = args.cmd == "activate"
        if active:
            confirm = input(
                f"Activate '{args.key}' — enrolled contacts WILL be emailed "
                f"from {cfg.sender_email}. Type 'yes' to confirm: ")
            if confirm.strip().lower() != "yes":
                print("aborted")
                return 1
        sequences.set_active(cfg, _apollo(cfg), args.key, active)
        with db.connect() as conn:
            db.log(conn, "sequence_" + ("activated" if active else "paused"),
                   f"{args.key} by operator")
        print(f"{args.key}: {'active' if active else 'paused'}")

    elif args.cmd == "leadgen":
        print(json.dumps(leadgen.run(cfg, _apollo(cfg), args.max), indent=2))

    elif args.cmd == "enroll":
        print(json.dumps(
            enroll.run(cfg, _apollo(cfg), args.sequence, args.limit), indent=2))

    elif args.cmd == "check-replies":
        result = replies.run(cfg, _apollo(cfg), LLM(cfg), Mailer(cfg))
        print(json.dumps(result, indent=2))

    elif args.cmd == "nurture":
        llm = LLM(cfg) if cfg.anthropic_api_key else None
        print(json.dumps(nurture.run(cfg, llm), indent=2))

    elif args.cmd == "daily":
        summary = daily_loop.run(cfg)
        print(json.dumps(summary, indent=2, default=str))

    elif args.cmd == "pipeline":
        with db.connect() as conn:
            for stage, n in metrics.pipeline_summary(conn).items():
                print(f"{stage:20s} {n}")

    elif args.cmd == "leads":
        query = "SELECT email, first_name, last_name, title, company, score, " \
                "stage FROM leads"
        params: list = []
        if args.stage:
            query += " WHERE stage=?"
            params.append(args.stage)
        query += " ORDER BY score DESC LIMIT ?"
        params.append(args.limit)
        with db.connect() as conn:
            for r in conn.execute(query, params):
                print(f"{r['score']:3d}  {r['stage']:15s} "
                      f"{r['first_name']} {r['last_name']} — {r['title']} "
                      f"@ {r['company']}  <{r['email']}>")

    elif args.cmd == "note":
        with db.connect() as conn:
            row = conn.execute("SELECT id FROM leads WHERE email=?",
                               (args.email,)).fetchone()
            if not row:
                print("lead not found")
                return 1
            text = " ".join(args.text)
            conn.execute("UPDATE leads SET notes = notes || ? WHERE id=?",
                         (f"\n{text}", row["id"]))
            db.log(conn, "note", text, row["id"])
        print("noted")

    elif args.cmd == "dnc":
        with db.connect() as conn:
            row = conn.execute("SELECT id FROM leads WHERE email=?",
                               (args.email,)).fetchone()
            if not row:
                print("lead not found")
                return 1
            db.mark_dnc(conn, row["id"], "manually marked by operator")
        print("marked do-not-contact")

    elif args.cmd == "approvals":
        if args.action == "list":
            with db.connect() as conn:
                for a in approvals.pending(conn):
                    print(f"#{a['id']:4d} {a['kind']:16s} "
                          f"{a['first_name']} {a['last_name']} @ {a['company']} "
                          f"— {a['reason']}")
        elif args.action == "show":
            with db.connect() as conn:
                for a in approvals.pending(conn):
                    if a["id"] == args.id:
                        print(json.dumps(json.loads(a["payload"]), indent=2))
                        return 0
            print("not found")
            return 1
        elif args.action == "approve":
            print(approvals.approve(cfg, Mailer(cfg), args.id))
        elif args.action == "reject":
            print(approvals.reject(args.id, args.reason))

    elif args.cmd == "pause":
        with db.connect() as conn:
            guardrails.set_paused(conn, True, args.reason)
        print("paused — no outbound until `vicky resume`")

    elif args.cmd == "resume":
        with db.connect() as conn:
            guardrails.set_paused(conn, False, "operator resume")
        print("resumed")

    elif args.cmd == "report":
        print(metrics.render_report(cfg, args.days))

    return 0


if __name__ == "__main__":
    sys.exit(main())
