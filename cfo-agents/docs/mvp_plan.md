# MVP implementation plan

The MVP is a working demo. Anything in **bold** is in scope for the first cut.

## In scope

1. **Repo + folder layout** ✅
2. **Database schema + SQLAlchemy models** ✅
3. **Xero OAuth2 skeleton** (real OAuth flow + token store; data fetch stubbed for fixtures) ✅
4. **Claude client abstraction** ✅
5. **Rules engine** (deterministic merchant normalization, duplicate detection, VAT) ✅
6. **Reconciliation agent** ✅
7. **Cash flow forecasting agent** (7/30/90-day) ✅
8. **AR agent** (late-payment risk score + email draft) ✅
9. **AP agent** (duplicate detection + payment-plan suggestion) ✅
10. **FP&A agent** (budget vs actual + scenario stubs) ✅
11. **Contractor margin / Treasury / Compliance / Board reporting agents** ✅
12. **Approval queue + audit log** ✅
13. **Streamlit dashboard** ✅
14. **Demo data mode** ✅
15. **Tests** for: schema, rules engine, recon agent, cashflow agent, approval flow ✅

## Out of scope (post-MVP)

- Multi-tenant org switching UI
- Production-grade Xero rate limit handling and pagination edge cases
- Rich PDF templating (board pack is markdown + simple PDF)
- Role-based UI (only API-level permissions in MVP)
- pgvector-backed memory (table is created, but not yet populated)
- Auto-approval thresholds
- Crypto treasury integration

## Sequence

1. Schema → models → repositories.
2. Integrations: Xero client (skeleton) + Claude client.
3. Services: rules engine → approval → audit → forecasting → document.
4. Base agent + 9 specialist agents + orchestrator.
5. API routes.
6. Streamlit dashboard.
7. Seed data + tests.
