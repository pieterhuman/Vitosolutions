"""The scenario suite. This IS the spec for the closure engine.

Each test drives donna.engine.poll.run_poll with synthetic Graph delta
pages and asserts ledger state. No LLM, no heuristics: every assertion
is a deterministic consequence of the state-machine rules.
"""
from __future__ import annotations

from donna import states
from donna.engine.poll import run_poll
from donna.states import (
    CLOSED_EVIDENCE, KIND_INBOUND, KIND_SENT_AWAITING, OPEN, UNCERTAIN,
)

from conftest import ALICE, BOB, CAROL, CEO, DAN, ERIN, FRANK, T, fixture, pid


def only(seq):
    assert len(seq) == 1, f"expected exactly one, got {len(seq)}"
    return seq[0]


# -- 01 plain reply in-thread ---------------------------------------------

def test_reply_in_thread_closes_inbound_item(graph, store):
    graph.queue(ALICE, "inbox", [fixture("m01_inbound")])
    run_poll(graph, store, now=T("2026-07-01T08:30:00Z"))

    item = only(store.items(kind=KIND_INBOUND))
    assert item.state == OPEN
    assert item.threshold_hours == 24
    assert item.counterparty_smtp == "lawyer@sterlinglaw.example"

    graph.queue(ALICE, "sentitems", [fixture("m01_reply_sent")])
    run_poll(graph, store, now=T("2026-07-01T09:30:00Z"))

    item = only(store.items(kind=KIND_INBOUND))
    assert item.state == CLOSED_EVIDENCE
    assert item.state_reason == "replied_in_thread"
    assert item.closed_by_upn == ALICE
    events = store.events_for(item.id)
    assert [(e.from_state, e.to_state) for e in events] == [
        ("none", OPEN), (OPEN, CLOSED_EVIDENCE)]
    # The outbound reply to an external counterparty starts the
    # sent-awaiting-reply clock (72h) per the state machine.
    awaiting = only(store.items(kind=KIND_SENT_AWAITING))
    assert awaiting.state == OPEN
    assert awaiting.threshold_hours == 72


# -- 02 different monitored team member closes it ---------------------------

def test_team_member_reply_closes_with_attribution(graph, store):
    graph.queue(ALICE, "inbox", [fixture("m02_inbound")])
    run_poll(graph, store, now=T("2026-07-01T08:30:00Z"))
    graph.queue(BOB, "sentitems", [fixture("m02_team_reply")])
    run_poll(graph, store, now=T("2026-07-01T10:30:00Z"))

    item = only(store.items(kind=KIND_INBOUND,
                            principal_id=pid(store, ALICE)))
    assert item.state == CLOSED_EVIDENCE
    assert item.state_reason == "handled_by_team"
    assert item.closed_by_upn == BOB


# -- 03 reply from unknown sender -> UNCERTAIN ------------------------------

def test_unknown_sender_reply_goes_uncertain(graph, store):
    graph.queue(ALICE, "inbox", [fixture("m03_inbound")])
    run_poll(graph, store, now=T("2026-07-01T08:30:00Z"))
    graph.queue(ALICE, "inbox", [fixture("m03_unknown_reply")])
    run_poll(graph, store, now=T("2026-07-01T11:30:00Z"))

    items = store.items(kind=KIND_INBOUND, principal_id=pid(store, ALICE))
    item = only(items)  # no duplicate item for the same conversation
    assert item.state == UNCERTAIN
    assert item.state_reason == "reply_from_unknown_sender"
    assert item.closed_utc is None  # stays flagged, never silently closed


# -- 04 out-of-office auto-reply closes nothing ------------------------------

def test_ooo_autoreply_does_not_close_sent_awaiting(graph, store):
    graph.queue(ALICE, "sentitems", [fixture("m04_outbound")])
    run_poll(graph, store, now=T("2026-07-01T08:32:00Z"))
    awaiting = only(store.items(kind=KIND_SENT_AWAITING))
    assert awaiting.state == OPEN

    graph.queue(ALICE, "inbox", [fixture("m04_ooo_reply")])
    run_poll(graph, store, now=T("2026-07-01T09:00:00Z"))

    awaiting = only(store.items(kind=KIND_SENT_AWAITING))
    assert awaiting.state == OPEN, "OOO auto-reply must not close"
    # And the auto-reply itself never becomes an inbound item.
    assert store.items(kind=KIND_INBOUND,
                       principal_id=pid(store, ALICE)) == []


def test_own_ooo_in_sent_items_does_not_close_inbound(graph, store):
    graph.queue(CAROL, "inbox", [fixture("m04_inbound_carol")])
    run_poll(graph, store, now=T("2026-07-01T08:40:00Z"))
    graph.queue(CAROL, "sentitems", [fixture("m04_carol_ooo_sent")])
    run_poll(graph, store, now=T("2026-07-01T09:00:00Z"))

    item = only(store.items(kind=KIND_INBOUND,
                            principal_id=pid(store, CAROL)))
    assert item.state == OPEN, "own OOO bounce is not closure evidence"
    # The OOO auto-reply is not an outbound follow-up either.
    assert store.items(kind=KIND_SENT_AWAITING,
                       principal_id=pid(store, CAROL)) == []


# -- 05 newsletter / no-reply signals: excluded, never an item ----------------

def test_bulk_and_excluded_mail_never_becomes_items(graph, store):
    graph.queue(DAN, "inbox", [
        fixture("m05_list_unsubscribe"),
        fixture("m05_precedence_bulk"),
        fixture("m05_auto_generated"),
        fixture("m05_suppress"),
        fixture("m05_exclusion_rule"),
    ])
    run_poll(graph, store, now=T("2026-07-01T09:00:00Z"))
    assert store.items() == []


