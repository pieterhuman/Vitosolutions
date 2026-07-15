"""Poll job: delta-sync each monitored mailbox, upsert the ledger, run
the closure rules.

The entire decision path is here and in donna.engine.rules. Messages
from all mailboxes are processed in strict chronological order, so the
outcome of a poll never depends on which mailbox happened to sync first.

Every rule below maps 1:1 to the state machine in the build spec:
- inbound, principal in To, not excluded          -> inbound_unanswered
- outbound to an external counterparty            -> sent_awaiting_reply
- in-thread message in a monitored Sent Items     -> closes inbound items
- counterparty reply after our send               -> closes sent_awaiting
- auto-replies (RFC 3834 auto-replied)            -> ignored entirely
- anything ambiguous                              -> uncertain, never closed
"""
from __future__ import annotations

from datetime import datetime

from .. import states
from ..errors import CursorGone
from ..model import Message
from ..store import Store
from ..telemetry import get_logger, hash_text
from . import rules

log = get_logger(__name__)

FOLDERS = ("inbox", "sentitems")


def run_poll(graph, store: Store, now: datetime) -> dict:
    principals = store.active_principals()
    monitored = {p.upn: p for p in principals}
    internal_domains = {
        d.strip() for d in store.config_get("internal_domains").split(",")
        if d.strip()
    }
    exclusions = store.exclusions()
    default_inbound = int(store.config_get("threshold_inbound_hours"))
    default_sent = int(store.config_get("threshold_sent_awaiting_hours"))
    suggestion_threshold = int(
        store.config_get("suggestion_min_occurrences"))

    inbox: list[tuple] = []
    for p in principals:
        for folder in FOLDERS:
            for payload in _delta(graph, store, p, folder, now):
                msg = Message.from_graph(payload)
                sort_key = msg.sent if folder == "sentitems" else msg.received
                inbox.append((sort_key, p, folder, msg))
    inbox.sort(key=lambda t: t[0])

    created = closed = uncertain = 0
    for _, p, folder, msg in inbox:
        if folder == "sentitems":
            c1, c2 = _process_sent(store, p, msg, monitored,
                                   internal_domains, default_sent, now)
        else:
            c1, c2 = _process_inbound(store, p, msg, monitored, exclusions,
                                      default_inbound, now,
                                      suggestion_threshold)
        created += c1
        closed += c2

    store.record_job_run("poll", "success", now,
                         detail=f"messages={len(inbox)}")
    log.info("poll complete messages=%d created=%d closed=%d",
             len(inbox), created, closed)
    return {"messages": len(inbox), "created": created, "closed": closed}


def _delta(graph, store: Store, p, folder: str, now: datetime) -> list[dict]:
    cursor = store.get_cursor(p.id, folder)
    try:
        messages, new_link = graph.delta_messages(p.upn, folder, cursor)
    except CursorGone:
        # Server invalidated the cursor: full resync. The unique
        # constraint on (principal, kind, internetMessageId) makes the
        # replayed messages idempotent.
        log.info("delta cursor gone principal=%d folder=%s, resyncing",
                 p.id, folder)
        store.drop_cursor(p.id, folder)
        messages, new_link = graph.delta_messages(p.upn, folder, None)
    store.set_cursor(p.id, folder, new_link, now)
    return messages


def _active_items(store: Store, conversation_id: str, kind: str):
    return store.items(conversation_id=conversation_id, kind=kind,
                       item_states=states.ACTIVE_STATES)


def _has_active_item(store: Store, principal_id: int, kind: str,
                     conversation_id: str) -> bool:
    return any(i.principal_id == principal_id
               for i in _active_items(store, conversation_id, kind))


def _evidence(msg: Message) -> str:
    return (f"msgid_hash={hash_text(msg.internet_message_id)} "
            f"conv_hash={hash_text(msg.conversation_id)}")


def _process_sent(store: Store, p, msg: Message, monitored: dict,
                  internal_domains: set[str], default_sent: int,
                  now: datetime) -> tuple[int, int]:
    created = closed = 0
    # An auto-reply in Sent Items is the principal's own OOO responder:
    # it is not closure evidence and it does not start a waiting clock.
    if rules.is_auto_reply(msg):
        return 0, 0

    # Closure evidence for inbound items: any monitored principal sent a
    # message in the same conversation after the item's anchor.
    for item in _active_items(store, msg.conversation_id,
                              states.KIND_INBOUND):
        if msg.sent <= item.anchor_utc:
            continue
        if item.principal_id == p.id:
            reason = "replied_in_thread"
        else:
            reason = "handled_by_team"
        store.transition(item.id, states.CLOSED_EVIDENCE, reason=reason,
                         evidence=_evidence(msg), actor_upn=p.upn, now=now)
        closed += 1

    # Outbound to an external counterparty starts the waiting clock,
    # unless this thread already has an active waiting item.
    counterparty = rules.external_counterparty(msg, internal_domains)
    if counterparty and not _has_active_item(
            store, p.id, states.KIND_SENT_AWAITING, msg.conversation_id):
        item = store.create_item_if_new(
            principal_id=p.id, kind=states.KIND_SENT_AWAITING,
            conversation_id=msg.conversation_id,
            internet_message_id=msg.internet_message_id,
            subject=msg.subject, counterparty_smtp=counterparty[0],
            counterparty_name=counterparty[1], anchor_utc=msg.sent,
            threshold_hours=default_sent, now=now)
        if item:
            created += 1
    return created, closed


