# CFO Agents

Modular AI CFO agent platform for services businesses. Xero is the source of truth; AI suggests, humans approve, the system posts.

## Highlights

- **12 specialist agents** (reconciliation, cash flow, AR, AP, FP&A, contractor margin, treasury, compliance, board reporting, plus an orchestrator).
- **Approval-first**: no AI-generated change is posted to Xero in the MVP without human approval.
- **Auditable**: every recommendation, approval, and posting is logged.
- **Local demo mode**: runs end-to-end on seed data without Xero or external APIs.

## Stack

| Layer | Tech |
| --- | --- |
| API | FastAPI |
| DB | PostgreSQL + pgvector |
| AI | Claude (Anthropic) |
| Accounting | Xero API (OAuth2) |
| Workflow | n8n-compatible webhooks |
| UI | Streamlit (MVP) |
| Tests | pytest |

## Quick start

```bash
cd cfo-agents
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Demo mode (no Xero, no Postgres needed):
export CFO_DEMO_MODE=true
uvicorn app.main:app --reload
# In a second shell:
streamlit run app/ui/dashboard.py
```

For the full Postgres + Xero setup see `docs/setup.md`.

## Project layout

See `docs/architecture.md` for the full architecture and `docs/agent_map.md` for the responsibility map.

```
app/
  api/             FastAPI routes
  agents/          Specialist agents (one file per agent) + orchestrator
  core/            Config, security, logging, permissions
  db/              SQLAlchemy models, migrations, repositories
  integrations/    Xero, Claude, n8n webhook clients
  services/        Forecasting, rules engine, approval, audit, document
  ui/              Streamlit dashboard
  main.py          FastAPI entrypoint
docs/              Architecture + setup + security
seed_data/         Demo CSVs used in CFO_DEMO_MODE=true
tests/             pytest
```

## Safety model

1. Deterministic rules run first.
2. AI reasoning runs second, with structured JSON output, confidence score, explanation, and source record references.
3. Low-confidence items go to the review queue. High-confidence items still require human approval before any Xero write in the MVP.
4. Every action is captured in `audit_logs`.

## License

Proprietary — Vito Solutions.
