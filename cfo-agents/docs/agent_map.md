# Agent responsibility map

| # | Agent | Task types | Reads | Writes (recommendations only) |
| --- | --- | --- | --- | --- |
| 1 | Reconciliation | `RECONCILE_BANK_LINE` | bank_transactions, invoices, bills, contacts, COA | reconciliations, agent_recommendations |
| 2 | Cash flow forecasting | `BUILD_CASHFLOW_FORECAST` | bank balances, invoices, bills, recurring expenses, payroll, VAT reserve | forecasts, cashflow_snapshots, agent_recommendations |
| 3 | Accounts receivable | `AR_RISK_REVIEW`, `DRAFT_FOLLOWUP` | invoices, contacts, payment history | agent_recommendations |
| 4 | Accounts payable | `AP_PAYMENT_PLAN`, `FLAG_DUPLICATE_BILL` | bills, contacts | agent_recommendations |
| 5 | FP&A | `BUDGET_VS_ACTUAL`, `SCENARIO_MODEL` | forecasts, P&L data, headcount inputs | agent_recommendations |
| 6 | Contractor margin | `CONTRACTOR_MARGIN_REVIEW` | bills (contractors), invoices (clients) | agent_recommendations |
| 7 | Treasury | `RESERVE_POLICY_REVIEW` | cashflow_snapshots, settings | agent_recommendations |
| 8 | Compliance & audit | `VAT_RESERVE_CHECK`, `AUDIT_PATTERN_CHECK` | journals, audit_logs | agent_recommendations |
| 9 | Board reporting | `MONTHLY_BOARD_PACK` | all of the above | agent_recommendations + PDF/MD |
| 10 | Orchestrator | (router) | n/a | dispatches to agents |

## Approval gates

Every agent sets `requires_human_approval=True` in the MVP. Suggested actions are routed to a typed handler:

| `suggested_action.type` | Handler |
| --- | --- |
| `POST_RECONCILIATION` | `xero_client.post_reconciliation` |
| `SEND_FOLLOWUP_EMAIL` | `document_service.send_email` |
| `MARK_BILL_FOR_PAYMENT` | internal status change |
| `GENERATE_BOARD_PACK` | `document_service.render_pdf` |
| `NOTIFY_OWNER` | n8n webhook |

Each handler is only invoked after `approvals.status == APPROVED`.
