"""Sync Xero -> normalized snapshots."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_tenant_id, require_perm
from app.core.permissions import Permission
from app.db.models import (
    BankTransaction,
    Bill,
    ChartOfAccount,
    Contact,
    Invoice,
    SyncRun,
    SyncStatus,
)
from app.integrations.xero_client import get_xero_client
from app.services.audit_service import write_audit

router = APIRouter(prefix="/sync", tags=["sync"], dependencies=[Depends(require_perm(Permission.SYNC))])


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.split("T")[0]
    try:
        return date.fromisoformat(s)
    except ValueError:
        # tolerate /Date(.../)/ Xero legacy
        return None


@router.post("/xero")
def sync_xero(
    db: Session = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    client = get_xero_client()
    run = SyncRun(tenant_id=tenant_id, started_at=datetime.now(timezone.utc))
    db.add(run)
    db.flush()
    counts: dict[str, int] = {}
    try:
        # bank transactions
        for row in client.list_bank_transactions(tenant_id):
            db.add(
                BankTransaction(
                    tenant_id=tenant_id,
                    xero_id=row.get("BankTransactionID") or row.get("id"),
                    bank_account_id=row.get("BankAccount", {}).get("AccountID") or row.get("bank_account_id", ""),
                    posted_on=_parse_date(row.get("Date") or row.get("posted_on")) or date.today(),
                    amount=float(row.get("Total") or row.get("amount") or 0),
                    currency=row.get("CurrencyCode") or row.get("currency") or "ZAR",
                    description=row.get("Reference") or row.get("description") or "",
                    counterparty_name=row.get("Contact", {}).get("Name") or row.get("counterparty_name") or "",
                )
            )
        counts["bank_transactions"] = len(client.list_bank_transactions(tenant_id))

        for row in client.list_invoices(tenant_id):
            db.add(
                Invoice(
                    tenant_id=tenant_id,
                    xero_id=row.get("InvoiceID") or row.get("id"),
                    contact_id=row.get("Contact", {}).get("ContactID") or row.get("contact_id"),
                    invoice_number=row.get("InvoiceNumber") or row.get("invoice_number") or "",
                    issue_date=_parse_date(row.get("Date") or row.get("issue_date")) or date.today(),
                    due_date=_parse_date(row.get("DueDate") or row.get("due_date")) or date.today(),
                    total=float(row.get("Total") or row.get("total") or 0),
                    amount_due=float(row.get("AmountDue") or row.get("amount_due") or 0),
                    currency=row.get("CurrencyCode") or row.get("currency") or "ZAR",
                    status=row.get("Status") or row.get("status") or "AUTHORISED",
                )
            )
        counts["invoices"] = len(client.list_invoices(tenant_id))

        for row in client.list_bills(tenant_id):
            db.add(
                Bill(
                    tenant_id=tenant_id,
                    xero_id=row.get("InvoiceID") or row.get("id"),
                    contact_id=row.get("Contact", {}).get("ContactID") or row.get("contact_id"),
                    bill_number=row.get("InvoiceNumber") or row.get("bill_number") or "",
                    issue_date=_parse_date(row.get("Date") or row.get("issue_date")) or date.today(),
                    due_date=_parse_date(row.get("DueDate") or row.get("due_date")) or date.today(),
                    total=float(row.get("Total") or row.get("total") or 0),
                    amount_due=float(row.get("AmountDue") or row.get("amount_due") or 0),
                    currency=row.get("CurrencyCode") or row.get("currency") or "ZAR",
                    status=row.get("Status") or row.get("status") or "AUTHORISED",
                )
            )
        counts["bills"] = len(client.list_bills(tenant_id))

        for row in client.list_contacts(tenant_id):
            db.add(
                Contact(
                    tenant_id=tenant_id,
                    xero_id=row.get("ContactID") or row.get("id"),
                    name=row.get("Name") or row.get("name") or "",
                    is_customer=bool(row.get("IsCustomer", row.get("is_customer", "false"))) if isinstance(row.get("IsCustomer", row.get("is_customer", "false")), bool) else str(row.get("IsCustomer") or row.get("is_customer") or "").lower() == "true",
                    is_supplier=str(row.get("IsSupplier") or row.get("is_supplier") or "").lower() == "true",
                    email=row.get("EmailAddress") or row.get("email"),
                )
            )
        counts["contacts"] = len(client.list_contacts(tenant_id))

        for row in client.list_chart_of_accounts(tenant_id):
            db.add(
                ChartOfAccount(
                    tenant_id=tenant_id,
                    xero_id=row.get("AccountID") or row.get("id"),
                    code=row.get("Code") or row.get("code") or "",
                    name=row.get("Name") or row.get("name") or "",
                    type=row.get("Type") or row.get("type") or "",
                    tax_type=row.get("TaxType") or row.get("tax_type"),
                )
            )
        counts["chart_of_accounts"] = len(client.list_chart_of_accounts(tenant_id))

        run.counts = counts
        run.status = SyncStatus.OK
        run.finished_at = datetime.now(timezone.utc)
        write_audit(
            db,
            actor="system",
            action="SYNC_XERO",
            target_type="sync_runs",
            target_id=run.id,
            tenant_id=tenant_id,
            payload=counts,
        )
        return {"status": "ok", "counts": counts, "sync_run_id": run.id}
    except Exception as e:
        run.status = SyncStatus.FAILED
        run.error = str(e)
        run.finished_at = datetime.now(timezone.utc)
        raise
