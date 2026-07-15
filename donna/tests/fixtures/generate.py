"""Generate the synthetic Microsoft Graph message fixtures.

Every fixture in this directory is synthetic. None of it comes from a real
tenant. Re-run this script only when adding scenarios; the emitted JSON is
checked in and IS the spec the engine must satisfy.

Usage: python tests/fixtures/generate.py
"""
from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).parent

TENANT = "familyoffice.example"

PRINCIPALS = {
    "ceo": ("ceo@familyoffice.example", "Nomsa Dlamini"),
    "alice": ("alice@familyoffice.example", "Alice Meyer"),
    "bob": ("bob@familyoffice.example", "Bob Naidoo"),
    "carol": ("carol@familyoffice.example", "Carol van Wyk"),
    "dan": ("dan@familyoffice.example", "Dan Botha"),
    "erin": ("erin@familyoffice.example", "Erin Sithole"),
    "frank": ("frank@familyoffice.example", "Frank Joubert"),
}

LAWYER = ("lawyer@sterlinglaw.example", "Sipho Khumalo")
BANKER = ("banker@privatebank.example", "Marie du Toit")
VENDOR = ("vendor@supplies.example", "Vendor Desk")
ACCOUNTANT = ("accountant@numbers.example", "Thabo Mokoena")
VIP = ("vip@bigclient.example", "Key Client")
UNKNOWN = ("unknown@elsewhere.example", "Somebody Else")
NEWSLETTER = ("news@updates.example", "Market Update")
SPAMLISTED = ("promo@spamlist.example", "Promo Desk")


def addr(pair):
    smtp, name = pair
    return {"emailAddress": {"address": smtp, "name": name}}


def msg(
    key: str,
    *,
    frm,
    to,
    conv: str,
    subject: str,
    when: str,
    cc=(),
    headers=None,
    received: str | None = None,
):
    """Build one Graph message resource. `when` is sentDateTime; received
    defaults to one minute later for inbound realism."""
    return {
        "id": f"AAMk-{key}",
        "internetMessageId": f"<{key}@{frm[0].split('@')[1]}>",
        "conversationId": f"AAQk-{conv}",
        "subject": subject,
        "sentDateTime": when,
        "receivedDateTime": received or when,
        "from": addr(frm),
        "sender": addr(frm),
        "toRecipients": [addr(t) for t in to],
        "ccRecipients": [addr(c) for c in cc],
        "internetMessageHeaders": [
            {"name": n, "value": v} for n, v in (headers or [])
        ],
        # Synthetic but shaped like a real Graph webLink, so tests can
        # exercise the digest's "open in Outlook" link rendering.
        "webLink": f"https://outlook.office.com/mail/deeplink/read/AAMk-{key}",
    }


FIXTURES: dict[str, dict] = {}


def fx(name, m):
    FIXTURES[name] = m


A = PRINCIPALS["alice"]
B = PRINCIPALS["bob"]
C = PRINCIPALS["carol"]
D = PRINCIPALS["dan"]
E = PRINCIPALS["erin"]
F = PRINCIPALS["frank"]
CEO = PRINCIPALS["ceo"]

# 01: plain reply in-thread closes an inbound item.
fx("m01_inbound", msg("m01a", frm=LAWYER, to=[A], conv="c01",
                      subject="Trust deed amendments",
                      when="2026-07-01T08:00:00Z"))
fx("m01_reply_sent", msg("m01b", frm=A, to=[LAWYER], conv="c01",
                         subject="RE: Trust deed amendments",
                         when="2026-07-01T09:15:00Z"))

# 02: reply by a DIFFERENT monitored team member -> closed_evidence,
# attribution "handled by team".
fx("m02_inbound", msg("m02a", frm=BANKER, to=[A], conv="c02",
                      subject="Q3 portfolio rebalance",
                      when="2026-07-01T08:10:00Z"))
fx("m02_team_reply", msg("m02b", frm=B, to=[BANKER], conv="c02",
                         subject="RE: Q3 portfolio rebalance",
                         when="2026-07-01T10:00:00Z"))

# 03: reply from an unknown/different sender address -> UNCERTAIN.
fx("m03_inbound", msg("m03a", frm=LAWYER, to=[A], conv="c03",
                      subject="Property transfer",
                      when="2026-07-01T08:20:00Z"))
fx("m03_unknown_reply", msg("m03b", frm=UNKNOWN, to=[A], conv="c03",
                            subject="RE: Property transfer",
                            when="2026-07-01T11:00:00Z"))

