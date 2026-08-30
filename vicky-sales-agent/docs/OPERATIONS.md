# Daily operating instructions

## What the agent does autonomously

Every weekday run of `vicky daily`:

1. **Preflight** — refuses to run if paused, weekend, mailbox unlinked, or
   the deliverability breaker tripped (bounce >3% / spam-block >1%).
2. **Replies** — polls the Gmail inbox, classifies every new reply:
   - `unsubscribe` → immediate DNC + removed from the Apollo sequence.
   - `out_of_office` → ignored (Apollo pauses OOO contacts itself).
   - `not_now` → snoozed 6 weeks into the nurture pool. No send.
   - everything else → drafts a grounded reply and **queues it for your
     approval**. Nothing is auto-sent.
3. **Nurture** — wakes expired snoozes into the warm sequence, moves
   35-day no-reply leads to nurture, queues referral asks after positive
   interactions (also approval-gated).
4. **Lead sourcing** — Apollo people search against the ICP (titles ×
   50–500 employees × US), enriches signals (data/AI job postings,
   funding, tech keywords), dedupes, scores 0–100.
5. **Enrollment** — top-scoring leads (≥60) into the primary sequence,
   respecting the daily budget and warm-up ramp. Apollo then sends the
   emails on the "Normal Business Hours" schedule **in each contact's
   timezone**.
6. **LinkedIn/call tasks** — pulls today's open Apollo tasks (capped at
   50/day) and lists them in the run output and Apollo's Tasks view.
7. **Report** — writes `reports/summary-<date>.md`; optionally emails it
   (`reporting.send_email_summary: true`).

## What needs a human (you)

| When | What | Command |
|---|---|---|
| Daily, ~10 min | Approve/reject queued reply drafts, invites, pilot proposals | `vicky approvals list / show / approve / reject` |
| Daily, ~20 min | Execute LinkedIn tasks (connect requests, messages, profile views) from Apollo Tasks — Apollo can't automate LinkedIn | Apollo UI → Tasks |
| When a positive reply asks for profiles | Attach 2–3 real candidate profiles to the Sequence C step-1 draft (it's a manual_email step held for review) | Apollo UI / `vicky approvals` |
| After a discovery call | Update the stage and push the pilot | `vicky note`, stage moves happen on approval of the pilot proposal |
| Once | Review sequence copy and activate | `vicky activate primary` |
| Anytime | Kill switch | `vicky pause` |

## Weekly review (Mondays, ~15 min)

```bash
vicky report --days 7
vicky pipeline
```

Look at: reply rate (target ≥5% cold), positive-reply rate, meetings
booked, pilots proposed/active vs. the 5-role goal, bounce/spam rates in
Apollo's sequence analytics. If reply rate <2% after ~150 sends, change
the step-1 email in `config/templates/sequences.yaml`, run
`vicky sync-sequences`, and consider tightening the ICP.

## Volume & pacing rules

- Email cap 40/day (raise toward 50 in `settings.yaml` only after two
  clean weeks). Warm-up starts at 15/day, +5 per weekday.
- LinkedIn 50 touches/day max — stay under LinkedIn's radar.
- Keep the account pool at 80–150 high-priority accounts
  (`volumes.pipeline_target_accounts`); leadgen wraps its search cursor
  automatically.
- Re-engagement: no-replies get a fresh angle via the warm sequence after
  ~5 weeks; "not now" after 6 weeks.

## Incident playbook

- **Bounce/spam spike**: the breaker auto-pauses and logs why. Check
  Apollo analytics, fix (list quality? copy?), then `vicky resume`.
- **Angry reply / legal threat**: classifier marks it `requires_human`;
  reject the draft, handle personally, `vicky dnc <email>`.
- **Apollo/Gmail outage**: the loop logs errors and continues other
  steps; re-run later — everything is idempotent.
- **Wrong person enrolled**: `vicky dnc <email>` + remove them from the
  sequence in Apollo UI.

## Running from a Claude session instead of cron

Everything the daily loop does headlessly can also be driven through the
Apollo connector in a Claude Code session (the object IDs in
`config/apollo.yaml` are the shared source of truth). Useful for one-off
work: hand-picking accounts, bespoke research on a hot reply, or editing
sequences conversationally.
