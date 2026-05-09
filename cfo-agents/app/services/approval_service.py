"""Approval workflow.

Every AgentRecommendation that requires human approval goes here. The handler
for a `suggested_action.type` is only invoked AFTER a user APPROVES.

Action handlers must be idempotent and must write an audit_log entry.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import (
    AgentRecommendation,
    Approval,
    ApprovalStatus,
)
from app.integrations.xero_client import get_xero_client
from app.services.audit_service import write_audit

log = get_logger(__name__)


# ---------- Action handlers ----------
ActionHandler = Callable[[Session, AgentRecommendation, Approval], dict[str, Any]]


def _handle_post_reconciliation(
    session: Session, rec: AgentRecommendation, approval: Approval
) -> dict[str, Any]:
    client = get_xero_client()
    payload = rec.suggested_action.get("payload", {})
    result = client.post_reconciliation(rec.tenant_id, payload)
    write_audit(
        session,
        actor=f"approval:{approval.id}",
        action="POST_RECONCILIATION",
        target_type="reconciliations",
        target_id=payload.get("bank_transaction_id"),
        tenant_id=rec.tenant_id,
        payload=result,
    )
    return result


def _handle_send_followup_email(
    session: Session, rec: AgentRecommendation, approval: Approval
) -> dict[str, Any]:
    # Wired through document_service in MVP - stored, not actually sent.
    from app.services.document_service import save_outbound_email

    body = rec.suggested_action.get("payload", {}).get("body", "")
    to = rec.suggested_action.get("payload", {}).get("to", "")
    doc_id = save_outbound_email(session, tenant_id=rec.tenant_id, to=to, body=body)
    write_audit(
        session,
        actor=f"approval:{approval.id}",
        action="SEND_FOLLOWUP_EMAIL",
        target_type="documents",
        target_id=doc_id,
        tenant_id=rec.tenant_id,
        payload={"to": to},
    )
    return {"status": "queued", "document_id": doc_id}


def _handle_mark_bill_for_payment(
    session: Session, rec: AgentRecommendation, approval: Approval
) -> dict[str, Any]:
    bill_id = rec.suggested_action.get("payload", {}).get("bill_id")
    write_audit(
        session,
        actor=f"approval:{approval.id}",
        action="MARK_BILL_FOR_PAYMENT",
        target_type="bills",
        target_id=bill_id,
        tenant_id=rec.tenant_id,
        payload=rec.suggested_action.get("payload", {}),
    )
    return {"status": "marked", "bill_id": bill_id}


def _handle_generate_board_pack(
    session: Session, rec: AgentRecommendation, approval: Approval
) -> dict[str, Any]:
    from app.services.document_service import render_board_pack

    doc_id = render_board_pack(session, tenant_id=rec.tenant_id, payload=rec.suggested_action.get("payload", {}))
    write_audit(
        session,
        actor=f"approval:{approval.id}",
        action="GENERATE_BOARD_PACK",
        target_type="documents",
        target_id=doc_id,
        tenant_id=rec.tenant_id,
        payload={},
    )
    return {"status": "rendered", "document_id": doc_id}


def _handle_notify_owner(
    session: Session, rec: AgentRecommendation, approval: Approval
) -> dict[str, Any]:
    from app.integrations.n8n_webhooks import fire_webhook

    ok = fire_webhook("notify-owner", rec.suggested_action.get("payload", {}))
    write_audit(
        session,
        actor=f"approval:{approval.id}",
        action="NOTIFY_OWNER",
        target_type="webhooks",
        target_id=None,
        tenant_id=rec.tenant_id,
        payload={"delivered": ok},
    )
    return {"status": "delivered" if ok else "skipped"}


HANDLERS: dict[str, ActionHandler] = {
    "POST_RECONCILIATION": _handle_post_reconciliation,
    "SEND_FOLLOWUP_EMAIL": _handle_send_followup_email,
    "MARK_BILL_FOR_PAYMENT": _handle_mark_bill_for_payment,
    "GENERATE_BOARD_PACK": _handle_generate_board_pack,
    "NOTIFY_OWNER": _handle_notify_owner,
}


# ---------- Public API ----------
def enqueue(session: Session, rec: AgentRecommendation) -> Approval:
    settings = get_settings()
    auto = (
        not rec.requires_human_approval
        and rec.confidence_score >= settings.auto_approve_threshold
        and settings.auto_approve_threshold > 0.0
    )
    approval = Approval(
        tenant_id=rec.tenant_id,
        recommendation_id=rec.id,
        status=ApprovalStatus.AUTO_APPROVED if auto else ApprovalStatus.PENDING,
    )
    session.add(approval)
    session.flush()
    write_audit(
        session,
        actor=f"agent:{rec.agent_name}",
        action="ENQUEUE_APPROVAL",
        target_type="approvals",
        target_id=approval.id,
        tenant_id=rec.tenant_id,
        payload={"task_type": rec.task_type, "auto": auto},
    )
    if auto:
        commit(session, approval, decided_by="system:auto")
    return approval


def commit(
    session: Session,
    approval: Approval,
    *,
    decided_by: str,
    decision_note: str | None = None,
) -> dict[str, Any]:
    """Approve and execute the typed action."""
    if approval.status not in (ApprovalStatus.PENDING, ApprovalStatus.AUTO_APPROVED):
        raise ValueError(f"approval {approval.id} not pending (status={approval.status})")
    rec = approval.recommendation
    action_type = (rec.suggested_action or {}).get("type")
    handler = HANDLERS.get(action_type or "")
    if handler is None:
        raise ValueError(f"no handler for action type {action_type!r}")

    result = handler(session, rec, approval)

    if approval.status != ApprovalStatus.AUTO_APPROVED:
        approval.status = ApprovalStatus.APPROVED
    approval.decided_by = decided_by
    approval.decided_at = datetime.now(timezone.utc)
    approval.decision_note = decision_note
    approval.posted_at = datetime.now(timezone.utc)
    approval.posting_result = result
    session.flush()
    return result


def reject(
    session: Session,
    approval: Approval,
    *,
    decided_by: str,
    decision_note: str | None = None,
) -> None:
    approval.status = ApprovalStatus.REJECTED
    approval.decided_by = decided_by
    approval.decided_at = datetime.now(timezone.utc)
    approval.decision_note = decision_note
    write_audit(
        session,
        actor=decided_by,
        action="REJECT_APPROVAL",
        target_type="approvals",
        target_id=approval.id,
        tenant_id=approval.tenant_id,
        payload={"note": decision_note},
    )
    session.flush()