def _process_inbound(store: Store, p, msg: Message, monitored: dict,
                     exclusions, default_inbound: int, now: datetime,
                     suggestion_threshold: int) -> tuple[int, int]:
    created = closed = 0
    # Auto-replies close nothing, open nothing, and are never grounds
    # for uncertainty. Checked before the bulk filter because OOO
    # bounces often also carry X-Auto-Response-Suppress.
    if rules.is_auto_reply(msg):
        return 0, 0
    if rules.is_bulk(msg) or rules.matches_exclusion(msg, exclusions):
        return 0, 0

    # Closure for sent_awaiting: the counterparty answered after we sent.
    for item in _active_items(store, msg.conversation_id,
                              states.KIND_SENT_AWAITING):
        if msg.received <= item.anchor_utc:
            continue
        if msg.from_smtp == item.counterparty_smtp or store.alias_match(
                item.counterparty_smtp, msg.from_smtp):
            reason = ("counterparty_replied"
                     if msg.from_smtp == item.counterparty_smtp
                     else "replied_via_known_alias")
            store.transition(item.id, states.CLOSED_EVIDENCE, reason=reason,
                             evidence=_evidence(msg), actor_upn=None,
                             now=now)
            closed += 1
        elif msg.from_smtp not in monitored:
            if item.state != states.UNCERTAIN:
                store.transition(item.id, states.UNCERTAIN,
                                 reason="reply_from_different_address",
                                 evidence=_evidence(msg), actor_upn=None,
                                 now=now, signal_smtp=msg.from_smtp)
                store.record_suggestion_signal(
                    kind="recurring_alias",
                    counterparty_smtp=item.counterparty_smtp,
                    signal_smtp=msg.from_smtp, subject=item.subject,
                    min_occurrences=suggestion_threshold, now=now)

    # An in-thread reply from an address that is neither the original
    # counterparty nor a monitored team member makes the inbound item
    # ambiguous: uncertain, never closed — UNLESS a human has already
    # approved that address as a known alias of the counterparty, in
    # which case it's an ordinary deterministic closure.
    for item in _active_items(store, msg.conversation_id,
                              states.KIND_INBOUND):
        if msg.received <= item.anchor_utc:
            continue
        if msg.from_smtp == item.counterparty_smtp:
            continue
        if msg.from_smtp in monitored:
            continue
        if store.alias_match(item.counterparty_smtp, msg.from_smtp):
            store.transition(item.id, states.CLOSED_EVIDENCE,
                             reason="replied_via_known_alias",
                             evidence=_evidence(msg), actor_upn=None,
                             now=now)
            closed += 1
        elif item.state != states.UNCERTAIN:
            store.transition(item.id, states.UNCERTAIN,
                             reason="reply_from_unknown_sender",
                             evidence=_evidence(msg), actor_upn=None,
                             now=now, signal_smtp=msg.from_smtp)
            store.record_suggestion_signal(
                kind="recurring_alias", counterparty_smtp=item.counterparty_smtp,
                signal_smtp=msg.from_smtp, subject=item.subject,
                min_occurrences=suggestion_threshold, now=now)

    # Item creation: principal must be a To recipient (CC-only never
    # becomes an item), and one active item per conversation is enough.
    if not rules.addressed_in_to(msg, p.upn):
        return created, closed
    if _has_active_item(store, p.id, states.KIND_INBOUND,
                        msg.conversation_id):
        return created, closed
    vip = store.vip_match(msg.from_smtp)
    threshold = vip.threshold_hours if vip else default_inbound
    item = store.create_item_if_new(
        principal_id=p.id, kind=states.KIND_INBOUND,
        conversation_id=msg.conversation_id,
        internet_message_id=msg.internet_message_id,
        subject=msg.subject, counterparty_smtp=msg.from_smtp,
        counterparty_name=msg.from_name, anchor_utc=msg.received,
        threshold_hours=threshold, now=now)
    if item:
        created += 1
    return created, closed
