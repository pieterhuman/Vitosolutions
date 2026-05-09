"""Agent dispatch endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.orchestrator import AGENT_REGISTRY, Orchestrator
from app.api.deps import get_db, get_tenant_id

router = APIRouter(prefix="/agents", tags=["agents"])


class DispatchRequest(BaseModel):
    task_type: str
    inputs: dict[str, Any] = {}


@router.get("")
def list_agents() -> dict:
    return {
        name: {"handles": list(agent.handles)}
        for name, agent in AGENT_REGISTRY.items()
    }


@router.post("/dispatch")
def dispatch(
    body: DispatchRequest,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    recs = Orchestrator().dispatch(
        db, tenant_id=tenant_id, task_type=body.task_type, inputs=body.inputs
    )
    return {
        "count": len(recs),
        "recommendations": [
            {
                "id": r.id,
                "agent": r.agent_name,
                "summary": r.summary,
                "confidence": r.confidence_score,
                "risk": r.risk_level,
                "requires_approval": r.requires_human_approval,
                "action": r.suggested_action,
            }
            for r in recs
        ],
    }
