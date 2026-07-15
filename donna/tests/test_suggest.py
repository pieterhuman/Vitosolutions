"""The suggestion engine: recurrence counting only, never a decider.

Every assertion here either proves (a) recurring ambiguity surfaces as
a reviewable suggestion without ever touching item state, or (b) once
a human approves the resulting known_alias row, future occurrences of
that exact pattern become an ordinary deterministic closure — the
'learning' cannot re-enter the decision path except as approved data.
"""
from __future__ import annotations

from donna import states
from donna.engine.poll import run_poll
from donna.jobs.suggest import run_suggest
from donna.states import KIND_INBOUND

from conftest import ALICE, T, pid

LAWYER = "lawyer@sterlinglaw.example"
ASSISTANT = "assistant@sterlinglaw.example"
UNRELATED = "someone-else@sterlinglaw.example"


def _thread(n: int) -> dict:
    return {
        "id": f"AAMk-thread{n}",
        "internetMessageId": f"<thread{n}@sterlinglaw.example>",
        "conversationId": f"AAQk-conv{n}",
        "subject": f"Matter #{n}",
        "sentDateTime": "2026-07-01T08:00:00Z",
        "receivedDateTime": "2026-07-01T08:00:00Z",
        "from": {"emailAddress": {"address": LAWYER, "name": "Lawyer"}},
        "toRecipients": [{"emailAddress": {"address": ALICE, "name": "Alice"}}],
    }


def _reply(n: int, from_addr: str, when: str) -> dict:
    return {
        "id": f"AAMk-reply{n}",
        "internetMessageId": f"<reply{n}@sterlinglaw.example>",
        "conversationId": f"AAQk-conv{n}",
        "subject": f"RE: Matter #{n}",
        "sentDateTime": when,
        "receivedDateTime": when,
        "from": {"emailAddress": {"address": from_addr, "name": "Assistant"}},
        "toRecipients": [{"emailAddress": {"address": ALICE, "name": "Alice"}}],
    }


def test_below_threshold_produces_no_pending_suggestion(graph, store):
    for n in range(1, 3):  # 2 occurrences, default threshold is 3
        graph.queue(ALICE, "inbox", [_thread(n)])
        graph.queue(ALICE, "inbox", [_reply(n, ASSISTANT, "2026-07-01T09:00:00Z")])
        run_poll(graph, store, now=T("2026-07-01T09:30:00Z"))

    run_suggest(store, now=T("2026-07-01T10:00:00Z"), report_dir="/tmp")
    assert store.pending_suggestions(min_occurrences=3) == []
    items = store.items(kind=KIND_INBOUND, principal_id=pid(store, ALICE))
    assert all(i.state == states.UNCERTAIN for i in items)


def test_recurrence_crosses_threshold_and_surfaces(graph, store, tmp_path):
    for n in range(1, 4):  # 3 occurrences of the SAME alias pattern
        graph.queue(ALICE, "inbox", [_thread(n)])
        graph.queue(ALICE, "inbox", [_reply(n, ASSISTANT, "2026-07-01T09:00:00Z")])
        run_poll(graph, store, now=T("2026-07-01T09:30:00Z"))

    result = run_suggest(store, now=T("2026-07-01T10:00:00Z"),
                         report_dir=str(tmp_path))
    assert result["pending"] == 1
    pending = store.pending_suggestions(min_occurrences=3)
    row = pending[0]
    assert row.counterparty_smtp == LAWYER
    assert row.signal_smtp == ASSISTANT
    assert row.occurrences == 3
    assert "known_alias" in row.suggested_sql

    report = next(tmp_path.glob("suggestions_*.html")).read_text()
    assert ASSISTANT in report and LAWYER in report
    assert "Matter #1" in report  # example subject shown for review


