"""Contractor margin agent.

For each contractor (supplier), match their cost (bills) to client billings
(invoices) tagged to them, and compute gross margin. In MVP we assume tags
arrive as `inputs.contractor_map = {contractor_contact_id: [client_contact_id, ...]}`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentContext, AgentOutput, SourceRecord, SuggestedAction
from app.db.models import RiskLevel
from app.db.repositories import BillRepository, ContactRepository, InvoiceRepository


class ContractorMarginAgent(Agent):
    name = "contractor_margin"
    handles = ("CONTRACTOR_MARGIN_REVIEW",)

    def run(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        bills = BillRepository(session).list(tenant_id=ctx.tenant_id)
        invs = InvoiceRepository(session).list(tenant_id=ctx.tenant_id)
        contacts = ContactRepository(session)
        mapping: dict[str, list[str]] = ctx.inputs.get("contractor_map", {})

        out: list[AgentOutput] = []
        for contractor_id, client_ids in mapping.items():
            cost = sum(float(b.total) for b in bills if b.contact_id == contractor_id)
            revenue = sum(float(i.total) for i in invs if i.contact_id in client_ids)
            margin = revenue - cost
            margin_pct = (margin / revenue) if revenue > 0 else 0.0
            contractor = contacts.get(contractor_id)
            name = contractor.name if contractor else contractor_id

            risk = (
                RiskLevel.HIGH if margin_pct < 0.10
                else RiskLevel.MEDIUM if margin_pct < 0.25
                else RiskLevel.LOW
            )
            out.append(
                AgentOutput(
                    agent_name=self.name,
                    task_type="CONTRACTOR_MARGIN_REVIEW",
                    summary=f"{name}: margin {margin_pct:.0%} ({margin:,.0f})",
                    recommendation=(
                        "Margin healthy."
                        if margin_pct >= 0.25
                        else f"Margin on {name} is {margin_pct:.0%}. Review pricing or utilisation."
                    ),
                    confidence_score=0.7,
                    risk_level=risk,
                    source_records=[SourceRecord(table="contacts", id=contractor_id)],
                    reasoning_summary=(
                        f"Cost {cost:,.0f}, revenue {revenue:,.0f}, margin {margin:,.0f} ({margin_pct:.0%})."
                    ),
                    requires_human_approval=False,
                    suggested_action=SuggestedAction(
                        type="NOTIFY_OWNER",
                        payload={"contractor_id": contractor_id, "margin_pct": margin_pct},
                    ),
                )
            )
        return out
