# Vicky — AI Sales Agent for Unicorn Club

An autonomous outbound sales system that runs team-augmentation sales for
senior **data & AI engineers**, targeting US Eastern Time companies with
50–500 employees. The agent operates as **Vicky Steyn, BDM**
(`vicky@getunicornclub.com`) and drives prospects from cold outreach to a
**2–4 week paid pilot**. Goal: 5 active data/AI roles.

## How it works

```
┌─────────────────────────────  daily loop  ─────────────────────────────┐
│                                                                        │
│  preflight ──> replies ──> nurture ──> leadgen ──> enroll ──> report   │
│  (guardrails)  (Gmail +    (snoozes,   (Apollo     (Apollo    (metrics │
│                 Claude      re-engage,  search +    sequences  + email │
│                 classify)   referrals)  score)      A/B/C)     digest) │
└────────────────────────────────────────────────────────────────────────┘
         │                                                    │
         ▼                                                    ▼
   approval queue  <────── humans approve ──────>   Apollo tasks (LinkedIn,
   (reply drafts, calendar invites, pilots)         calls) for the human
```

- **Apollo.io** owns sequence sending (from the linked
  `vicky@getunicornclub.com` Gmail), lead search, enrichment, and
  LinkedIn/call task management.
- **Gmail (IMAP/SMTP, app password)** is polled for replies; approved 1:1
  responses and calendar invites (.ics) go out through it.
- **Claude** (`claude-opus-5`) classifies replies and drafts responses,
  grounded in pre-approved scripts.
- **SQLite** (`data/vicky.db`) holds the pipeline, approval queue, and a
  full audit log — every action is recorded with a timestamped reason.

## Pipeline stages

`new → sequenced → replied → discovery_booked → profiles_sent →
pilot_proposed → pilot_active → expanded / closed_lost`
(plus `nurture` and `unsubscribed`).

## The three Apollo sequences

Created and version-controlled in
[`config/templates/sequences.yaml`](config/templates/sequences.yaml);
live IDs in [`config/apollo.yaml`](config/apollo.yaml). All were created
**inactive** — nothing sends until you review and activate.

| Key | Name | Steps |
|---|---|---|
| `primary` | Vicky A — Data/AI Capacity (US ET 50-500) | D0 cold email → D1 LinkedIn connect → D2 value follow-up → D4 profile view → D6 direct ask + scarcity → D11 breakup |
| `warm` | Vicky B — Warm / Referral (Data-AI) | D0 intro follow-up → D3 profiles nudge → D5 LinkedIn message |
| `pilot` | Vicky C — Pilot Conversion (Replied/Interested) | D0 profiles + pilot email (**human-reviewed**) → D3 follow-up → D6 call task |

## Quick start

```bash
cd vicky-sales-agent
pip install -e .                 # installs the `vicky` command
cp .env.example .env             # fill in the three keys (see docs/SETUP.md)
vicky init                       # create the local database
vicky doctor                     # verifies Apollo, Gmail, sequences, mailbox
vicky sync-sequences             # verify/create the Apollo sequences
# review copy in Apollo UI, then:
vicky activate primary           # explicit confirmation required
vicky daily                      # run the full loop (idempotent)
```

Schedule `vicky daily` on weekday mornings (ET) via cron:

```
0 13 * * 1-5 cd /path/to/vicky-sales-agent && /usr/bin/python -m agent daily >> reports/cron.log 2>&1
```

(13:00 UTC = 8–9 am ET.) Running it a second time in a day is safe — all
budgets are enforced per-day.

## Human control surface

```bash
vicky pipeline                   # counts by stage
vicky leads --stage replied      # list leads
vicky approvals list             # what's waiting on you
vicky approvals show 12          # inspect a draft
vicky approvals approve 12       # send it
vicky approvals reject 12 --reason "wrong angle"
vicky note cto@acme.com "met at conf, knows our work"
vicky dnc cto@acme.com           # immediate do-not-contact
vicky pause / vicky resume       # kill switch for all outbound
vicky report --days 7            # weekly metrics
```

## Guardrails (always on)

- **Daily caps**: 40 emails/day (configurable 30–50), 50 LinkedIn
  touches/day, with a warm-up ramp (15/day, +5 per weekday).
- **Unsubscribes** are honored immediately: DNC flag + removal from the
  Apollo sequence, no approval needed, logged.
- **Human approval required** for: replies to interested/meeting/objection
  responses, all calendar invites, pilot proposals, and sequence
  activation.
- **Deliverability circuit breaker**: auto-pauses all outbound if bounce
  rate >3% or spam-block rate >1% over the trailing window.
- **Spam-language linter** on all sequence copy (enforced in tests).
- **Suppression list** by domain; weekdays-only sending; every action
  audit-logged with reasoning.

## Repo layout

```
agent/            the Python package (one module per workflow)
config/settings.yaml        ICP, volumes, scoring, guardrails
config/apollo.yaml          live Apollo IDs (schedule, mailbox, sequences)
config/templates/           sequence copy, objection scripts, LLM prompts
docs/SETUP.md               connecting Apollo + Gmail (auth)
docs/OPERATIONS.md          daily ops: what's autonomous vs. human
tests/                      unit tests (pure logic, no network)
```

## Status / known setup gaps

- `vicky@getunicornclub.com` is **not yet linked as a mailbox in
  Apollo** — sequences cannot send until that's done (2 minutes in the
  Apollo UI; see docs/SETUP.md). `vicky doctor` detects and stores the
  mailbox ID automatically once linked.
- All three sequences exist in Apollo and are **inactive** pending your
  copy review.
