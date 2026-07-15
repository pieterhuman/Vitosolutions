"""Signed mark-as-done link: the only path to closed_human."""
from __future__ import annotations

from donna import states
from donna.http_close import handle_close
from donna.states import KIND_INBOUND
from donna.tokens import TOKEN_TTL_SECONDS, make_token

from conftest import ALICE, BOB, T, pid

KEY = b"test-signing-key"
NOW = T("2026-07-01T12:00:00Z")
NOW_EPOCH = int(NOW.timestamp())
EXPIRY = NOW_EPOCH + TOKEN_TTL_SECONDS


def _make_item(store, upn=ALICE):
    return store.create_item_if_new(
        principal_id=pid(store, upn), kind=KIND_INBOUND,
        conversation_id="AAQk-cX", internet_message_id="<x@ext.example>",
        subject="Needs attention", counterparty_smtp="who@ext.example",
        counterparty_name="Who", anchor_utc=T("2026-07-01T08:00:00Z"),
        threshold_hours=24, now=T("2026-07-01T08:30:00Z"))


def test_valid_token_closes_human(store):
    item = _make_item(store)
    token = make_token(item.id, item.principal_id, EXPIRY, KEY)
    status, body = handle_close(store, token, KEY, now=NOW)
    assert status == 200
    fresh = store.get_item(item.id)
    assert fresh.state == states.CLOSED_HUMAN
    assert fresh.closed_by_upn == ALICE
    events = store.events_for(item.id)
    assert events[-1].to_state == states.CLOSED_HUMAN


def test_token_is_single_use(store):
    item = _make_item(store)
    token = make_token(item.id, item.principal_id, EXPIRY, KEY)
    assert handle_close(store, token, KEY, now=NOW)[0] == 200
    status, _ = handle_close(store, token, KEY, now=NOW)
    assert status == 409, "replay must be rejected"


def test_expired_token_rejected(store):
    item = _make_item(store)
    token = make_token(item.id, item.principal_id, NOW_EPOCH - 10, KEY)
    status, _ = handle_close(store, token, KEY, now=NOW)
    assert status == 403
    assert store.get_item(item.id).state == states.OPEN


def test_wrong_principal_rejected(store):
    item = _make_item(store, upn=ALICE)
    token = make_token(item.id, pid(store, BOB), EXPIRY, KEY)
    status, _ = handle_close(store, token, KEY, now=NOW)
    assert status == 403, "token principal must own the item"
    assert store.get_item(item.id).state == states.OPEN


def test_tampered_token_rejected(store):
    item = _make_item(store)
    token = make_token(item.id, item.principal_id, EXPIRY, KEY)
    bad = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
    status, _ = handle_close(store, bad, KEY, now=NOW)
    assert status == 400
    assert store.get_item(item.id).state == states.OPEN


def test_uncertain_item_can_be_closed_by_human(store):
    item = _make_item(store)
    store.transition(item.id, states.UNCERTAIN, reason="test",
                     evidence="", actor_upn=None, now=NOW)
    token = make_token(item.id, item.principal_id, EXPIRY, KEY)
    status, _ = handle_close(store, token, KEY, now=NOW)
    assert status == 200
    assert store.get_item(item.id).state == states.CLOSED_HUMAN
