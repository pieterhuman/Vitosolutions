"""SQLite persistence: leads, pipeline stages, audit log, approvals, replies.

Every mutation goes through this module so the audit trail stays complete.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH

STAGES = [
    "new",
    "sequenced",
    "replied",
    "discovery_booked",
    "profiles_sent",
    "pilot_proposed",
    "pilot_active",
    "expanded",
    "closed_lost",
    "nurture",
    "unsubscribed",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY,
    apollo_person_id TEXT,
    apollo_contact_id TEXT UNIQUE,
    email TEXT UNIQUE,
    first_name TEXT, last_name TEXT, title TEXT,
    linkedin_url TEXT,
    company TEXT, company_domain TEXT, company_size INTEGER,
    city TEXT, state TEXT, country TEXT,
    signals TEXT DEFAULT '[]',          -- JSON list of fit signals
    score INTEGER DEFAULT 0,
    score_reasons TEXT DEFAULT '',
    stage TEXT DEFAULT 'new',
    sequence_key TEXT,                  -- primary|warm|pilot
    enrolled_at TEXT,
    snooze_until TEXT,                  -- ISO date; skip outreach before this
    do_not_contact INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);
CREATE INDEX IF NOT EXISTS idx_leads_domain ON leads(company_domain);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER,
    kind TEXT NOT NULL,                 -- enrolled|reply_in|reply_out|stage_change|...
    detail TEXT NOT NULL,               -- human-readable action + reasoning
    created_at TEXT NOT NULL,
    FOREIGN KEY(lead_id) REFERENCES leads(id)
);
CREATE INDEX IF NOT EXISTS idx_events_kind_date ON events(kind, created_at);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER,
    kind TEXT NOT NULL,                 -- reply_draft|calendar_invite|pilot_proposal
    payload TEXT NOT NULL,              -- JSON: draft body, slots, etc.
    reason TEXT NOT NULL,               -- why this needs a human
    status TEXT DEFAULT 'pending',      -- pending|approved|rejected|expired
    created_at TEXT NOT NULL,
    decided_at TEXT,
    FOREIGN KEY(lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS replies (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER,
    gmail_message_id TEXT UNIQUE,       -- dedupe across polls
    direction TEXT NOT NULL,            -- in|out
    classification TEXT,
    body_excerpt TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(path: Path = DB_PATH):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(path: Path = DB_PATH) -> None:
    path.parent.mkdir(exist_ok=True)
    with connect(path) as conn:
        conn.executescript(SCHEMA)


# ------------------------------------------------------------------ kv -------
def kv_get(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def kv_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# --------------------------------------------------------------- events ------
def log(conn, kind: str, detail: str, lead_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO events(lead_id, kind, detail, created_at) VALUES(?,?,?,?)",
        (lead_id, kind, detail, now()),
    )


# ---------------------------------------------------------------- leads ------
def upsert_lead(conn, lead: dict) -> tuple[int, bool]:
    """Insert or refresh a lead keyed by email. Returns (id, created)."""
    existing = None
    if lead.get("email"):
        existing = conn.execute(
            "SELECT id FROM leads WHERE email=?", (lead["email"],)
        ).fetchone()
    if not existing and lead.get("apollo_contact_id"):
        existing = conn.execute(
            "SELECT id FROM leads WHERE apollo_contact_id=?",
            (lead["apollo_contact_id"],),
        ).fetchone()

    cols = [
        "apollo_person_id", "apollo_contact_id", "email", "first_name",
        "last_name", "title", "linkedin_url", "company", "company_domain",
        "company_size", "city", "state", "country", "signals", "score",
        "score_reasons",
    ]
    values = {c: lead.get(c) for c in cols}
    if isinstance(values.get("signals"), (list, dict)):
        values["signals"] = json.dumps(values["signals"])

    if existing:
        sets = ", ".join(f"{c}=COALESCE(?, {c})" for c in cols)
        conn.execute(
            f"UPDATE leads SET {sets}, updated_at=? WHERE id=?",
            [*values.values(), now(), existing["id"]],
        )
        return existing["id"], False

    conn.execute(
        f"INSERT INTO leads({', '.join(cols)}, stage, created_at, updated_at) "
        f"VALUES({', '.join('?' * len(cols))}, 'new', ?, ?)",
        [*values.values(), now(), now()],
    )
    lead_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    log(conn, "lead_created", f"Sourced lead {lead.get('email')} "
        f"({lead.get('title')} @ {lead.get('company')})", lead_id)
    return lead_id, True


def set_stage(conn, lead_id: int, stage: str, reason: str) -> None:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    conn.execute(
        "UPDATE leads SET stage=?, updated_at=? WHERE id=?",
        (stage, now(), lead_id),
    )
    log(conn, "stage_change", f"-> {stage}: {reason}", lead_id)


def mark_dnc(conn, lead_id: int, reason: str) -> None:
    conn.execute(
        "UPDATE leads SET do_not_contact=1, stage='unsubscribed', updated_at=? "
        "WHERE id=?",
        (now(), lead_id),
    )
    log(conn, "do_not_contact", reason, lead_id)


def count_events_today(conn, kind: str) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE kind=? AND created_at >= ?",
        (kind, today),
    ).fetchone()
    return row["n"]
