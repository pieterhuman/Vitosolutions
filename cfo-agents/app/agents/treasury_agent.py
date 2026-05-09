"""Treasury agent.

Compares operating reserves to the policy in `company_settings`. Recommends
liquidity buffer changes when below target.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentContext, AgentOutput, SourceRecord, SuggestedAction
from app.db.models import CashflowSnapshot, CompanySettings, RiskLevel


class TreasuryAgent(Agent):
    name = "treasury"
    handles = ("RESERVE_POLICY_REVIEW",)

    def run(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        settings = session.get(CompanySettings, ctx.tenant_id) or CompanySettings(tenant_id=ctx.tenant_id)
        snap = session.execute(
            select(CashflowSnapshot)
            .where(CashflowSnapshot.tenant_id == ctx.tenant_id)
            .order_by(CashflowSnapshot.captured_on.desc())
            .limit(1)
        ).scalar_one_or_none()
        if not snap:
            return []

        # Daily burn ≈ payroll/30 + ap-due-this-month/30 (approx).
        daily_burn = float(settings.payroll_monthly or 0) / 30.0 + float(snap.open_ap or 0) / 30.0
        days_of_reserve = (float(snap.bank_balance) / daily_burn) if daily_burn > 0 else 9999.0
        target = float(settings.operating_reserve_target_days)

        risk = (
            RiskLevel.HIGH if days_of_reserve < target * 0.5
            else RiskLevel.MEDIUM if days_of_reserve < target
            else RiskLevel.LOW
        )

        rec = (
            f"Reserves are {days_of_reserve:.0f} days vs target {target:.0f} days. "
            + ("Increase the buffer." if days_of_reserve < target else "Within policy.")
        )

        return [
            AgentOutput(
                agent_name=self.name,
                task_type="RESERVE_POLICY_REVIEW",
                summary=f"{days_of_reserve:.0f}d of reserves vs target {target:.0f}d",
                recommendation=rec,
                confidence_score=0.8,
                risk_level=risk,
                source_records=[SourceRecord(table="cashflow_snapshots", id=snap.id)],
                reasoning_summary=(
                    f"Bank {float(snap.bank_balance):,.0f} / daily burn {daily_burn:,.0f} = {days_of_reserve:.1f}d."
                ),
                requires_human_approval=False,
                suggested_action=SuggestedAction(
                    type="NOTIFY_OWNER",
                    payload={"days_of_reserve": days_of_reserve, "target": target},
                ),
            )
        ]
