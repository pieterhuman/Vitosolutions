# Donna Minimal

Set-and-forget mailbox follow-up for a 7-person family office on
Microsoft 365. Donna watches 7 mailboxes via Microsoft Graph delta
queries, keeps a ledger of items needing attention, and emails each
person a briefing twice daily. **It never guesses**: whether an email is
answered is decided only by deterministic rules — no LLM, no scoring, no
"probably" anywhere in the decision path.

## Hard guarantees

- **No LLM in the decision path.** The state machine in
  `src/donna/engine/` is the entire product.
- **No client secrets.** Managed Identity + federated credential on a
  single-tenant app registration (OPERATOR.md §3).
- **Everything runs in the client's tenant.** The only external call is
  a Teams Workflows webhook carrying counts and category labels only.
- **Telemetry never contains subjects, bodies, or addresses.** A
  log-record factory (`src/donna/telemetry.py`) scrubs at the logging
  boundary; tests enforce it.
- **Read-mostly.** Graph permissions: Mail.Read, Mail.Send,
  Calendars.Read, Tasks.Read.All, User.Read.All — scoped to the
  monitored mailboxes by an Exchange Application Access Policy. The only
  write is `sendMail` from the dedicated service mailbox.
- **Append-only ledger.** Every state change writes an `ItemEvent` in
  the same transaction; `ItemEvent` rejects UPDATE/DELETE at both the
  app layer and (in production) a Postgres trigger.

## The state machine

| Trigger | Result |
|---|---|
| Inbound mail, principal in **To** (not CC-only), no exclusion match | `inbound_unanswered` item, 24h threshold (or the VIP threshold) |
| Outbound mail to an external counterparty | `sent_awaiting_reply` item, 72h threshold |
| A monitored Sent Items message in the same conversation, later | closes inbound item (`replied_in_thread` / `handled_by_team`) |
| Counterparty reply after our send | closes `sent_awaiting_reply` |
| Auto-replies (RFC 3834 `Auto-Submitted: auto-replied`) | ignored: close nothing, open nothing |
| Bulk mail (List-Unsubscribe, Precedence bulk/list/junk, auto-generated, X-Auto-Response-Suppress) | never becomes an item |
| Reply from an unknown address | item goes `uncertain` — surfaced in briefings, never auto-closed |
| Thread goes quiet | item stays open forever until a human acts |
| Human clicks the signed mark-as-done link | `closed_human` (the only path to it) |

## The briefing

Each person's twice-daily email carries: overdue inbound (oldest first),
sent-awaiting-reply, uncertain items, today's calendar, To Do tasks due
today and overdue, and **overdue Planner tasks** (title, plan, due date).
Planner is additive — if the Planner read fails, the briefing still
sends without that section. The CEO's rollup shows per-person counts
only (inbound / awaiting / uncertain / tasks overdue), never subjects,
senders, or task titles.

## Layout

```
src/donna/            engine, ledger, jobs (poll / digest / urgent / heartbeat)
function_app.py       Azure Functions entry points (timers UTC + POST /api/close/{token})
tests/                the fixture suite — 22 synthetic Graph messages; the suite is the spec
infra/                Bicep (Function App, Postgres Burstable, Key Vault, alert rule) + SQL trigger
OPERATOR.md           Entra app registration, admin consent, Application Access Policy
RUNBOOK.md            onboarding, VIP/exclusion edits, heartbeat alert, quarterly re-verification
CONFIG.md             DB-backed tunables — nothing requires a redeploy
```

## Development

All development runs against synthetic fixtures — no real tenant data,
ever (see `tests/fixtures/generate.py`).

```bash
cd donna
pip install -r requirements-dev.txt
python -m pytest                     # the fixture suite is the spec
python scripts/dry_run_local.py      # renders all 7 digests into ./out/
```