# -- 06 CC-only never becomes an item ----------------------------------------

def test_cc_only_recipient_gets_no_item(graph, store):
    msg = fixture("m06_cc_only")
    graph.queue(BOB, "inbox", [msg])
    graph.queue(ERIN, "inbox", [msg])
    run_poll(graph, store, now=T("2026-07-01T09:00:00Z"))

    assert store.items(principal_id=pid(store, ERIN)) == []
    item = only(store.items(principal_id=pid(store, BOB)))
    assert item.kind == KIND_INBOUND and item.state == OPEN


# -- 07 quiet thread stays open forever ---------------------------------------

def test_quiet_thread_stays_open(graph, store):
    graph.queue(FRANK, "inbox", [fixture("m07_inbound")])
    run_poll(graph, store, now=T("2026-07-01T09:00:00Z"))
    # 45 days of silence and many polls later: still open, no new events.
    run_poll(graph, store, now=T("2026-08-15T09:00:00Z"))
    run_poll(graph, store, now=T("2026-08-15T09:30:00Z"))

    item = only(store.items(principal_id=pid(store, FRANK)))
    assert item.state == OPEN
    assert len(store.events_for(item.id)) == 1  # creation only


# -- 08 forwarded then replied, subject-prefix variants ------------------------

def test_forward_then_reply_with_prefix_variants(graph, store):
    graph.queue(ALICE, "inbox", [fixture("m08_inbound")])
    run_poll(graph, store, now=T("2026-07-01T09:05:00Z"))

    graph.queue(ALICE, "sentitems", [fixture("m08_forward_sent")])
    run_poll(graph, store, now=T("2026-07-01T09:35:00Z"))

    inbound = only(store.items(kind=KIND_INBOUND,
                               principal_id=pid(store, ALICE)))
    assert inbound.state == CLOSED_EVIDENCE, \
        "forward in-thread is closure evidence (conversationId match)"
    awaiting = only(store.items(kind=KIND_SENT_AWAITING))
    assert awaiting.counterparty_smtp == "accountant@numbers.example"

    graph.queue(ALICE, "inbox", [fixture("m08_antw_reply")])
    run_poll(graph, store, now=T("2026-07-01T10:35:00Z"))

    awaiting = only(store.items(kind=KIND_SENT_AWAITING))
    assert awaiting.state == CLOSED_EVIDENCE
    assert awaiting.state_reason == "counterparty_replied"
    # The counterparty's reply puts the ball back in Alice's court: a new
    # inbound item starts its own 24h clock.
    open_inbound = store.items(kind=KIND_INBOUND, item_states=(OPEN,))
    assert len(open_inbound) == 1
    assert open_inbound[0].counterparty_smtp == "accountant@numbers.example"


def test_subject_prefix_normalization():
    from donna.engine.rules import normalize_subject
    base = normalize_subject("Lease agreement")
    for variant in ("RE: Lease agreement", "FW: Lease agreement",
                    "Antw: Lease agreement", "Re: FW: Lease agreement",
                    "AW: lease AGREEMENT"):
        assert normalize_subject(variant) == base


# -- 09 delta 410 Gone: full resync without duplicates -------------------------

def test_delta_gone_resync_does_not_duplicate(graph, store):
    graph.queue(ERIN, "inbox", [fixture("m09_inbound")])
    run_poll(graph, store, now=T("2026-07-01T09:15:00Z"))
    item = only(store.items(principal_id=pid(store, ERIN)))

    # Cursor invalidated server-side; resync serves the same message again.
    graph.mark_cursor_gone(ERIN, "inbox")
    graph.queue(ERIN, "inbox", [fixture("m09_inbound")])
    run_poll(graph, store, now=T("2026-07-01T09:45:00Z"))

    items = store.items(principal_id=pid(store, ERIN))
    assert len(items) == 1, "resync must dedupe on internetMessageId"
    assert len(store.events_for(item.id)) == 1
    # After the 410 the engine restarted the delta without a cursor.
    resync_calls = [c for c in graph.delta_calls
                    if c[0] == ERIN and c[1] == "inbox"]
    assert resync_calls[-1][2] is None


# -- 10 VIP threshold: urgent fires once ----------------------------------------

def test_vip_urgent_fires_exactly_once(graph, store):
    from donna.jobs.urgent import run_urgent

    graph.queue(CEO, "inbox", [fixture("m10_vip_inbound")])
    run_poll(graph, store, now=T("2026-07-01T08:20:00Z"))

    item = only(store.items(principal_id=pid(store, CEO)))
    assert item.threshold_hours == 3, "VIP threshold overrides default"

    posts: list[dict] = []
    webhook = posts.append

    # Inside the 3h threshold: nothing fires.
    run_urgent(store, webhook, now=T("2026-07-01T10:00:00Z"))
    assert posts == []

    # Past threshold: fires once.
    run_urgent(store, webhook, now=T("2026-07-01T11:30:00Z"))
    assert len(posts) == 1

    # Next poll cycle: does not fire again.
    run_urgent(store, webhook, now=T("2026-07-01T11:40:00Z"))
    run_urgent(store, webhook, now=T("2026-07-01T12:40:00Z"))
    assert len(posts) == 1

    # Payload is counts and category labels only: no subject, no address.
    import json as _json
    payload = _json.dumps(posts[0])
    assert "Term sheet" not in payload
    assert "vip@bigclient.example" not in payload
    assert "Key Client" in payload
