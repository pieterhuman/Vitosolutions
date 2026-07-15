# CONFIG — tunables (no redeploy needed)

All keys live in the `config` table (`key`, `value`). Missing keys fall
back to the defaults below (`donna/src/donna/store.py:CONFIG_DEFAULTS`).

| key | default | meaning |
|---|---|---|
| `threshold_inbound_hours` | `24` | Hours before an unanswered inbound item counts as overdue |
| `threshold_sent_awaiting_hours` | `72` | Hours before a sent-awaiting-reply item counts as overdue |
| `vip_default_threshold_hours` | `3` | Default threshold for new `vip_contact` rows |
| `quiet_hours_utc` | `18:00-04:00` | UTC window in which urgent Teams alerts are held (they fire after the window; nothing is lost) |
| `teams_webhook_url` | *(empty)* | Teams Workflows webhook URL; if empty, the Key Vault secret `donna-teams-webhook-url` is used |
| `service_mailbox_upn` | `donna@familyoffice.example` | The ONLY mailbox Donna ever sends from |
| `internal_domains` | `familyoffice.example` | Comma-separated tenant domains; recipients outside these are "external counterparties" |
| `close_base_url` | `https://localhost/api` | Base URL for signed mark-as-done links (set to the Bicep output `closeEndpointBase`) |
| `heartbeat_window_hours` | `11` | Heartbeat alerts if no successful digest within this window |
| `digest_dry_run` | `0` | `1` renders digests to local files instead of sending |
| `dry_run_output_dir` | `out` | Where dry-run digests are written |

Update with plain SQL, e.g.:

```sql
UPDATE config SET value = '48' WHERE key = 'threshold_inbound_hours';
INSERT INTO config (key, value) VALUES ('threshold_inbound_hours', '48');  -- if absent
```

Thresholds apply to items created after the change; existing items keep
the threshold stamped at creation (deliberate: no retroactive urgency).
