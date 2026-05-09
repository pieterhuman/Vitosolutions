"""Base agent class + standard output schema.

Every agent extends `Agent` and returns an `AgentOutput`. The orchestrator
persists the output as an `AgentRecommendation` and enqueues an `Approval`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

from app.db.models import RiskLevel


class SourceRecord(BaseModel):
    table: str
    id: str


class SuggestedAction(BaseModel):
    type: str  # e.g. POST_RECONCILIATION, SEND_FOLLOWUP_EMAIL
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    """Canonical agent output. Mirrors the schema in docs/data_model.md."""

    model_config = ConfigDict(use_enum_values=True)

    agent_name: str
    task_type: str
    summary: str
    recommendation: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    source_records: list[SourceRecord] = Field(default_factory=list)
    reasoning_summary: str
    requires_human_approval: bool = True
    suggested_action: SuggestedAction
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    tenant_id: str
    task_type: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class Agent(ABC):
    """Specialist agent base class."""

    name: str = "base"
    handles: tuple[str, ...] = ()

    @abstractmethod
    def run(self, session: Session, ctx: AgentContext) -> list[AgentOutput]:
        """Produce zero or more recommendations for this context."""
