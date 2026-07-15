"""Synthetic dataset for the local Docker demo.

Every timestamp is computed relative to `now` at container start, so the
demo looks current whenever a client opens it — not pinned to whatever
date this file was written on. All addresses, names, and mail content
are synthetic; no real tenant data is used anywhere in this repo
(hard constraint 6).
"""
from __future__ import annotations

from datetime import datetime, timedelta

CEO = "ceo@familyoffice.example"
ALICE = "alice@familyoffice.example"
BOB = "bob@familyoffice.example"
CAROL = "carol@familyoffice.example"
DAN = "dan@familyoffice.example"
ERIN = "erin@familyoffice.example"
FRANK = "frank@familyoffice.example"

PRINCIPALS = [
    (CEO, "Nomsa Dlamini", True),
    (ALICE, "Alice Meyer", False),
    (BOB, "Bob Naidoo", False),
    (CAROL, "Carol van Wyk", False),
    (DAN, "Dan Botha", False),
    (ERIN, "Erin Sithole", False),
    (FRANK, "Frank Joubert", False),
]

LAWYER = ("lawyer@sterlinglaw.example", "Sipho Khumalo")
BANKER = ("banker@privatebank.example", "Marie du Toit")
ACCOUNTANT = ("accountant@numbers.example", "Thabo Mokoena")
VENDOR = ("vendor@supplies.example", "Vendor Desk")
VIP = ("vip@bigclient.example", "Key Client — Board Chair")
NEWSLETTER = ("news@updates.example", "Market Update")
SPAMLISTED = ("promo@spamlist.example", "Promo Desk")
ADVISOR = ("consultant@advisory.example", "Advisory Partners")
ADVISOR_ASSISTANT = ("assistant@advisory.example", "Advisory Partners — EA")

_seq = 0


def _id() -> str:
    global _seq
    _seq += 1
    return f"demo-{_seq:03d}"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _addr(pair):
    smtp, name = pair
    return {"emailAddress": {"address": smtp, "name": name}}


def _msg(*, frm, to, conv: str, subject: str, sent: datetime,
         cc=(), headers=None, received: datetime | None = None) -> dict:
    return {
        "id": f"AAMk-{_id()}",
        "internetMessageId": f"<{_id()}@{frm[0].split('@')[1]}>",
        "conversationId": f"AAQk-{conv}",
        "subject": subject,
        "sentDateTime": _iso(sent),
        "receivedDateTime": _iso(received or sent),
        "from": _addr(frm),
        "toRecipients": [_addr(t) for t in to],
        "ccRecipients": [_addr(c) for c in cc],
        "internetMessageHeaders": [
            {"name": n, "value": v} for n, v in (headers or [])
        ],
    }


def _principal_pair(upn: str, name: str):
    return (upn, name)


def seed_principals_and_config(store) -> None:
    if store.active_principals():
        return  # already seeded — demo is idempotent across restarts
    for upn, name, is_ceo in PRINCIPALS:
        store.add_principal(upn, name, is_ceo=is_ceo)
    store.add_vip(smtp=VIP[0], label="Key Client (Board Chair)",
                  threshold_hours=3)
    store.add_exclusion("domain", "spamlist.example")
    store.config_set("internal_domains", "familyoffice.example")
    store.config_set("service_mailbox_upn", "donna@familyoffice.example")
    store.config_set("close_base_url", "http://localhost:8080")
    store.config_set("suggestion_min_occurrences", "3")


