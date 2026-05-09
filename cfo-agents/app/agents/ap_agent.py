"""Accounts payable agent.

Responsibilities:
  - Detect duplicate bills (deterministic).
  - Recommend a payment plan ranked by due date and supplier criticality.
  - Flag unusual supplier spend (>2x median month).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import median

from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentContext, AgentOutput, SourceRecord, SuggestedAction
from app.db.models import RiskLevel
from app.db.repositories import BillRepository, ContactRepository
from app.services.rules_engine import find_duplicate_bills


class APAgent(Agent):
    name = "ap"
    handles = ("AP_PAYMENT_PLAN", "FLAG_DUPLICATE_BILL")

    def run(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        bills = BillRepository(session).open_bills(ctx.tenant_id)
        contacts = ContactRepository(session)
        out: list[AgentOutput] = []

        # 1. duplicates
        for a, b in find_duplicate_bills(bills):
            out.append(
                AgentOutput(
                    agent_name=self.name,
                    task_type="FLAG_DUPLICATE_BILL",
                    summary=f"Possible duplicate: {a.bill_number} vs {b.bill_number}",
                    recommendation=(
                        "Review these two bills before payment. Same supplier and total within 7 days."
                    ),
                    confidence_score=0.85,
                    risk_level=RiskLevel.HIGH,
                    source_records=[
                        SourceRecord(table="bills", id=a.id),
                        SourceRecord(table="bills", id=b.id),
                    ],
                    reasoning_summary="Same contact_id and total amount, issue dates within 7 days.",
                    requires_human_approval=True,
                    suggested_action=SuggestedAction(
                        type="NOTIFY_OWNER",
                        payload={"bill_a": a.id, "bill_b": b.id, "kind": "duplicate_bill"},
                    ),
                )
            )

        # 2. unusual supplier spend
        spend_by_contact: dict[str, list[float]] = defaultdict(list)
        for b in bills:
            if b.contact_id:
                spend_by_contact[b.contact_id].append(float(b.total))
        for cid, amounts in spend_by_contact.items():
            if len(amounts) < 3:
                continue
            med = median(amounts)
            for b in bills:
                if b.contact_id == cid and float(b.total) > 2 * med and med > 0:
                    contact = contacts.get(cid)
                    out.append(
                        AgentOutput(
                            agent_name=self.name,
                            task_type="FLAG_DUPLICATE_BILL",
                            summary=f"Unusual spend with {contact.name if contact else cid}",
                            recommendation=(
                                f"Bill {b.bill_number} for {b.total:,.0f} is >2x median for this supplier."
                            ),
                            confidence_score=0.6,
                            risk_level=RiskLevel.MEDIUM,
                            source_records=[SourceRecord(table="bills", id=b.id)],
                            reasoning_summary=f"Median {med:,.0f}; current {float(b.total):,.0f}.",
                            requires_human_approval=True,
                            suggested_action=SuggestedAction(
                                type="NOTIFY_OWNER",
                                payload={"bill_id": b.id, "kind": "unusual_spend"},
                            ),
                        )
                    )

        # 3. payment plan: pay urgent first, batched by week
        today = date.today()
        urgent = sorted(bills, key=lambda b: (b.due_date - today).days)[:10]
        for b in urgent:
            days = (b.due_date - today).days
            risk = (
                RiskLevel.HIGH if days < 0
                else RiskLevel.MEDIUM if days <= 7
                else RiskLevel.LOW
            )
            out.append(
                AgentOutput(
                    agent_name=self.name,
                    task_type="AP_PAYMENT_PLAN",
                    summary=f"Pay bill {b.bill_number} ({b.amount_due:,.0f}) by {b.due_date}",
                    recommendation=(
                        f"Schedule payment for {b.bill_number}. {'Already overdue.' if days < 0 else f'Due in {days}d.'}"
                    ),
                    confidence_score=0.7,
                    risk_level=risk,
                    source_records=[SourceRecord(table="bills", id=b.id)],
                    reasoning_summary="Ranked by due date proximity.",
                    requires_human_approval=True,
                    suggested_action=SuggestedAction(
                        type="MARK_BILL_FOR_PAYMENT",
                        payload={"bill_id": b.id, "amount": float(b.amount_due)},
                    ),
                )
            )

        return out
