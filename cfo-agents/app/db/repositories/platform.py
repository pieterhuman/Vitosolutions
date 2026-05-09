from __future__ import annotations

from sqlalchemy import select

from app.db.models import (
    AgentRecommendation,
    Approval,
    ApprovalStatus,
    AuditLog,
    Forecast,
)
from app.db.repositories.base import BaseRepository


class AgentRecommendationRepository(BaseRepository[AgentRecommendation]):
    model = AgentRecommendation

    def recent(self, tenant_id: str, limit: int = 50) -> list[AgentRecommendation]:
        stmt = (
            select(AgentRecommendation)
            .where(AgentRecommendation.tenant_id == tenant_id)
            .order_by(AgentRecommendation.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())


class ApprovalRepository(BaseRepository[Approval]):
    model = Approval

    def pending(self, tenant_id: str) -> list[Approval]:
        stmt = (
            select(Approval)
            .where(Approval.tenant_id == tenant_id)
            .where(Approval.status == ApprovalStatus.PENDING)
            .order_by(Approval.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars())


class AuditLogRepository(BaseRepository[AuditLog]):
    model = AuditLog


class ForecastRepository(BaseRepository[Forecast]):
    model = Forecast

    def latest(self, tenant_id: str, horizon_days: int) -> Forecast | None:
        stmt = (
            select(Forecast)
            .where(Forecast.tenant_id == tenant_id)
            .where(Forecast.horizon_days == horizon_days)
            .order_by(Forecast.created_at.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()
