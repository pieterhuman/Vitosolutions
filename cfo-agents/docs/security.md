# Security & approval workflow

## Principles

1. **Recommendation ≠ execution.** Agents only write to `agent_recommendations`. Side effects (Xero posting, sending email, paying bills) happen only after approval.
2. **Secrets never in code.** Loaded from env via `pydantic-settings`. `.env` is gitignored. Xero refresh tokens are encrypted at rest with `CFO_SECRET_KEY` (Fernet).
3. **Prompt injection containment.** Agents pass external text (vendor names, invoice memos, emails) through `core.security.sanitize_external_text()` before including it in Claude prompts. Agent prompts never grant tools that the agent doesn't need. AI output is parsed as JSON against a Pydantic schema; any free text it produces cannot escape the schema.
4. **Least privilege.** Approver role is required for any action that mutates Xero or sends external messages. Viewer role can read recommendations only.
5. **Immutable audit log.** `audit_logs` rows are append-only. Every recommendation, approval, posting, and sync is logged with actor, timestamp, before/after.
6. **Input validation.** All API inputs are Pydantic models. SQL is parameterized via SQLAlchemy.
7. **TLS enforced** in production via reverse proxy. JWT for API auth.

## Approval gates

```
                +--------------------+
   agent.run -> | agent_recommendation |
                +----------+---------+
                           |
                           v
                +-------------------+
                | approval_service  |
                |   .enqueue()      |
                +----+-------+------+
                     |       |
              APPROVED       REJECTED
                     |
                     v
        +------------+--------------+
        | typed action handler      |
        | (xero_client / email /    |
        |  internal status change)  |
        +---------------------------+
                     |
                     v
                audit_logs (append)
```

## What AI is NOT allowed to do (MVP)

- Post journals, invoices, payments, or reconciliations directly to Xero.
- Send email or Slack messages directly.
- Modify `chart_of_accounts`, `finance_rules`, or `company_settings`.
- Override approval gates via tool calls. (No tool granting executes side effects without going through `approval_service.commit()`.)

## Secrets & PII

- Xero tokens: encrypted column.
- Bank account numbers: stored as last-4 only in dashboard; full value in DB column flagged as sensitive.
- Email contents in `documents` table are tagged `pii=true` and excluded from log output.
