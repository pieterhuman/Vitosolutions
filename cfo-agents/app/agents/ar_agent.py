"""Accounts receivable agent.

For each open invoice:
  - compute days overdue
  - score late-payment risk (deterministic)
  - if Claude is available, draft a polite follow-up email; else use a template
  - emit an AR_RISK_REVIEW recommendation, plus a SEND_FOLLOWUP_EMAIL action
    when the invoice is overdue
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentContext, AgentOutput, SourceRecord, SuggestedAction
from app.core.security import sanitize_external_text
from app.db.models import RiskLevel
from app.db.repositories import ContactRepository, InvoiceRepository
from app.integrations.claude_client import get_claude_client


class ARAgent(Agent):
    name = "ar"
    handles = ("AR_RISK_REVIEW", "DRAFT_FOLLOWUP")

    def run(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        invs = InvoiceRepository(session).open_invoices(ctx.tenant_id)
        contacts = ContactRepository(session)
        today = date.today()
        out: list[AgentOutput] = []
        for inv in invs:
            days_overdue = (today - inv.due_date).days
            risk_score = self._risk_score(days_overdue, float(inv.amount_due))
            risk_level = (
                RiskLevel.HIGH if risk_score >= 0.7
                else RiskLevel.MEDIUM if risk_score >= 0.4
                else RiskLevel.LOW
            )

            contact = contacts.get(inv.contact_id) if inv.contact_id else None
            contact_name = contact.name if contact else "Customer"
            contact_email = (contact.email if contact else None) or "unknown@example.com"

            recommendation, suggested = self._build_action(
                inv=inv,
                days_overdue=days_overdue,
                contact_name=contact_name,
                contact_email=contact_email,
            )

            out.append(
                AgentOutput(
                    agent_name=self.name,
                    task_type="AR_RISK_REVIEW",
                    summary=(
                        f"{contact_name}: {inv.invoice_number} "
                        f"{inv.amount_due:,.2f} {inv.currency} "
                        f"({days_overdue}d {'overdue' if days_overdue > 0 else 'until due'})"
                    ),
                    recommendation=recommendation,
                    confidence_score=round(risk_score, 2),
                    risk_level=risk_level,
                    source_records=[
                        SourceRecord(table="invoices", id=inv.id),
                        *(
                            [SourceRecord(table="contacts", id=inv.contact_id)]
                            if inv.contact_id
                            else []
                        ),
                    ],
                    reasoning_summary=(
                        f"{days_overdue}d past due on {inv.amount_due:,.0f} {inv.currency}. "
                        f"Risk score = days_overdue / 60 capped at 1, weighted by amount."
                    ),
                    requires_human_approval=True,
                    suggested_action=suggested,
                )
            )
        return out

    @staticmethod
    def _risk_score(days_overdue: int, amount: float) -> float:
        time_factor = max(0.0, min(1.0, days_overdue / 60.0))
        amount_factor = min(1.0, amount / 100_000.0)
        return 0.7 * time_factor + 0.3 * amount_factor

    def _build_action(self, *, inv, days_overdue: int, contact_name: str, contact_email: str):
        if days_overdue <= 0:
            return (
                f"Monitor {inv.invoice_number}. Due in {-days_overdue}d.",
                SuggestedAction(type="NOTIFY_OWNER", payload={"invoice_id": inv.id, "kind": "ar_watch"}),
            )

        body = self._draft_email(
            contact_name=contact_name,
            invoice_number=inv.invoice_number,
            amount=float(inv.amount_due),
            currency=inv.currency,
            days_overdue=days_overdue,
        )
        rec = f"Send follow-up email to {contact_name} for {inv.invoice_number} ({days_overdue}d overdue)."
        return (
            rec,
            SuggestedAction(
                type="SEND_FOLLOWUP_EMAIL",
                payload={
                    "to": contact_email,
                    "subject": f"Friendly reminder: invoice {inv.invoice_number}",
                    "body": body,
                    "invoice_id": inv.id,
                },
            ),
        )

    @staticmethod
    def _draft_email(*, contact_name, invoice_number, amount, currency, days_overdue) -> str:
        client = get_claude_client()
        safe_name = sanitize_external_text(contact_name, 80)
        if client.available:
            from pydantic import BaseModel

            class _Out(BaseModel):
                body: str

            result = client.complete_json(
                schema=_Out,
                system=(
                    "Draft a polite, concise (<120 words) follow-up email from the "
                    "finance team of a services business. Sign off as 'Finance Team'."
                ),
                user_data={
                    "contact_name": safe_name,
                    "invoice_number": invoice_number,
                    "amount": amount,
                    "currency": currency,
                    "days_overdue": days_overdue,
                },
                max_tokens=400,
            )
            if result and result.body:
                return result.body
        return (
            f"Hi {safe_name},\n\n"
            f"Just a quick note that invoice {invoice_number} for "
            f"{amount:,.2f} {currency} is now {days_overdue} day(s) overdue. "
            f"Could you please confirm a payment date?\n\n"
            f"Many thanks,\nFinance Team"
        )
