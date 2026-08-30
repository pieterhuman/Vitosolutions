"""Human-in-the-loop approval queue.

Kinds:
  reply_draft     -> approve = send the drafted reply via Gmail SMTP
  calendar_invite -> approve = email the .ics invite to the prospect
  pilot_proposal  -> approve = send the pilot proposal email

Approve/reject from the CLI: `vicky approvals list|show|approve|reject`.
"""

from __future__ import annotations

import json
from datetime import datetime

from . import calendar_slots, db
from .config import Config
from .mailer import Mailer


def pending(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT a.*, l.email AS lead_email, l.first_name, l.last_name, "
        "l.company FROM approvals a LEFT JOIN leads l ON l.id = a.lead_id "
        "WHERE a.status='pending' ORDER BY a.created_at").fetchall()
    return [dict(r) for r in rows]


def approve(cfg: Config, mailer: Mailer, approval_id: int,
            edited_body: str | None = None) -> str:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM approvals WHERE id=? AND "
                           "status='pending'", (approval_id,)).fetchone()
        if not row:
            return f"approval {approval_id} not found or not pending"
        payload = json.loads(row["payload"])
        body = edited_body or payload["body"]

        if row["kind"] in ("reply_draft", "pilot_proposal"):
            mailer.send(payload["to"], payload["subject"], body)
            db.log(conn, "reply_out",
                   f"approved & sent ({row['kind']}, approval {approval_id})",
                   row["lead_id"])
            conn.execute(
                "INSERT INTO replies(lead_id, direction, classification, "
                "body_excerpt, created_at) VALUES(?, 'out', ?, ?, ?)",
                (row["lead_id"], row["kind"], body[:500], db.now()))
            if row["kind"] == "pilot_proposal":
                db.set_stage(conn, row["lead_id"], "pilot_proposed",
                             "pilot proposal approved and sent")
        elif row["kind"] == "calendar_invite":
            start = datetime.fromisoformat(payload["start"])
            ics = calendar_slots.build_ics(
                cfg, start=start, attendee_email=payload["to"],
                attendee_name=payload.get("name", ""),
                summary=payload.get("summary",
                                    "Discovery call — Unicorn Club"),
                description=payload.get("description", ""))
            mailer.send(payload["to"], payload.get(
                "summary", "Discovery call — Unicorn Club"),
                payload.get("body", "Calendar invite attached."), ics)
            db.set_stage(conn, row["lead_id"], "discovery_booked",
                         f"invite sent for {payload['start']}")
        else:
            return f"unknown approval kind {row['kind']}"

        conn.execute("UPDATE approvals SET status='approved', decided_at=? "
                     "WHERE id=?", (db.now(), approval_id))
    return f"approval {approval_id} executed"


def reject(approval_id: int, reason: str = "") -> str:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM approvals WHERE id=? AND "
                           "status='pending'", (approval_id,)).fetchone()
        if not row:
            return f"approval {approval_id} not found or not pending"
        conn.execute("UPDATE approvals SET status='rejected', decided_at=? "
                     "WHERE id=?", (db.now(), approval_id))
        db.log(conn, "approval_rejected",
               f"approval {approval_id} rejected: {reason or 'no reason'}",
               row["lead_id"])
    return f"approval {approval_id} rejected"


def queue_calendar_invite(conn, lead: dict, start_iso: str,
                          body: str = "") -> None:
    payload = {
        "to": lead["email"],
        "name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
        "start": start_iso,
        "summary": "Discovery call — Unicorn Club x " + (lead.get("company") or ""),
        "body": body or "Looking forward to it — invite attached.",
    }
    conn.execute(
        "INSERT INTO approvals(lead_id, kind, payload, reason, status, "
        "created_at) VALUES(?,?,?,?, 'pending', ?)",
        (lead["id"], "calendar_invite", json.dumps(payload),
         "calendar bookings require human confirmation", db.now()))
    db.log(conn, "approval_queued", f"calendar invite for {start_iso}",
           lead["id"])
