"""Compliance & audit agent.

Checks:
  - VAT reserve adequacy: reserve >= vat_rate * recent revenue.
  - Suspicious journal patterns (very large round-numbered entries).
  - Missing documentation (placeholder check; extend with attachments later).

Never gives final tax/legal authority — always recommends human review.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentContext, AgentOutput, SourceRecord, SuggestedAction
from app.db.models import CashflowSnapshot, CompanySettings, Journal, RiskLevel
from app.db.repositories import InvoiceRepository


class ComplianceAgent(Agent):
    name = "compliance"
    handles = ("VAT_RESERVE_CHECK", "AUDIT_PATTERN_CHECK")

    def run(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        out: list[AgentOutput] = []

        if ctx.task_type in ("VAT_RESERVE_CHECK", "ALL"):
            out.extend(self._vat_reserve(session, ctx))
        if ctx.task_type in ("AUDIT_PATTERN_CHECK", "ALL"):
            out.extend(self._audit_patterns(session, ctx))
        return out

    def _vat_reserve(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        settings = session.get(CompanySettings, ctx.tenant_id) or CompanySettings(tenant_id=ctx.tenant_id)
        snap = session.query(CashflowSnapshot).filter_by(tenant_id=ctx.tenant_id).order_by(
            CashflowSnapshot.captured_on.desc()
        ).first()
        invs = InvoiceRepository(session).list(tenant_id=ctx.tenant_id)
        revenue = sum(float(i.total) for i in invs)
        required = revenue * float(settings.vat_rate or 0.15)
        held = float(snap.vat_reserve) if snap else 0.0
        gap = required - held

        risk = (
            RiskLevel.HIGH if gap > required * 0.5
            else RiskLevel.MEDIUM if gap > 0
            else RiskLevel.LOW
        )
        rec = (
            f"VAT reserve shortfall of {gap:,.0f}. Top up before next return."
            if gap > 0
            else "VAT reserve appears adequate. Confirm with your accountant."
        )
        return [
            AgentOutput(
                agent_name=self.name,
                task_type="VAT_RESERVE_CHECK",
                summary=f"VAT reserve {held:,.0f} vs required {required:,.0f}",
                recommendation=rec,
                confidence_score=0.75,
                risk_level=risk,
                source_records=[],
                reasoning_summary=(
                    f"vat_rate={settings.vat_rate}, revenue={revenue:,.0f}, "
                    f"required={required:,.0f}, held={held:,.0f}."
                ),
                requires_human_approval=False,
                suggested_action=SuggestedAction(
                    type="NOTIFY_OWNER",
                    payload={"vat_gap": gap, "required": required, "held": held},
                ),
            )
        ]

    def _audit_patterns(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        journals = session.query(Journal).filter_by(tenant_id=ctx.tenant_id).all()
        out: list[AgentOutput] = []
        for j in journals:
            lines = j.lines or []
            if not isinstance(lines, list):
                continue
            for line in lines:
                amt = float(line.get("amount", 0))
                if amt >= 100_000 and amt % 10_000 == 0:
                    out.append(
                        AgentOutput(
                            agent_name=self.name,
                            task_type="AUDIT_PATTERN_CHECK",
                            summary=f"Large round-number journal entry: {amt:,.0f}",
                            recommendation="Review the journal — round numbers at this size are unusual.",
                            confidence_score=0.55,
                            risk_level=RiskLevel.MEDIUM,
                            source_records=[SourceRecord(table="journals", id=j.id)],
                            reasoning_summary="Heuristic: amount >= 100k AND divisible by 10k.",
                            requires_human_approval=False,
                            suggested_action=SuggestedAction(
                                type="NOTIFY_OWNER",
                                payload={"journal_id": j.id, "amount": amt},
                            ),
                        )
                    )
                    break
        return out
