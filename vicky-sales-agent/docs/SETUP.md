# Setup — connecting Apollo, Gmail, and Claude

## 1. Link the sending mailbox in Apollo (REQUIRED, currently missing)

As of 2026-08-30 the Apollo workspace has **no linked email account**, so
sequences cannot send. Fix:

1. Log into Apollo as the workspace owner.
2. **Settings → Mailboxes → Link mailbox → Google**.
3. Sign in as `vicky@getunicornclub.com` and grant send permissions.
4. Set it as the default mailbox and add Vicky's signature (include the
   Calendly/booking link if one exists — sequence copy references "my
   calendar link is in my signature").
5. Run `vicky doctor` — it finds the mailbox via the API and writes its ID
   into `config/apollo.yaml` (`send_email_account_id`).

Deliverability checklist while you're there: SPF, DKIM, and DMARC on
`getunicornclub.com` must pass (Google Admin → Apps → Gmail →
Authenticate email). The account is already warmed; the agent's warm-up
ramp still starts conservatively because Apollo is a new sending path.

## 2. Apollo API key

Apollo → **Settings → Integrations → API** → create a key (master key so
`emailer_campaigns` endpoints are allowed) → put it in `.env` as
`APOLLO_API_KEY`.

The API key drives the headless daily loop. Interactive work in a Claude
session can use the Apollo MCP connector instead — both hit the same
workspace objects (IDs in `config/apollo.yaml`).

## 3. Gmail app password (reply polling + approved sends)

1. `vicky@getunicornclub.com` must have 2-Step Verification enabled.
2. Google Account → **Security → 2-Step Verification → App passwords** →
   create one for "Mail".
3. Put it in `.env` as `GMAIL_APP_PASSWORD`.

This grants IMAP (reading replies) and SMTP (sending only human-approved
replies and .ics calendar invites). If Workspace policy blocks app
passwords, an admin can allow them for this one account, or swap
`agent/mailer.py` for the Gmail API with OAuth.

## 4. Anthropic API key

Create a key at console.anthropic.com → `.env` as `ANTHROPIC_API_KEY`.
Used for reply classification, reply drafting, and personalization
(`claude-opus-5` by default; change in `config/settings.yaml → llm.model`).

## 5. Calendar

Discovery-call invites are sent as `.ics` attachments from
`vicky@getunicornclub.com`, so accepted invites land on that account's
Google Calendar automatically — no extra Calendar API auth needed. Slots
are computed in `America/New_York` inside the windows configured under
`booking.windows_et`. By default (`booking.auto_book: false`) every
invite requires `vicky approvals approve <id>` first.

## 6. Verify

```bash
vicky doctor          # all checks must print OK
vicky sync-sequences  # should report all three sequences as existing
```

Then review the three sequences in the Apollo UI (they are inactive),
adjust copy if desired (edit `config/templates/sequences.yaml` and re-run
`sync-sequences` to keep git as the source of truth), and activate:

```bash
vicky activate primary
```
