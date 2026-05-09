"""Dashboard data endpoints. Used by Streamlit and any other UI."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_tenant_id
from app.db.models import (
    AgentRecommendation,
    Approval,
    ApprovalStatus,
    Bill,
    CashflowSnapshot,
    Forecast,
    Invoice,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    today = date.today()
    cash = db.execute(
        select(CashflowSnapshot)
        .where(CashflowSnapshot.tenant_id == tenant_id)
        .order_by(CashflowSnapshot.captured_on.desc())
        .limit(1)
    ).scalar_one_or_none()

    open_ar = db.execute(
        select(func.coalesce(func.sum(Invoice.amount_due), 0))
        .where(Invoice.tenant_id == tenant_id)
        .where(Invoice.amount_due > 0)
    ).scalar_one()
    overdue_ar = db.execute(
        select(func.coalesce(func.sum(Invoice.amount_due), 0))
        .where(Invoice.tenant_id == tenant_id)
        .where(Invoice.amount_due > 0)
        .where(Invoice.due_date < today)
    ).scalar_one()
    open_ap = db.execute(
        select(func.coalesce(func.sum(Bill.amount_due), 0))
        .where(Bill.tenant_id == tenant_id)
        .where(Bill.amount_due > 0)
    ).scalar_one()

    forecast_30 = db.execute(
        select(Forecast)
        .where(Forecast.tenant_id == tenant_id)
        .where(Forecast.horizon_days == 30)
        .order_by(Forecast.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    forecast_90 = db.execute(
        select(Forecast)
        .where(Forecast.tenant_id == tenant_id)
        .where(Forecast.horizon_days == 90)
        .order_by(Forecast.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    pending_approvals = db.execute(
        select(func.count())
        .select_from(Approval)
        .where(Approval.tenant_id == tenant_id)
        .where(Approval.status == ApprovalStatus.PENDING)
    ).scalar_one()

    return {
        "cash": float(cash.bank_balance) if cash else 0.0,
        "open_ar": float(open_ar),
        "overdue_ar": float(overdue_ar),
        "open_ap": float(open_ap),
        "forecast_30_closing": float(forecast_30.closing_balance) if forecast_30 else None,
        "forecast_90_closing": float(forecast_90.closing_balance) if forecast_90 else None,
        "runway_days": forecast_90.runway_days if forecast_90 else None,
        "pending_approvals": int(pending_approvals),
    }


@router.get("/recommendations")
def recent_recommendations(
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
    limit: int = 25,
) -> list[dict]:
    recs = db.execute(
        select(AgentRecommendation)
        .where(AgentRecommendation.tenant_id == tenant_id)
        .order_by(AgentRecommendation.created_at.desc())
        .limit(limit)
    ).scalars()
    return [
        {
            "id": r.id,
            "agent": r.agent_name,
            "task_type": r.task_type,
            "summary": r.summary,
            "recommendation": r.recommendation,
            "confidence": r.confidence_score,
            "risk": r.risk_level,
            "created_at": r.created_at.isoformat(),
        }
        for r in recs
    ]


@router.get("/forecast/{horizon}")
def forecast_series(
    horizon: int,
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    f = db.execute(
        select(Forecast)
        .where(Forecast.tenant_id == tenant_id)
        .where(Forecast.horizon_days == horizon)
        .order_by(Forecast.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not f:
        return {"horizon": horizon, "series": [], "commentary": "no forecast yet"}
    return {
        "horizon": horizon,
        "opening": float(f.opening_balance),
        "closing": float(f.closing_balance),
        "runway_days": f.runway_days,
        "series": f.series,
        "commentary": f.commentary,
    }
