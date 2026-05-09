from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def write_audit(
    session: Session,
    *,
    actor: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    tenant_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        tenant_id=tenant_id,
        payload=payload or {},
    )
    session.add(entry)
    session.flush()
    return entry