def build_graph(graph, now: datetime) -> None:
    """Queue a realistic day's worth of synthetic mail, relative to now."""
    h = lambda hrs: now - timedelta(hours=hrs)  # noqa: E731

    # -- Alice: an overdue inbound, a team-handled item, an overdue
    #    sent-awaiting, and two legs of a recurring-alias pattern.
    graph.queue(ALICE, "inbox", [
        _msg(frm=LAWYER, to=[(ALICE, "Alice Meyer")], conv="a1",
             subject="Trust deed amendments", sent=h(26)),
    ])
    graph.queue(ALICE, "inbox", [
        _msg(frm=BANKER, to=[(ALICE, "Alice Meyer")], conv="a2",
             subject="Q3 portfolio rebalance", sent=h(30)),
    ])
    graph.queue(BOB, "sentitems", [
        _msg(frm=(BOB, "Bob Naidoo"), to=[BANKER], conv="a2",
             subject="RE: Q3 portfolio rebalance", sent=h(20)),
    ])
    graph.queue(ALICE, "sentitems", [
        _msg(frm=(ALICE, "Alice Meyer"), to=[ACCOUNTANT], conv="a3",
             subject="Signed engagement letter", sent=h(80)),
    ])
    graph.queue(ALICE, "inbox", [
        _msg(frm=ADVISOR, to=[(ALICE, "Alice Meyer")], conv="a4",
             subject="Governance review — Q3", sent=h(48)),
    ])
    graph.queue(ALICE, "inbox", [
        _msg(frm=ADVISOR_ASSISTANT, to=[(ALICE, "Alice Meyer")], conv="a4",
             subject="RE: Governance review — Q3", sent=h(44)),
    ])
    graph.queue(ALICE, "inbox", [
        _msg(frm=ADVISOR, to=[(ALICE, "Alice Meyer")], conv="a5",
             subject="Governance review — follow-up docs", sent=h(36)),
    ])
    graph.queue(ALICE, "inbox", [
        _msg(frm=ADVISOR_ASSISTANT, to=[(ALICE, "Alice Meyer")], conv="a5",
             subject="RE: Governance review — follow-up docs", sent=h(33)),
    ])

    # -- Bob: a third leg of the recurring-alias pattern (crosses the
    #    suggestion threshold of 3), plus a CC-only mail he must NOT get
    #    an item for (Carol, the To recipient, gets it instead).
    graph.queue(BOB, "inbox", [
        _msg(frm=ADVISOR, to=[(BOB, "Bob Naidoo")], conv="a6",
             subject="Governance review — board pack", sent=h(20)),
    ])
    graph.queue(BOB, "inbox", [
        _msg(frm=ADVISOR_ASSISTANT, to=[(BOB, "Bob Naidoo")], conv="a6",
             subject="RE: Governance review — board pack", sent=h(18)),
    ])
    cc_only = _msg(frm=LAWYER, to=[(CAROL, "Carol van Wyk")],
                   cc=[(BOB, "Bob Naidoo")], conv="a7",
                   subject="Estate planning notes", sent=h(28))
    graph.queue(CAROL, "inbox", [cc_only])
    graph.queue(BOB, "inbox", [cc_only])

    # -- Carol: an out-of-office auto-reply that must NOT close her
    #    overdue item, plus a thread gone quiet for over a week.
    graph.queue(CAROL, "inbox", [
        _msg(frm=VENDOR, to=[(CAROL, "Carol van Wyk")], conv="c1",
             subject="Invoice 8841 overdue", sent=h(27)),
    ])
    graph.queue(CAROL, "sentitems", [
        _msg(frm=(CAROL, "Carol van Wyk"), to=[VENDOR], conv="c1",
             subject="Automatic reply: Invoice 8841 overdue", sent=h(26.9),
             headers=[("Auto-Submitted", "auto-replied")]),
    ])
    graph.queue(CAROL, "inbox", [
        _msg(frm=BANKER, to=[(CAROL, "Carol van Wyk")], conv="c2",
             subject="FX facility renewal", sent=h(24 * 9)),
    ])

    # -- Dan: bulk mail that must never become an item at all.
    graph.queue(DAN, "inbox", [
        _msg(frm=NEWSLETTER, to=[(DAN, "Dan Botha")], conv="d1",
             subject="Weekly market wrap", sent=h(10),
             headers=[("List-Unsubscribe", "<mailto:leave@updates.example>")]),
        _msg(frm=SPAMLISTED, to=[(DAN, "Dan Botha")], conv="d2",
             subject="Special offer inside", sent=h(9)),
    ])

    # -- Erin: a ONE-OFF uncertain item — a different (unrelated) unknown
    #    address replying once. This deliberately does NOT recur, so it
    #    stays flagged in her digest without ever crossing the suggestion
    #    engine's review threshold — proof that recurrence, not mere
    #    ambiguity, is what the suggestion report reacts to. Plus an
    #    overdue Planner task.
    graph.queue(ERIN, "inbox", [
        _msg(frm=BANKER, to=[(ERIN, "Erin Sithole")], conv="e1",
             subject="KYC refresh documents", sent=h(29)),
    ])
    graph.queue(ERIN, "inbox", [
        _msg(frm=("kyc-team@privatebank.example", "KYC Team"),
             to=[(ERIN, "Erin Sithole")], conv="e1",
             subject="RE: KYC refresh documents", sent=h(25)),
    ])

    # -- Frank: a VIP inbound past its 3h threshold — fires the urgent
    #    Teams alert.
    graph.queue(FRANK, "inbox", [
        _msg(frm=VIP, to=[(FRANK, "Frank Joubert")], conv="f1",
             subject="Term sheet — decision needed today", sent=h(5)),
    ])

    # -- CEO: an overdue inbound of her own, for the rollup to roll up.
    graph.queue(CEO, "inbox", [
        _msg(frm=("chair@familyfoundation.example", "Foundation Chair"),
             to=[(CEO, "Nomsa Dlamini")], conv="g1",
             subject="Q3 board pack sign-off", sent=h(31)),
    ])

    # -- Calendar + To Do + Planner, for the sections beyond mail.
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    graph.calendar[ALICE] = [
        {"start": "09:00", "subject": "Trustee call"},
        {"start": "14:00", "subject": "Lease renewal walkthrough"},
    ]
    graph.calendar[CEO] = [
        {"start": "08:00", "subject": "Investment committee"},
        {"start": "13:00", "subject": "Lunch — Key Client chair"},
    ]
    graph.tasks[ALICE] = [{"title": "Sign off Q2 management accounts"}]
    graph.tasks[CEO] = [{"title": "Approve term sheet"}]
    graph.planner[CAROL] = [
        {"title": "File FICA documentation", "plan": "Compliance",
         "due": (now - timedelta(days=3)).strftime("%Y-%m-%d")},
    ]
    graph.planner[ERIN] = [
        {"title": "Renew KYC pack template", "plan": "Compliance",
         "due": (now - timedelta(days=1)).strftime("%Y-%m-%d")},
    ]
