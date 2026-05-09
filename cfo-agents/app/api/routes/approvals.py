"""Approval queue API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_tenant_id, require_perm
from app.core.permissions import Permission
from app.db.models import Approval
from app.db.repositories import ApprovalRepository
from app.services import approval_service

router = APIRouter(prefix="/approvals", tags=["approvals"])


class DecisionRequest(BaseModel):
    note: str | None = None


@router.get("")
def list_pending(
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> list[dict]:
    pending = ApprovalRepository(db).pending(tenant_id)
    return [
        {
            "id": a.id,
            "recommendation_id": a.recommendation_id,
            "summary": a.recommendation.summary,
            "agent": a.recommendation.agent_name,
            "confidence": a.recommendation.confidence_score,
            "risk": a.recommendation.risk_level,
            "action": a.recommendation.suggested_action,
            "created_at": a.created_at.isoformat(),
        }
        for a in pending
    ]


@router.post("/{approval_id}/approve", dependencies=[Depends(require_perm(Permission.APPROVE_RECOMMENDATIONS))])
def approve(
    approval_id: str,
    body: DecisionRequest = DecisionRequest(),
    db: Session = Depends(get_db),
) -> dict:
    approval = db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(404, "approval not found")
    result = approval_service.commit(
        db, approval, decided_by="user:owner", decision_note=body.note
    )
    return {"status": "approved", "result": result}


@router.post("/{approval_id}/reject", dependencies=[Depends(require_perm(Permission.APPROVE_RECOMMENDATIONS))])
def reject(
    approval_id: str,
    body: DecisionRequest = DecisionRequest(),
    db: Session = Depends(get_db),
) -> dict:
    approval = db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(404, "approval not found")
    approval_service.reject(db, approval, decided_by="user:owner", decision_note=body.note)
    return {"status": "rejected"}
