from app.agents.orchestrator import Orchestrator


def test_reconciliation_dispatch_creates_recommendations(db_session):
    recs = Orchestrator().dispatch(
        db_session, tenant_id="demo", task_type="RECONCILE_BANK_LINE"
    )
    assert recs, "expected at least one recommendation from seed data"
    # Every recommendation needs human approval in MVP.
    assert all(r.requires_human_approval for r in recs)
    # The exact-amount line for INV-001 should pick up a high-confidence match.
    high_conf = [r for r in recs if r.confidence_score >= 0.75]
    assert high_conf, "expected at least one deterministic match"
