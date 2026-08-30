"""Unit tests for the pure-logic modules (no network, no API keys)."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import db, guardrails
from agent.calendar_slots import ET, format_slots, propose_slots
from agent.config import load
from agent.scoring import score_lead
from agent.sequences import _body_to_html, template_to_payload


@pytest.fixture
def cfg():
    return load()


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "test.db"
    db.init(path)
    with db.connect(path) as c:
        yield c


# ------------------------------------------------------------- scoring ------
def test_perfect_icp_lead_scores_high(cfg):
    lead = {
        "title": "VP Engineering", "company_size": 200, "state": "New York",
        "country": "United States", "hiring_signal": True,
        "funding_signal": True, "tech_signal": True,
    }
    score, reasons = score_lead(cfg, lead)
    assert score >= 90
    assert "title exact match" in reasons


def test_off_icp_lead_scores_low(cfg):
    score, _ = score_lead(cfg, {"title": "Marketing Intern",
                                "company_size": 10000, "state": "",
                                "country": "Germany"})
    assert score < cfg.s("scoring.enroll_threshold")


def test_partial_title(cfg):
    score, reasons = score_lead(cfg, {"title": "Senior Director of AI Platforms",
                                      "company_size": 150,
                                      "state": "Georgia",
                                      "country": "United States"})
    assert "title partial match" in reasons
    assert score > 0


# ---------------------------------------------------------- guardrails ------
def test_pause_switch(cfg, conn):
    assert not guardrails.is_paused(conn)
    guardrails.set_paused(conn, True, "test")
    assert guardrails.is_paused(conn)
    ok, reason = guardrails.check_can_run(cfg, conn)
    assert not ok and "paused" in reason


def test_spam_lint_flags_bad_copy():
    hits = guardrails.lint_copy("FREE guarantee!! Act now, limited time")
    assert len(hits) >= 3


def test_spam_lint_passes_real_copy(cfg):
    body = cfg.sequences["primary"]["steps"][0]["body"]
    assert guardrails.lint_copy(body) == []


def test_all_sequence_email_copy_passes_lint(cfg):
    for seq in cfg.sequences.values():
        for step in seq["steps"]:
            if "body" in step:
                assert guardrails.lint_copy(step["body"]) == [], seq["name"]


def test_suppression(cfg):
    assert guardrails.is_suppressed(cfg, "a@getunicornclub.com", None)
    assert not guardrails.is_suppressed(cfg, "a@example.com", "example.com")


def test_deliverability_breaker(cfg):
    ok, _ = guardrails.check_deliverability(
        cfg, {"delivered": 100, "bounced": 10, "spam_blocked": 0})
    assert not ok
    ok, _ = guardrails.check_deliverability(
        cfg, {"delivered": 100, "bounced": 1, "spam_blocked": 0})
    assert ok


# ------------------------------------------------------------------ db ------
def test_lead_dedupe(conn):
    lead = {"email": "cto@acme.com", "first_name": "Ada", "title": "CTO",
            "company": "Acme"}
    id1, created1 = db.upsert_lead(conn, lead)
    id2, created2 = db.upsert_lead(conn, {**lead, "score": 80})
    assert id1 == id2 and created1 and not created2


def test_stage_machine(conn):
    lead_id, _ = db.upsert_lead(conn, {"email": "x@y.com"})
    db.set_stage(conn, lead_id, "sequenced", "test")
    with pytest.raises(ValueError):
        db.set_stage(conn, lead_id, "bogus_stage", "test")
    row = conn.execute("SELECT stage FROM leads WHERE id=?",
                       (lead_id,)).fetchone()
    assert row["stage"] == "sequenced"


def test_unsubscribe_marks_dnc(conn):
    lead_id, _ = db.upsert_lead(conn, {"email": "no@more.com"})
    db.mark_dnc(conn, lead_id, "unsubscribe")
    row = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    assert row["do_not_contact"] == 1 and row["stage"] == "unsubscribed"


# ------------------------------------------------------------- booking ------
def test_slots_are_weekday_business_hours_et(cfg):
    slots = propose_slots(cfg)
    assert len(slots) == cfg.s("booking.slots_to_propose", 3)
    for slot in slots:
        assert slot.tzinfo is not None
        assert slot.weekday() < 5
        assert 9 <= slot.astimezone(ET).hour <= 16
    assert all("ET" in s for s in format_slots(slots))


def test_slots_respect_min_notice(cfg):
    earliest = min(propose_slots(cfg))
    hours_out = (earliest - datetime.now(ET)).total_seconds() / 3600
    assert hours_out >= cfg.s("booking.min_notice_hours", 20)


# ----------------------------------------------------------- sequences ------
def test_template_to_payload_shapes(cfg):
    payload = template_to_payload(cfg, "primary")
    assert payload["active"] is False
    assert len(payload["emailer_steps"]) == 6
    first = payload["emailer_steps"][0]
    assert first["type"] == "auto_email" and first["wait_time"] == 0
    subject = first["emailer_touches"][0]["emailer_template"]["subject"]
    assert len(subject.split()) <= 9
    # pilot sequence's first step must require review
    pilot = template_to_payload(cfg, "pilot")
    assert pilot["emailer_steps"][0]["emailer_touches"][0]["status"] == \
        "to_be_reviewed"


def test_body_to_html():
    html = _body_to_html("para one\nsame para\n\npara two")
    assert html == "<p>para one same para</p><p>para two</p>"