def test_unrelated_unknown_senders_do_not_pollute_the_pattern(graph, store):
    graph.queue(ALICE, "inbox", [_thread(1)])
    graph.queue(ALICE, "inbox", [_reply(1, ASSISTANT, "2026-07-01T09:00:00Z")])
    graph.queue(ALICE, "inbox", [_thread(2)])
    graph.queue(ALICE, "inbox", [_reply(2, UNRELATED, "2026-07-01T09:00:00Z")])
    run_poll(graph, store, now=T("2026-07-01T09:30:00Z"))

    run_suggest(store, now=T("2026-07-01T10:00:00Z"), report_dir="/tmp")
    # Two different signal_smtp values, one occurrence each: neither
    # pattern has actually recurred yet.
    assert store.pending_suggestions(min_occurrences=2) == []


def test_suggestion_engine_never_touches_item_state(graph, store):
    for n in range(1, 5):
        graph.queue(ALICE, "inbox", [_thread(n)])
        graph.queue(ALICE, "inbox", [_reply(n, ASSISTANT, "2026-07-01T09:00:00Z")])
        run_poll(graph, store, now=T("2026-07-01T09:30:00Z"))
    before = {i.id: i.state for i in store.items(principal_id=pid(store, ALICE))}

    run_suggest(store, now=T("2026-07-01T10:00:00Z"), report_dir="/tmp")

    after = {i.id: i.state for i in store.items(principal_id=pid(store, ALICE))}
    assert before == after, "suggest must be read-only with respect to open_item"


def test_dismissed_pattern_does_not_resurface(graph, store):
    for n in range(1, 4):
        graph.queue(ALICE, "inbox", [_thread(n)])
        graph.queue(ALICE, "inbox", [_reply(n, ASSISTANT, "2026-07-01T09:00:00Z")])
        run_poll(graph, store, now=T("2026-07-01T09:30:00Z"))
    run_suggest(store, now=T("2026-07-01T10:00:00Z"), report_dir="/tmp")

    # Human dismisses it (RUNBOOK-documented statement).
    import sqlalchemy as sa
    from donna.store import suggestion
    with store.engine.begin() as cx:
        cx.execute(suggestion.update().values(status="dismissed"))

    # The pattern recurs again — must not be re-surfaced or re-counted.
    graph.queue(ALICE, "inbox", [_thread(9)])
    graph.queue(ALICE, "inbox", [_reply(9, ASSISTANT, "2026-07-01T09:00:00Z")])
    run_poll(graph, store, now=T("2026-07-01T11:00:00Z"))
    run_suggest(store, now=T("2026-07-01T11:30:00Z"), report_dir="/tmp")
    assert store.pending_suggestions(min_occurrences=3) == []


def test_approved_alias_closes_future_occurrences_deterministically(graph, store):
    for n in range(1, 4):
        graph.queue(ALICE, "inbox", [_thread(n)])
        graph.queue(ALICE, "inbox", [_reply(n, ASSISTANT, "2026-07-01T09:00:00Z")])
        run_poll(graph, store, now=T("2026-07-01T09:30:00Z"))
    older = store.items(kind=KIND_INBOUND, principal_id=pid(store, ALICE))
    assert all(i.state == states.UNCERTAIN for i in older)

    # A human reviews the report and runs the suggested SQL, verbatim.
    store.add_known_alias(counterparty_smtp=LAWYER, alias_smtp=ASSISTANT,
                          label="lawyer's assistant")

    # The exact same pattern recurs — now a plain deterministic rule,
    # not a model decision.
    graph.queue(ALICE, "inbox", [_thread(4)])
    graph.queue(ALICE, "inbox", [_reply(4, ASSISTANT, "2026-07-01T09:00:00Z")])
    run_poll(graph, store, now=T("2026-07-01T09:45:00Z"))

    newest = [i for i in store.items(kind=KIND_INBOUND,
                                     principal_id=pid(store, ALICE))
             if i.subject == "Matter #4"][0]
    assert newest.state == states.CLOSED_EVIDENCE
    assert newest.state_reason == "replied_via_known_alias"

    # Older items already flagged uncertain are untouched retroactively
    # — approving an alias is not silent mass-reclassification.
    still = store.items(kind=KIND_INBOUND, principal_id=pid(store, ALICE),
                        item_states=(states.UNCERTAIN,))
    assert len(still) == 3
