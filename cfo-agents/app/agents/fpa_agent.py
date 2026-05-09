"""FP&A agent.

Scenario modelling and budget-vs-actual. The numerics are deterministic;
Claude (when available) writes the executive commentary.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.base import Agent, AgentContext, AgentOutput, SourceRecord, SuggestedAction
from app.db.models import RiskLevel
from app.db.repositories import BillRepository, InvoiceRepository
from app.integrations.claude_client import get_claude_client


class FPAAgent(Agent):
    name = "fpa"
    handles = ("BUDGET_VS_ACTUAL", "SCENARIO_MODEL")

    def run(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        if ctx.task_type == "SCENARIO_MODEL":
            return [self._scenario(ctx)]
        return [self._budget_vs_actual(session, ctx)]

    def _budget_vs_actual(self, session: Session, ctx: AgentContext) -> AgentOutput:
        budget = float(ctx.inputs.get("monthly_budget", 0) or 0)
        invs = InvoiceRepository(session).list(tenant_id=ctx.tenant_id)
        bills = BillRepository(session).list(tenant_id=ctx.tenant_id)
        actual_revenue = sum(float(i.total) for i in invs)
        actual_costs = sum(float(b.total) for b in bills)
        variance = actual_revenue - actual_costs - budget

        commentary = self._commentary(
            "budget_vs_actual",
            {
                "budget": budget,
                "actual_revenue": actual_revenue,
                "actual_costs": actual_costs,
                "variance": variance,
            },
            f"Net of {actual_revenue - actual_costs:,.0f} vs budget {budget:,.0f} (variance {variance:,.0f}).",
        )

        risk = RiskLevel.HIGH if variance < -budget * 0.2 else RiskLevel.MEDIUM if variance < 0 else RiskLevel.LOW

        return AgentOutput(
            agent_name=self.name,
            task_type="BUDGET_VS_ACTUAL",
            summary=f"Net {actual_revenue - actual_costs:,.0f} vs budget {budget:,.0f}",
            recommendation=commentary,
            confidence_score=0.75,
            risk_level=risk,
            source_records=[],
            reasoning_summary="Sum of invoices minus sum of bills minus budget.",
            requires_human_approval=False,
            suggested_action=SuggestedAction(type="NOTIFY_OWNER", payload={"variance": variance}),
        )

    def _scenario(self, ctx: AgentContext) -> AgentOutput:
        scenario = ctx.inputs.get("scenario", "revenue_drop_20")
        baseline_runway = float(ctx.inputs.get("baseline_runway_days", 120))
        if scenario == "revenue_drop_20":
            new_runway = baseline_runway * 0.78
            description = "20% revenue drop"
        elif scenario == "hire_2_engineers":
            new_runway = baseline_runway - 18
            description = "Hiring 2 engineers at average loaded cost"
        elif scenario == "client_pays_30_late":
            new_runway = baseline_runway - 12
            description = "Largest client pays 30 days late"
        else:
            new_runway = baseline_runway
            description = scenario

        risk = (
            RiskLevel.HIGH if new_runway < 60
            else RiskLevel.MEDIUM if new_runway < 90
            else RiskLevel.LOW
        )
        commentary = self._commentary(
            "scenario",
            {"scenario": description, "baseline_runway": baseline_runway, "new_runway": new_runway},
            f"Under '{description}', runway moves from {baseline_runway:.0f}d to {new_runway:.0f}d.",
        )
        return AgentOutput(
            agent_name=self.name,
            task_type="SCENARIO_MODEL",
            summary=f"{description}: runway {new_runway:.0f}d (was {baseline_runway:.0f}d)",
            recommendation=commentary,
            confidence_score=0.65,
            risk_level=risk,
            source_records=[],
            reasoning_summary="Static stress factors; replace with full reforecast post-MVP.",
            requires_human_approval=False,
            suggested_action=SuggestedAction(type="NOTIFY_OWNER", payload={"scenario": scenario}),
        )

    @staticmethod
    def _commentary(kind: str, data: dict, fallback: str) -> str:
        client = get_claude_client()
        if not client.available:
            return fallback
        from pydantic import BaseModel

        class _Out(BaseModel):
            commentary: str

        result = client.complete_json(
            schema=_Out,
            system="You are an FP&A analyst. Write 2-3 sentences for an exec audience.",
            user_data={"kind": kind, **data},
            max_tokens=300,
        )
        return result.commentary if result else fallback
