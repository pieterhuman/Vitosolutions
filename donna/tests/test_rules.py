"""Unit coverage for the deterministic classification rules."""
from __future__ import annotations

from donna.engine import rules
from donna.model import Message

from conftest import fixture


def M(name: str) -> Message:
    return Message.from_graph(fixture(name))


def test_auto_reply_detection():
    assert rules.is_auto_reply(M("m04_ooo_reply"))
    assert rules.is_auto_reply(M("m04_carol_ooo_sent"))
    assert not rules.is_auto_reply(M("m01_reply_sent"))
    assert not rules.is_auto_reply(M("m01_inbound"))


def test_bulk_detection_each_signal():
    for name in ("m05_list_unsubscribe", "m05_precedence_bulk",
                 "m05_auto_generated", "m05_suppress"):
        assert rules.is_bulk(M(name)), name
    assert not rules.is_bulk(M("m01_inbound"))


def test_exclusion_rules(store):
    excl = store.exclusions()
    assert rules.matches_exclusion(M("m05_exclusion_rule"), excl)
    assert not rules.matches_exclusion(M("m01_inbound"), excl)


def test_to_vs_cc_membership():
    m = M("m06_cc_only")
    assert rules.addressed_in_to(m, "bob@familyoffice.example")
    assert not rules.addressed_in_to(m, "erin@familyoffice.example")


def test_external_counterparty_resolution():
    m = M("m04_outbound")  # alice -> banker
    smtp, _name = rules.external_counterparty(
        m, internal_domains={"familyoffice.example"})
    assert smtp == "banker@privatebank.example"
    # A purely internal mail has no external counterparty.
    internal = Message.from_graph({
        "id": "x", "internetMessageId": "<i@familyoffice.example>",
        "conversationId": "c", "subject": "internal",
        "sentDateTime": "2026-07-01T08:00:00Z",
        "receivedDateTime": "2026-07-01T08:00:00Z",
        "from": {"emailAddress": {"address": "alice@familyoffice.example",
                                  "name": "Alice"}},
        "toRecipients": [{"emailAddress": {
            "address": "bob@familyoffice.example", "name": "Bob"}}],
    })
    assert rules.external_counterparty(
        internal, internal_domains={"familyoffice.example"}) is None
