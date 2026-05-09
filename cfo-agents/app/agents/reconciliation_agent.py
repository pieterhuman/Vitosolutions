"""Reconciliation agent.

Workflow:
  1. Pull unreconciled bank lines + open invoices/bills.
  2. Run deterministic rules first (`rules_engine.match_bank_line`).
  3. For lines without a deterministic match, optionally call Claude to
     suggest a contact / account code. If Claude is unavailable, fall back
     to merchant normalisation + heuristic account-code suggestion.
  4. Emit one `AgentOutput` per bank line that requires a recommendation.

In MVP the suggested_action is `POST_RECONCILIATION` and is gated by
human approval.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentContext, AgentOutput, SourceRecord, SuggestedAction
from app.core.security import sanitize_external_text
from app.db.models import RiskLevel
from app.db.repositories import (
    BankTransactionRepository,
    BillRepository,
    InvoiceRepository,
)
from app.integrations.claude_client import get_claude_client
from app.services.rules_engine import (
    match_bank_line,
    normalize_merchant,
    suggest_account_code,
)


class ReconciliationAgent(Agent):
    name = "reconciliation"
    handles = ("RECONCILE_BANK_LINE",)

    def run(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        bank_repo = BankTransactionRepository(session)
        inv_repo = InvoiceRepository(session)
        bill_repo = BillRepository(session)

        lines = bank_repo.unreconciled(ctx.tenant_id)
        invs = inv_repo.open_invoices(ctx.tenant_id)
        bills = bill_repo.open_bills(ctx.tenant_id)

        out: list[AgentOutput] = []
        for line in lines:
            out.append(self._reconcile_one(line, invs, bills))
        return out

    def _reconcile_one(self, line, invs, bills) -> AgentOutput:
        amount = float(line.amount)
        desc = line.description or ""

        match = match_bank_line(
            amount=amount,
            description=desc,
            open_invoices=invs,
            open_bills=bills,
        )

        sources = [SourceRecord(table="bank_transactions", id=line.id)]
        if match and match.invoice_id:
            sources.append(SourceRecord(table="invoices", id=match.invoice_id))
        if match and match.bill_id:
            sources.append(SourceRecord(table="bills", id=match.bill_id))

        if match and match.confidence >= 0.75:
            return AgentOutput(
                agent_name=self.name,
                task_type="RECONCILE_BANK_LINE",
                summary=f"Match on amount {amount:.2f}",
                recommendation=(
                    f"Reconcile bank line to "
                    f"{'invoice ' + match.invoice_id if match.invoice_id else 'bill ' + match.bill_id}"
                ),
                confidence_score=match.confidence,
                risk_level=RiskLevel.LOW,
                source_records=sources,
                reasoning_summary=f"Deterministic rule: {match.reason}",
                requires_human_approval=True,
                suggested_action=SuggestedAction(
                    type="POST_RECONCILIATION",
                    payload={
                        "bank_transaction_id": line.id,
                        "invoice_id": match.invoice_id,
                        "bill_id": match.bill_id,
                    },
                ),
            )

        # No deterministic match -> ask Claude for code/category guess, falling
        # back to merchant normalisation.
        merchant = normalize_merchant(desc)
        coded = suggest_account_code(desc) or suggest_account_code(merchant)
        ai_payload, ai_confidence, ai_reason = self._ai_assist(line, merchant)
        code, code_name = coded if coded else (ai_payload.get("account_code"), ai_payload.get("account_name"))
        confidence = max(0.45 if coded else 0.3, ai_confidence)

        return AgentOutput(
            agent_name=self.name,
            task_type="RECONCILE_BANK_LINE",
            summary=f"Unmatched bank line for {merchant} ({amount:.2f})",
            recommendation=(
                f"Suggest account {code} ({code_name}) for {merchant}."
                if code
                else f"Manual review: {merchant} ({amount:.2f})."
            ),
            confidence_score=confidence,
            risk_level=RiskLevel.MEDIUM if confidence < 0.6 else RiskLevel.LOW,
            source_records=sources,
            reasoning_summary=ai_reason
            or f"Merchant normalised to '{merchant}'. {'Heuristic account match.' if coded else 'No exact match.'}",
            requires_human_approval=True,
            suggested_action=SuggestedAction(
                type="POST_RECONCILIATION",
                payload={
                    "bank_transaction_id": line.id,
                    "invoice_id": None,
                    "bill_id": None,
                    "account_code": code,
                    "merchant": merchant,
                },
            ),
        )

    def _ai_assist(self, line, merchant: str) -> tuple[dict, float, str]:
        """Optional AI lift. Returns ({account_code, account_name}, conf, reason)."""
        from pydantic import BaseModel

        class _Out(BaseModel):
            account_code: str | None = None
            account_name: str | None = None
            confidence: float = 0.0
            reason: str = ""

        client = get_claude_client()
        if not client.available:
            return ({}, 0.0, "")
        result = client.complete_json(
            schema=_Out,
            system="You categorize bank transactions for a services business in South Africa using Xero.",
            user_data={
                "amount": float(line.amount),
                "description": sanitize_external_text(line.description),
                "merchant_normalised": merchant,
            },
            max_tokens=400,
        )
        if result is None:
            return ({}, 0.0, "")
        return (
            {"account_code": result.account_code, "account_name": result.account_name},
            min(max(result.confidence, 0.0), 1.0),
            result.reason,
        )
