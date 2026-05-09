# Architecture overview

## Goal

A modular AI CFO platform for a services business. Xero is the source of truth. AI agents read from a normalized snapshot of Xero data, produce **recommendations** with confidence scores and explanations, and route them through an **approval queue**. Only after human approval can the system post back to Xero.

## High-level flow

```
                  +---------------------+
                  |  Xero (OAuth2)      |
                  +----------+----------+
                             | sync (read)
                             v
+-----------+      +---------+----------+      +----------------+
|  n8n /    | <--> |  FastAPI Backend   | <--> |  PostgreSQL    |
|  cron     |      |  - sync jobs       |      |  + pgvector    |
+-----------+      |  - agent runners   |      +----------------+
                   |  - approval API    |
                   +----+----------+----+
                        |          |
                        v          v
                +----------+   +-----------+
                | Streamlit|   | n8n hooks |
                | dashboard|   +-----------+
                +----------+
```

## Layers

| Layer | Responsibility |
| --- | --- |
| `integrations/` | Talks to Xero, Claude, n8n. No business logic. |
| `db/` | SQLAlchemy models + repositories. The normalized finance data layer. |
| `services/` | Cross-cutting business logic: rules engine, forecasting, approval workflow, audit, document generation. |
| `agents/` | Specialist agents. Each produces a `AgentRecommendation` (see schema). Orchestrator routes tasks. |
| `api/` | FastAPI routes for sync, agents, approvals, audit, dashboard data. |
| `ui/` | Streamlit CFO dashboard. |
| `core/` | Config, logging, security, permissions. |

## Sync model

1. Xero OAuth2 token obtained and encrypted at rest.
2. A periodic sync job (or n8n webhook) pulls bank transactions, invoices, bills, contacts, chart of accounts, journals, AR, AP.
3. Snapshots are stored in normalized tables. Source data is **never overwritten** — every sync writes a new versioned row + entry in `audit_logs`.

## Agent execution model

```
Trigger (cron / API / n8n) ──▶ Orchestrator
        ├─ select agent based on task_type
        ├─ load required snapshot data via repositories
        ├─ run deterministic rules (rules_engine)
        ├─ call agent.run()  -> AgentRecommendation (JSON)
        ├─ persist to agent_recommendations
        └─ if requires_human_approval -> approval_service.enqueue()
```

## Approval workflow

```
agent_recommendation (status=PENDING)
   ├─ approver views in dashboard
   ├─ approver approves / rejects / edits
   ├─ approval_service writes to approvals + audit_logs
   └─ on APPROVED:
        - if action target = Xero: integrations/xero_client.post(...)
        - else: internal state change (e.g. mark invoice followed up)
```

In the MVP, `CFO_AUTO_APPROVE_THRESHOLD = 0.0` — nothing is ever auto-approved. The threshold can be raised later by class of action.

## Demo mode

`CFO_DEMO_MODE=true` swaps:
- Postgres → in-memory SQLite + seed CSVs in `seed_data/`
- Xero client → fixture-backed `FakeXeroClient`
- Claude client → optional; if `ANTHROPIC_API_KEY` is set we call Claude, otherwise the agents fall back to deterministic rule output.

This lets the whole platform be demoed without external services.

## Extensibility

- New agent → new file in `app/agents/`, register in `orchestrator.AGENT_REGISTRY`.
- New data source → new client in `app/integrations/` + sync job + table.
- New approval type → extend `ApprovalAction` enum and add a handler in `approval_service`.
