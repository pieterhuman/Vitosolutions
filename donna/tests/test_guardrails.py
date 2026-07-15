"""Cross-cutting guarantees: telemetry redaction, append-only ledger,
heartbeat signal, no hedging in closure logic, state machine legality."""
from __future__ import annotations

import logging
import pathlib

import pytest

from donna import states, telemetry
from donna.jobs.heartbeat import ALERT_LINE, run_heartbeat
from donna.states import KIND_INBOUND

from conftest import ALICE, T, pid

SRC = pathlib.Path(__file__).parent.parent / "src" / "donna"


# -- telemetry boundary ------------------------------------------------------

def test_email_addresses_scrubbed_at_logging_boundary(caplog):
    telemetry.install()
    log = logging.getLogger("donna.test.boundary")
    with caplog.at_level(logging.INFO, logger="donna.test.boundary"):
        log.info("processing mail from lawyer@sterlinglaw.example "
                 "to alice@familyoffice.example")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "lawyer@sterlinglaw.example" not in joined
    assert "alice@familyoffice.example" not in joined
    assert "smtp#" in joined  # replaced by hash, not silently dropped


def test_scrub_applies_to_percent_formatted_args(caplog):
    telemetry.install()
    log = logging.getLogger("donna.test.boundary2")
    with caplog.at_level(logging.INFO, logger="donna.test.boundary2"):
        log.info("counterparty=%s", "vip@bigclient.example")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "vip@bigclient.example" not in joined


def test_hash_is_stable_and_normalized():
    a = telemetry.hash_text("Lawyer@SterlingLaw.example ")
    b = telemetry.hash_text("lawyer@sterlinglaw.example")
    assert a == b and len(a) == 16


# -- append-only ledger --------------------------------------------------------

def test_item_event_rejects_update_and_delete(store):
    import sqlalchemy as sa
    from donna.store import AppendOnlyViolation, item_event

    item = store.create_item_if_new(
        principal_id=pid(store, ALICE), kind=KIND_INBOUND,
        conversation_id="AAQk-cY", internet_message_id="<y@ext.example>",
        subject="s", counterparty_smtp="c@ext.example", counterparty_name="",
        anchor_utc=T("2026-07-01T08:00:00Z"), threshold_hours=24,
        now=T("2026-07-01T08:30:00Z"))

    with store.engine.begin() as cx:
        with pytest.raises(AppendOnlyViolation):
            cx.execute(item_event.update().values(evidence="tampered"))
    with store.engine.begin() as cx:
        with pytest.raises(AppendOnlyViolation):
            cx.execute(item_event.delete())
    assert len(store.events_for(item.id)) == 1


def test_state_change_and_event_are_atomic(store):
    item = _mk(store)
    before = len(store.events_for(item.id))
    with pytest.raises(states.IllegalTransition):
        store.transition(item.id, "nonsense-state", reason="r",
                         evidence="", actor_upn=None,
                         now=T("2026-07-01T09:00:00Z"))
    assert store.get_item(item.id).state == states.OPEN
    assert len(store.events_for(item.id)) == before


def _mk(store):
    return store.create_item_if_new(
        principal_id=pid(store, ALICE), kind=KIND_INBOUND,
        conversation_id="AAQk-cZ", internet_message_id="<z@ext.example>",
        subject="s", counterparty_smtp="c@ext.example", counterparty_name="",
        anchor_utc=T("2026-07-01T08:00:00Z"), threshold_hours=24,
        now=T("2026-07-01T08:30:00Z"))


def test_closed_states_are_terminal_except_via_nothing(store):
    item = _mk(store)
    store.transition(item.id, states.CLOSED_EVIDENCE, reason="r",
                     evidence="", actor_upn=ALICE,
                     now=T("2026-07-01T09:00:00Z"))
    with pytest.raises(states.IllegalTransition):
        store.transition(item.id, states.OPEN, reason="no reopen",
                         evidence="", actor_upn=None,
                         now=T("2026-07-01T10:00:00Z"))


# -- uncertain never auto-closes -------------------------------------------------

def test_uncertain_to_closed_human_allowed_evidence_allowed_open_not():
    states.check_transition(states.UNCERTAIN, states.CLOSED_HUMAN)
    states.check_transition(states.UNCERTAIN, states.CLOSED_EVIDENCE)
    with pytest.raises(states.IllegalTransition):
        states.check_transition(states.UNCERTAIN, states.OPEN)


# -- heartbeat -------------------------------------------------------------------

def test_heartbeat_raises_signal_when_digest_missing(store, caplog):
    with caplog.at_level(logging.CRITICAL):
        result = run_heartbeat(store, now=T("2026-07-01T04:45:00Z"))
    assert result["missed"] is True
    assert any(ALERT_LINE in r.getMessage() for r in caplog.records)


def test_heartbeat_quiet_after_recent_digest_success(store, caplog):
    store.record_job_run("digest", "success", T("2026-07-01T04:30:00Z"))
    with caplog.at_level(logging.CRITICAL):
        result = run_heartbeat(store, now=T("2026-07-01T04:45:00Z"))
    assert result["missed"] is False
    assert not any(ALERT_LINE in r.getMessage() for r in caplog.records)


# -- definition of done: no hedging in the decision path ---------------------------

def test_the_word_probably_appears_nowhere_in_source():
    offenders = [
        p for p in SRC.rglob("*.py")
        if "probably" in p.read_text(encoding="utf-8").casefold()
    ]
    assert offenders == []
