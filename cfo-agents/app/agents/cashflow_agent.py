"""Cash flow forecasting agent.

Builds 7/30/90-day forecasts. AI is used only to generate the plain-English
commentary; the numbers themselves come from the deterministic
`forecasting_service.build_forecast`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentContext, AgentOutput, SourceRecord, SuggestedAction
from app.db.models import (
    CashflowSnapshot,
    CompanySettings,
    Forecast,
    RiskLevel,
)
from app.db.repositories import BillRepository, InvoiceRepository
from app.integrations.claude_client import get_claude_client
from app.services.forecasting_service import (
    ForecastInputs,
    build_forecast,
    runway_days,
)


class CashflowAgent(Agent):
    name = "cashflow"
    handles = ("BUILD_CASHFLOW_FORECAST",)

    def run(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        invoices = InvoiceRepository(session).open_invoices(ctx.tenant_id)
        bills = BillRepository(session).open_bills(ctx.tenant_id)
        settings = session.get(CompanySettings, ctx.tenant_id) or CompanySettings(
            tenant_id=ctx.tenant_id
        )
        opening = self._latest_balance(session, ctx.tenant_id)

        inputs = ForecastInputs(
            opening_balance=opening,
            invoices=invoices,
            bills=bills,
            monthly_recurring_outflow=float(settings.payroll_monthly or 0),
            vat_reserve_pct=float(settings.vat_reserve_pct or 0.15),
        )

        outputs: list[AgentOutput] = []
        for horizon in (7, 30, 90):
            days = build_forecast(inputs, horizon)
            closing = days[-1].balance if days else opening
            runway = runway_days(days)
            commentary = self._commentary(opening, closing, runway, horizon)

            forecast = Forecast(
                tenant_id=ctx.tenant_id,
                horizon_days=horizon,
                opening_balance=opening,
                closing_balance=closing,
                runway_days=runway,
                series=[
                    {
                        "date": d.date.isoformat(),
                        "inflow": d.inflow,
                        "outflow": d.outflow,
                        "balance": d.balance,
                    }
                    for d in days
                ],
                commentary=commentary,
            )
            session.add(forecast)
            session.flush()

            risk = (
                RiskLevel.HIGH if (runway is not None and runway <= 30)
                else RiskLevel.MEDIUM if closing < opening * 0.5
                else RiskLevel.LOW
            )

            outputs.append(
                AgentOutput(
                    agent_name=self.name,
                    task_type="BUILD_CASHFLOW_FORECAST",
                    summary=f"{horizon}-day forecast: closing {closing:,.0f}",
                    recommendation=commentary,
                    confidence_score=0.7,
                    risk_level=risk,
                    source_records=[SourceRecord(table="forecasts", id=forecast.id)],
                    reasoning_summary=(
                        f"Opening {opening:,.0f}; "
                        f"{len(invoices)} open invoices, {len(bills)} open bills; "
                        f"VAT reserve {inputs.vat_reserve_pct:.0%}; "
                        f"recurring outflow {inputs.monthly_recurring_outflow:,.0f}/mo."
                    ),
                    requires_human_approval=False,  # forecasts are read-only artifacts
                    suggested_action=SuggestedAction(
                        type="NOTIFY_OWNER",
                        payload={"forecast_id": forecast.id, "horizon": horizon},
                    ),
                )
            )
        return outputs

    @staticmethod
    def _latest_balance(session: Session, tenant_id: str) -> float:
        stmt = (
            select(CashflowSnapshot)
            .where(CashflowSnapshot.tenant_id == tenant_id)
            .order_by(CashflowSnapshot.captured_on.desc())
            .limit(1)
        )
        snap = session.execute(stmt).scalar_one_or_none()
        return float(snap.bank_balance) if snap else 0.0

    @staticmethod
    def _commentary(opening: float, closing: float, runway: int | None, horizon: int) -> str:
        client = get_claude_client()
        if not client.available:
            if runway is not None:
                return (
                    f"Cash runs out in ~{runway} days under the current pipeline. "
                    f"Closing balance over the {horizon}-day window is {closing:,.0f}."
                )
            return (
                f"Cash position holds for the full {horizon}-day window. "
                f"Closing balance: {closing:,.0f} (opening {opening:,.0f})."
            )

        from pydantic import BaseModel

        class _Out(BaseModel):
            commentary: str

        result = client.complete_json(
            schema=_Out,
            system="You are the CFO commentator. Write 2-3 plain-English sentences for an owner.",
            user_data={
                "opening_balance": opening,
                "closing_balance": closing,
                "runway_days": runway,
                "horizon_days": horizon,
            },
            max_tokens=300,
        )
        return result.commentary if result else f"Closing balance {closing:,.0f} after {horizon} days."
