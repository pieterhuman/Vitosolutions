# Data model

All tables are normalized snapshots of Xero data plus platform-internal tables for AI recommendations, approvals, and audit.

## Source-of-truth (Xero snapshots)

| Table | Purpose |
| --- | --- |
| `bank_transactions` | Bank lines pulled from Xero. |
| `invoices` | AR invoices (issued by us). |
| `bills` | AP bills (received from suppliers). |
| `contacts` | Customers + suppliers. |
| `chart_of_accounts` | Account codes (revenue, COGS, expenses, etc.). |
| `journals` | Journal entries. |

Each row carries `xero_id`, `tenant_id`, `synced_at`, and `version`. Updates create a new row; old rows are kept.

## Platform tables

| Table | Purpose |
| --- | --- |
| `reconciliations` | Suggested + accepted reconciliation matches. |
| `agent_recommendations` | Standard AgentRecommendation JSON for every agent run. |
| `approvals` | Approval queue with status (PENDING, APPROVED, REJECTED, AUTO_APPROVED). |
| `forecasts` | Cash flow forecast snapshots (7/30/90-day). |
| `cashflow_snapshots` | Point-in-time cash positions. |
| `audit_logs` | Immutable log of every action (sync, recommendation, approval, posting). |
| `finance_rules` | Configurable deterministic rules used by the rules engine. |
| `company_settings` | Per-tenant settings: VAT rate, reserve policy, payroll cadence, etc. |

## Standard agent output schema

```json
{
  "agent_name": "string",
  "task_type": "string",
  "summary": "string",
  "recommendation": "string",
  "confidence_score": 0.0,
  "risk_level": "low | medium | high",
  "source_records": [{"table": "invoices", "id": "uuid"}],
  "reasoning_summary": "string",
  "requires_human_approval": true,
  "suggested_action": {"type": "POST_RECONCILIATION", "payload": {}},
  "created_at": "ISO-8601"
}
```

This schema is enforced by `app/agents/base.py::AgentRecommendation`.
