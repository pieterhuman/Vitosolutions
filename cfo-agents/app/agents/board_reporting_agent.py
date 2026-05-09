"""Board reporting agent.

Aggregates the latest forecast, AR/AP totals, margin, and risks into a
monthly CFO report. The report is rendered (after approval) via
`document_service.render_board_pack`.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentContext, AgentOutput, SourceRecord, SuggestedAction
from app.db.models import CashflowSnapshot, Forecast, RiskLevel
from app.db.repositories import BillRepository, InvoiceRepository
from app.integrations.claude_client import get_claude_client


class BoardReportingAgent(Agent):
    name = "board_reporting"
    handles = ("MONTHLY_BOARD_PACK",)

    def run(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        invs = InvoiceRepository(session).open_invoices(ctx.tenant_id)
        bills = BillRepository(session).open_bills(ctx.tenant_id)
        ar_total = sum(float(i.amount_due) for i in invs)
        ap_total = sum(float(b.amount_due) for b in bills)

        forecast = session.execute(
            select(Forecast)
            .where(Forecast.tenant_id == ctx.tenant_id)
            .where(Forecast.horizon_days == 90)
            .order_by(Forecast.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        snap = session.execute(
            select(CashflowSnapshot)
            .where(CashflowSnapshot.tenant_id == ctx.tenant_id)
            .order_by(CashflowSnapshot.captured_on.desc())
            .limit(1)
        ).scalar_one_or_none()

        period = date.today().strftime("%B %Y")
        cash = float(snap.bank_balance) if snap else 0.0
        runway = forecast.runway_days if forecast else None
        revenue_proxy = sum(float(i.total) for i in InvoiceRepository(session).list(tenant_id=ctx.tenant_id))

        headline, highlights, risks_md, recs_md = self._narrative(
            cash=cash,
            runway=runway,
            ar=ar_total,
            ap=ap_total,
            revenue=revenue_proxy,
        )

        payload = {
            "period": period,
            "headline": headline,
            "highlights": highlights,
            "revenue": f"{revenue_proxy:,.0f}",
            "cash": f"{cash:,.0f}",
            "runway_days": runway,
            "ar": f"{ar_total:,.0f}",
            "ap": f"{ap_total:,.0f}",
            "gross_margin": "n/a",
            "risks_md": risks_md,
            "recommendations_md": recs_md,
        }

        risk = (
            RiskLevel.HIGH if (runway is not None and runway <= 30)
            else RiskLevel.MEDIUM if (runway is not None and runway <= 60)
            else RiskLevel.LOW
        )

        return [
            AgentOutput(
                agent_name=self.name,
                task_type="MONTHLY_BOARD_PACK",
                summary=f"Monthly CFO pack for {period}",
                recommendation=headline,
                confidence_score=0.7,
                risk_level=risk,
                source_records=[
                    *([SourceRecord(table="forecasts", id=forecast.id)] if forecast else []),
                    *([SourceRecord(table="cashflow_snapshots", id=snap.id)] if snap else []),
                ],
                reasoning_summary="Aggregated cash, AR, AP, and 90d forecast.",
                requires_human_approval=True,
                suggested_action=SuggestedAction(type="GENERATE_BOARD_PACK", payload=payload),
            )
        ]

    @staticmethod
    def _narrative(*, cash: float, runway: int | None, ar: float, ap: float, revenue: float):
        client = get_claude_client()
        if client.available:
            from pydantic import BaseModel

            class _Out(BaseModel):
                headline: str
                highlights: list[str]
                risks_md: str
                recommendations_md: str

            result = client.complete_json(
                schema=_Out,
                system=(
                    "Write a CFO monthly board narrative. Be concise and data-grounded."
                    " Output 1 headline, 3-5 highlights, risks, recommendations."
                ),
                user_data={"cash": cash, "runway": runway, "ar": ar, "ap": ap, "revenue": revenue},
                max_tokens=700,
            )
            if result:
                return (
                    result.headline,
                    result.highlights,
                    result.risks_md,
                    result.recommendations_md,
                )

        headline = (
            f"Cash {cash:,.0f}, runway "
            + (f"{runway}d." if runway is not None else ">90d.")
        )
        highlights = [
            f"AR open: {ar:,.0f}",
            f"AP open: {ap:,.0f}",
            f"Indicative revenue (gross of period): {revenue:,.0f}",
        ]
        risks_md = "- Watch concentration risk on top customers.\n- Confirm VAT reserve."
        recs_md = "- Push collections on overdue invoices.\n- Sequence AP by due date."
        return headline, highlights, risks_md, recs_md
