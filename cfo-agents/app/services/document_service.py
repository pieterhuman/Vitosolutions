"""Document service: outbound emails and board packs.

In MVP we don't actually send mail. We persist the rendered content with a
PII flag, log it, and return the document id.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.core.logging import get_logger

log = get_logger(__name__)


# In-memory document store for the MVP. Swap for a `documents` table later.
_DOCS: dict[str, dict] = {}


def save_outbound_email(session: Session, *, tenant_id: str, to: str, body: str) -> str:
    doc_id = str(uuid.uuid4())
    _DOCS[doc_id] = {
        "id": doc_id,
        "tenant_id": tenant_id,
        "kind": "email",
        "to": to,
        "body": body,
        "pii": True,
        "queued_at": date.today().isoformat(),
    }
    log.info("doc.email.queued", document_id=doc_id, tenant_id=tenant_id)
    return doc_id


def render_board_pack(session: Session, *, tenant_id: str, payload: dict) -> str:
    doc_id = str(uuid.uuid4())
    md = _board_pack_markdown(payload)
    _DOCS[doc_id] = {
        "id": doc_id,
        "tenant_id": tenant_id,
        "kind": "board_pack",
        "format": "markdown",
        "content": md,
        "rendered_at": date.today().isoformat(),
    }
    log.info("doc.board_pack.rendered", document_id=doc_id, tenant_id=tenant_id)
    return doc_id


def get_document(doc_id: str) -> dict | None:
    return _DOCS.get(doc_id)


def _board_pack_markdown(payload: dict) -> str:
    bullets = "\n".join(f"- {line}" for line in payload.get("highlights", []))
    return f"""# Monthly CFO Report — {payload.get('period', '')}

## Headline
{payload.get('headline', '')}

## Highlights
{bullets or '_(none)_'}

## Numbers
- Revenue: {payload.get('revenue', 'n/a')}
- Cash: {payload.get('cash', 'n/a')}
- Runway: {payload.get('runway_days', 'n/a')} days
- AR: {payload.get('ar', 'n/a')}
- AP: {payload.get('ap', 'n/a')}
- Gross margin: {payload.get('gross_margin', 'n/a')}

## Risks
{payload.get('risks_md', '_(none)_')}

## Recommendations
{payload.get('recommendations_md', '_(none)_')}
"""