# 04: out-of-office auto-reply must not close anything and must not
# become an item itself.
#   04a: sent-awaiting-reply item survives the counterparty's OOO bounce.
fx("m04_outbound", msg("m04a", frm=A, to=[BANKER], conv="c04",
                       subject="Wire confirmation needed",
                       when="2026-07-01T08:30:00Z"))
fx("m04_ooo_reply", msg("m04b", frm=BANKER, to=[A], conv="c04",
                        subject="Automatic reply: Wire confirmation needed",
                        when="2026-07-01T08:31:00Z",
                        headers=[("Auto-Submitted", "auto-replied"),
                                 ("X-Auto-Response-Suppress", "All")]))
#   04b: the principal's OWN OOO auto-reply lands in their Sent Items with a
#   matching conversationId and later timestamp — it must NOT count as
#   closure evidence for the inbound item.
fx("m04_inbound_carol", msg("m04c", frm=VENDOR, to=[C], conv="c04b",
                            subject="Invoice 8841 overdue",
                            when="2026-07-01T08:35:00Z"))
fx("m04_carol_ooo_sent", msg("m04d", frm=C, to=[VENDOR], conv="c04b",
                             subject="Automatic reply: Invoice 8841 overdue",
                             when="2026-07-01T08:36:00Z",
                             headers=[("Auto-Submitted", "auto-replied")]))

# 05: newsletter / no-reply signals — excluded, never becomes an item.
fx("m05_list_unsubscribe", msg("m05a", frm=NEWSLETTER, to=[D], conv="c05a",
                               subject="Weekly market wrap",
                               when="2026-07-01T08:40:00Z",
                               headers=[("List-Unsubscribe",
                                         "<mailto:leave@updates.example>")]))
fx("m05_precedence_bulk", msg("m05b", frm=NEWSLETTER, to=[D], conv="c05b",
                              subject="Rates snapshot",
                              when="2026-07-01T08:41:00Z",
                              headers=[("Precedence", "bulk")]))
fx("m05_auto_generated", msg("m05c", frm=NEWSLETTER, to=[D], conv="c05c",
                             subject="Statement ready",
                             when="2026-07-01T08:42:00Z",
                             headers=[("Auto-Submitted", "auto-generated")]))
fx("m05_suppress", msg("m05d", frm=NEWSLETTER, to=[D], conv="c05d",
                       subject="Portal notification",
                       when="2026-07-01T08:43:00Z",
                       headers=[("X-Auto-Response-Suppress",
                                 "OOF, DR, RN, NRN")]))
fx("m05_exclusion_rule", msg("m05e", frm=SPAMLISTED, to=[D], conv="c05e",
                             subject="Special offer inside",
                             when="2026-07-01T08:44:00Z"))

# 06: CC-only — the CC'd principal never gets an item; the To principal does.
fx("m06_cc_only", msg("m06a", frm=LAWYER, to=[B], conv="c06",
                      subject="Estate planning notes", cc=[E],
                      when="2026-07-01T08:45:00Z"))

# 07: thread goes quiet — stays open forever until human action.
fx("m07_inbound", msg("m07a", frm=BANKER, to=[F], conv="c07",
                      subject="FX facility renewal",
                      when="2026-07-01T08:50:00Z"))

# 08: forwarded then replied, subject-prefix variants.
fx("m08_inbound", msg("m08a", frm=LAWYER, to=[A], conv="c08",
                      subject="Lease agreement",
                      when="2026-07-01T09:00:00Z"))
fx("m08_forward_sent", msg("m08b", frm=A, to=[ACCOUNTANT], conv="c08",
                           subject="FW: Lease agreement",
                           when="2026-07-01T09:30:00Z"))
fx("m08_antw_reply", msg("m08c", frm=ACCOUNTANT, to=[A], conv="c08",
                         subject="Antw: Lease agreement",
                         when="2026-07-01T10:30:00Z"))

# 09: delta cursor 410 Gone — full resync must not duplicate items.
fx("m09_inbound", msg("m09a", frm=BANKER, to=[E], conv="c09",
                      subject="KYC refresh documents",
                      when="2026-07-01T09:10:00Z"))

# 10: VIP sender crosses its shorter threshold — urgent fires once.
fx("m10_vip_inbound", msg("m10a", frm=VIP, to=[CEO], conv="c10",
                          subject="Term sheet decision needed",
                          when="2026-07-01T08:00:00Z"))


def main() -> None:
    out = HERE / "messages"
    out.mkdir(exist_ok=True)
    for name, payload in FIXTURES.items():
        (out / f"{name}.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    print(f"wrote {len(FIXTURES)} fixtures to {out}")


if __name__ == "__main__":
    main()
