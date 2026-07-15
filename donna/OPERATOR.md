# OPERATOR.md — one-time setup

Everything below happens inside the client's tenant. Donna has no client
secret; auth is Managed Identity + federated credential. Follow the steps
in order. Placeholders: `<TENANT_ID>`, `<APP_ID>`, `<MI_PRINCIPAL_ID>`
(managed identity object id, from the Bicep output
`managedIdentityPrincipalId`).

## 1. Entra app registration (single tenant)

1. Entra admin center → App registrations → **New registration**
   - Name: `donna-minimal`
   - Supported account types: **Accounts in this organizational
     directory only** (single tenant)
   - No redirect URI, no client secret, no certificate. Ever.
2. API permissions → Add a permission → Microsoft Graph →
   **Application permissions**. Add exactly these five and nothing else:
   - `Mail.Read`
   - `Mail.Send`
   - `Calendars.Read`
   - `Tasks.Read.All`
   - `User.Read.All`

   Do **not** add `Mail.ReadWrite`, `Chat.Read.All`, or
   `ChannelMessage.Read.All`. If a future request asks for them, that
   request is out of scope for this product by design.

   > `Tasks.Read.All` covers both To Do and Planner application-
   > permission reads — the overdue-Planner section in the briefings
   > needs no extra permission. Governance note: the Exchange
   > Application Access Policy in §5 fences **mailbox** access only; it
   > does not scope Planner. Donna's code reads Planner tasks solely
   > for the active principals in its ledger — include that in the
   > quarterly re-verification (RUNBOOK.md).
3. Remove the default `User.Read` delegated permission (unused).

## 2. Admin consent

Grant tenant-wide admin consent either with the button on the API
permissions blade, or by visiting:

```
https://login.microsoftonline.com/<TENANT_ID>/adminconsent?client_id=<APP_ID>
```

Verify all five permissions show **Granted for <tenant>**.

## 3. Deploy infrastructure, then federate the managed identity

1. Deploy: `az deployment group create -g rg-donna -f infra/main.bicep \
   -p appClientId=<APP_ID> pgAdminObjectId=<your-object-id> \
   pgAdminUpn=<you@tenant>`
2. App registration → **Certificates & secrets → Federated credentials →
   Add credential → Other issuer**:
   - Issuer: `https://login.microsoftonline.com/<TENANT_ID>/v2.0`
   - Subject identifier: `<MI_PRINCIPAL_ID>`
   - Audience: `api://AzureADTokenExchange`
   - Name: `donna-func-mi`

   This is what lets the Function App's managed identity act as the app
   registration with zero stored secrets.
3. Put the two secrets in Key Vault (names must match exactly):
   ```bash
   az keyvault secret set --vault-name <kv-name> \
     --name donna-close-hmac-key \
     --value "$(openssl rand -hex 64)"
   az keyvault secret set --vault-name <kv-name> \
     --name donna-teams-webhook-url \
     --value "<Teams Workflows webhook URL>"
   ```
4. Postgres: connect as the Entra admin and run
   `select * from pgaadauth_create_principal('donna-mi', false, false);`
   then, after first startup has created the schema, run
   `infra/sql/001_item_event_append_only.sql`.

## 4. Service mailbox

Create a dedicated mailbox `donna@<tenant-domain>` (a normal licensed
mailbox or a shared mailbox with the app sending as itself via Graph).
All digests are sent **from** this mailbox via `POST /users/donna@…/sendMail`.
Donna never sends as a person. Set `service_mailbox_upn` in the CONFIG
table to this UPN. This mailbox must also be a member of the security
group below, or sendMail will be blocked by the access policy — that is
correct and intended.

## 5. Application Access Policy — scope Graph to the 7 mailboxes

Application permissions are tenant-wide by default. This step restricts
Donna to exactly the monitored mailboxes plus the service mailbox.
In Exchange Online PowerShell (`Connect-ExchangeOnline`):

```powershell
# Mail-enabled security group holding ONLY the monitored mailboxes
# and the service mailbox.
New-DistributionGroup -Name "sg-donna-monitored" `
    -Alias "sg-donna-monitored" -Type "Security"

# The 7 monitored people + the service mailbox:
@(
  "ceo@<tenant-domain>", "alice@<tenant-domain>", "bob@<tenant-domain>",
  "carol@<tenant-domain>", "dan@<tenant-domain>", "erin@<tenant-domain>",
  "frank@<tenant-domain>", "donna@<tenant-domain>"
) | ForEach-Object {
  Add-DistributionGroupMember -Identity "sg-donna-monitored" -Member $_
}

New-ApplicationAccessPolicy -AppId "<APP_ID>" `
    -PolicyScopeGroupId "sg-donna-monitored@<tenant-domain>" `
    -AccessRight RestrictAccess `
    -Description "Donna Minimal: restrict Graph mail/calendar/tasks access to monitored mailboxes only"
```

### Verification (required, not optional)

```powershell
# Member: expect AccessCheckResult = Granted
Test-ApplicationAccessPolicy -Identity alice@<tenant-domain> -AppId "<APP_ID>"

# NON-member: expect AccessCheckResult = Denied
Test-ApplicationAccessPolicy -Identity someone-else@<tenant-domain> -AppId "<APP_ID>"
```

Then verify end-to-end with a real Graph call against a non-member
mailbox (e.g. via Graph Explorer signed in as the app, or a one-off call
from the Function App). Expected evidence — an HTTP **403** with:

```json
{
  "error": {
    "code": "ErrorAccessDenied",
    "message": "Access to OData is disabled."
  }
}
```

Keep a copy of both `Test-ApplicationAccessPolicy` outputs and the 403
response body with the deployment records.

> **Propagation:** Application Access Policy changes can take **more
> than an hour** to take effect. A `Granted/Denied` from
> `Test-ApplicationAccessPolicy` reflects the stored policy immediately,
> but live Graph calls may honor the old policy until propagation
> completes. Do not conclude the policy is broken inside that window.

## 6. Seed the ledger configuration

Insert the 7 principals into `principal` (upn, display_name, is_ceo,
active), your VIP rows into `vip_contact`, and any exclusion rules into
`exclusion_rule`. See RUNBOOK.md for the exact statements. Then review
the CONFIG table (CONFIG.md) — especially `teams_webhook_url`,
`service_mailbox_upn`, `internal_domains`, and `close_base_url` (set it
to the Bicep output `closeEndpointBase`).

## 7. Alert action group

The Bicep template creates the scheduled-query alert
`donna-heartbeat-missed` keyed on the `DONNA_HEARTBEAT_MISSED` log line.
Attach your action group (email/SMS) to that alert rule in the portal —
Donna only emits the signal.
