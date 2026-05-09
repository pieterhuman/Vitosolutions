from app.agents.orchestrator import Orchestrator
from app.db.models import Approval, ApprovalStatus, AuditLog
from app.services import approval_service


def test_full_recon_approval_flow(db_session):
    recs = Orchestrator().dispatch(db_session, tenant_id="demo", task_type="RECONCILE_BANK_LINE")
    assert recs

    # Pending approvals should exist for those that require approval.
    pending = (
        db_session.query(Approval)
        .filter_by(tenant_id="demo", status=ApprovalStatus.PENDING)
        .all()
    )
    assert pending

    a = pending[0]
    result = approval_service.commit(db_session, a, decided_by="user:test", decision_note="ok")
    assert result.get("status") in ("demo_ok", "skipped_in_mvp")
    db_session.refresh(a)
    assert a.status == ApprovalStatus.APPROVED
    assert a.decided_by == "user:test"
    assert a.posted_at is not None

    # Audit log should have entries for DISPATCH, ENQUEUE_APPROVAL, POST_RECONCILIATION.
    actions = {row.action for row in db_session.query(AuditLog).all()}
    assert "DISPATCH" in actions
    assert "ENQUEUE_APPROVAL" in actions
    assert "POST_RECONCILIATION" in actions


def test_reject_flow(db_session):
    Orchestrator().dispatch(db_session, tenant_id="demo", task_type="RECONCILE_BANK_LINE")
    a = (
        db_session.query(Approval)
        .filter_by(tenant_id="demo", status=ApprovalStatus.PENDING)
        .first()
    )
    approval_service.reject(db_session, a, decided_by="user:test", decision_note="not now")
    db_session.refresh(a)
    assert a.status == ApprovalStatus.REJECTED
