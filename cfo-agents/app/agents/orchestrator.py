"""Orchestrator: routes a task to the right specialist agent and persists results.

Usage:

    from app.agents.orchestrator import Orchestrator
    with session_scope() as s:
        Orchestrator().dispatch(s, tenant_id="demo", task_type="RECONCILE_BANK_LINE")
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agents.ap_agent import APAgent
from app.agents.ar_agent import ARAgent
from app.agents.base import Agent, AgentContext, AgentOutput
from app.agents.board_reporting_agent import BoardReportingAgent
from app.agents.cashflow_agent import CashflowAgent
from app.agents.compliance_agent import ComplianceAgent
from app.agents.contractor_margin_agent import ContractorMarginAgent
from app.agents.fpa_agent import FPAAgent
from app.agents.reconciliation_agent import ReconciliationAgent
from app.agents.treasury_agent import TreasuryAgent
from app.core.logging import get_logger
from app.db.models import AgentRecommendation
from app.services.approval_service import enqueue
from app.services.audit_service import write_audit

log = get_logger(__name__)


AGENT_REGISTRY: dict[str, Agent] = {
    a.name: a
    for a in [
        ReconciliationAgent(),
        CashflowAgent(),
        ARAgent(),
        APAgent(),
        FPAAgent(),
        ContractorMarginAgent(),
        TreasuryAgent(),
        ComplianceAgent(),
        BoardReportingAgent(),
    ]
}


def _agent_for(task_type: str) -> Agent:
    for agent in AGENT_REGISTRY.values():
        if task_type in agent.handles:
            return agent
    raise KeyError(f"no agent handles task_type={task_type!r}")


class Orchestrator:
    def dispatch(
        self,
        session: Session,
        *,
        tenant_id: str,
        task_type: str,
        inputs: dict[str, Any] | None = None,
    ) -> list[AgentRecommendation]:
        agent = _agent_for(task_type)
        ctx = AgentContext(tenant_id=tenant_id, task_type=task_type, inputs=inputs or {})

        write_audit(
            session,
            actor=f"agent:{agent.name}",
            action="DISPATCH",
            target_type="agents",
            target_id=agent.name,
            tenant_id=tenant_id,
            payload={"task_type": task_type, "inputs": inputs or {}},
        )

        outputs = agent.run(session, ctx)
        return [self._persist(session, tenant_id, o) for o in outputs]

    @staticmethod
    def _persist(session: Session, tenant_id: str, out: AgentOutput) -> AgentRecommendation:
        rec = AgentRecommendation(
            tenant_id=tenant_id,
            agent_name=out.agent_name,
            task_type=out.task_type,
            summary=out.summary,
            recommendation=out.recommendation,
            confidence_score=out.confidence_score,
            risk_level=out.risk_level,
            source_records=[r.model_dump() for r in out.source_records],
            reasoning_summary=out.reasoning_summary,
            requires_human_approval=out.requires_human_approval,
            suggested_action=out.suggested_action.model_dump(),
        )
        session.add(rec)
        session.flush()
        enqueue(session, rec)
        return rec
