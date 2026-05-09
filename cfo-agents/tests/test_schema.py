from app.agents.base import AgentOutput, SourceRecord, SuggestedAction
from app.db.models import RiskLevel


def test_agent_output_minimum_fields():
    o = AgentOutput(
        agent_name="x",
        task_type="t",
        summary="s",
        recommendation="r",
        confidence_score=0.5,
        risk_level=RiskLevel.LOW,
        source_records=[SourceRecord(table="invoices", id="i1")],
        reasoning_summary="why",
        suggested_action=SuggestedAction(type="NOTIFY_OWNER"),
    )
    j = o.model_dump()
    for key in (
        "agent_name",
        "task_type",
        "summary",
        "recommendation",
        "confidence_score",
        "risk_level",
        "source_records",
        "reasoning_summary",
        "requires_human_approval",
        "suggested_action",
        "created_at",
    ):
        assert key in j
