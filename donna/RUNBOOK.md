# RUNBOOK.md — day-2 operations

Donna is set-and-forget: no redeploy is needed for any operation on this
page. Everything is a row in the database or a portal click.

## Onboard a person

1. Add the mailbox to the Exchange group (propagation can exceed an hour):
   ```powershell
   Add-DistributionGroupMember -Identity "sg-donna-monitored" -Member "new@<tenant-domain>"
   ```
2. Insert the principal:
   ```sql
   INSERT INTO principal (upn, display_name, is_ceo, active)
   VALUES ('new@<tenant-domain>', 'New Person', false, true);
   ```
3. Done. The next poll (≤30 min after Exchange propagation) starts a
   fresh delta sync for both folders. History before onboarding is not
   backfilled — the first delta establishes the baseline.

## Offboard a person

1. ```sql
   UPDATE principal SET active = false WHERE upn = 'left@<tenant-domain>';
   ```
   Polling and digests stop immediately. Their ledger history stays
   (ItemEvent is append-only; nothing is ever deleted).
2. Remove them from `sg-donna-monitored` so Graph access is revoked too:
   ```powershell
   Remove-DistributionGroupMember -Identity "sg-donna-monitored" -Member "left@<tenant-domain>"
   ```

## Edit VIP rules

```sql
-- by exact address (3h threshold)
INSERT INTO vip_contact (smtp, domain_pattern, label, threshold_hours)
VALUES ('chair@bigclient.example', NULL, 'Key Client', 3);

-- or by whole domain
INSERT INTO vip_contact (smtp, domain_pattern, label, threshold_hours)
VALUES (NULL, 'bigclient.example', 'Key Client', 3);

DELETE FROM vip_contact WHERE label = 'Key Client';  -- remove
```
Takes effect at the next poll for new items. Existing items keep the
threshold they were created with.

## Edit exclusion rules

```sql
-- kinds: sender | domain | header | subject_regex
INSERT INTO exclusion_rule (kind, pattern, enabled)
VALUES ('domain', 'noisy-newsletter.example', true);

UPDATE exclusion_rule SET enabled = false WHERE id = 42;  -- disable
```
Header patterns are `Header-Name` (presence) or `Header-Name:regex`
(value match). Exclusions apply at item creation; they do not close
existing items.

## What the heartbeat alert means

`DONNA_HEARTBEAT_MISSED` fires at 04:45/14:45 UTC when the 04:30/14:30
digest run did not record success. In order of likelihood:

1. **Function App down or failing** — check the `digest` function's
   invocation log in Application Insights for the exception.
2. **Database unreachable** — check Postgres availability and the
   firewall rule `AllowAzureServices`.
3. **Graph auth broken** — the federated credential or admin consent was
   changed. Re-check OPERATOR.md §2–3.
4. **Access policy broken** — someone removed mailboxes from
   `sg-donna-monitored`. Graph returns `ErrorAccessDenied` in the logs
   (as hashes/status only — no mail content is ever logged).

The alert auto-mitigates after the next successful digest. No alert does
NOT mean digests are pretty — it means the job ran and recorded success.

## Quarterly scoping re-verification

Once a quarter (calendar reminder), re-run and file the evidence:

```powershell
Get-DistributionGroupMember -Identity "sg-donna-monitored"   # exactly 8 members
Get-ApplicationAccessPolicy | Where-Object AppId -eq "<APP_ID>"
Test-ApplicationAccessPolicy -Identity alice@<tenant-domain> -AppId "<APP_ID>"      # Granted
Test-ApplicationAccessPolicy -Identity not-monitored@<tenant-domain> -AppId "<APP_ID>"  # Denied
```

Also confirm in Entra that the app registration still holds exactly the
five permissions from OPERATOR.md §1 and no client secrets or
certificates have been added.

## Mark-as-done links

Each digest line has a signed `mark done` link (HMAC, 36h TTL, single
use, owner-only). A 403 means the link expired — the next digest carries
a fresh one. A 409 means the item is already closed.

## Dry-run mode

Set app setting `DONNA_DRY_RUN=1` (or `UPDATE config SET value='1' WHERE
key='digest_dry_run'`) and digests render to files in the Function App's
working directory instead of sending mail. Use it after any config
surgery before trusting the next live send.
