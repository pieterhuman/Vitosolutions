"""Seed the database from CSVs in seed_data/.

Used in demo mode (auto-called from app.main) and exposed as a CLI:

    python -m scripts.seed_local
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import (
    BankTransaction,
    Bill,
    CashflowSnapshot,
    ChartOfAccount,
    CompanySettings,
    Contact,
    Invoice,
    create_all,
)
from app.db.session import session_scope

SEED_DIR = Path(__file__).resolve().parents[1] / "seed_data"


def _bool(v: str) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def _date(s: str) -> date:
    return date.fromisoformat(s)


def _read(name: str) -> list[dict[str, str]]:
    with (SEED_DIR / name).open() as f:
        return list(csv.DictReader(f))


def seed_into_session(session: Session, *, tenant_id: str = "demo") -> None:
    # Already seeded?
    existing = session.query(Contact).filter(Contact.tenant_id == tenant_id).count()
    if existing:
        return

    for row in _read("contacts.csv"):
        session.add(
            Contact(
                tenant_id=tenant_id,
                xero_id=row["id"],
                name=row["name"],
                is_customer=_bool(row["is_customer"]),
                is_supplier=_bool(row["is_supplier"]),
                email=row.get("email") or None,
            )
        )

    for row in _read("chart_of_accounts.csv"):
        session.add(
            ChartOfAccount(
                tenant_id=tenant_id,
                xero_id=row["id"],
                code=row["code"],
                name=row["name"],
                type=row["type"],
                tax_type=row.get("tax_type"),
            )
        )

    contacts_by_xid = {c.xero_id: c.id for c in session.query(Contact).filter_by(tenant_id=tenant_id).all()}

    for row in _read("invoices.csv"):
        session.add(
            Invoice(
                tenant_id=tenant_id,
                xero_id=row["id"],
                contact_id=contacts_by_xid.get(row["contact_id"]),
                invoice_number=row["invoice_number"],
                issue_date=_date(row["issue_date"]),
                due_date=_date(row["due_date"]),
                total=float(row["total"]),
                amount_due=float(row["amount_due"]),
                currency=row["currency"],
                status=row["status"],
            )
        )

    for row in _read("bills.csv"):
        session.add(
            Bill(
                tenant_id=tenant_id,
                xero_id=row["id"],
                contact_id=contacts_by_xid.get(row["contact_id"]),
                bill_number=row["bill_number"],
                issue_date=_date(row["issue_date"]),
                due_date=_date(row["due_date"]),
                total=float(row["total"]),
                amount_due=float(row["amount_due"]),
                currency=row["currency"],
                status=row["status"],
            )
        )

    for row in _read("bank_transactions.csv"):
        session.add(
            BankTransaction(
                tenant_id=tenant_id,
                xero_id=row["id"],
                bank_account_id=row["bank_account_id"],
                posted_on=_date(row["posted_on"]),
                amount=float(row["amount"]),
                currency=row["currency"],
                description=row["description"],
                counterparty_name=row["counterparty_name"],
                is_reconciled=_bool(row["is_reconciled"]),
            )
        )

    session.add(
        CompanySettings(
            tenant_id=tenant_id,
            base_currency="ZAR",
            vat_rate=0.15,
            vat_reserve_pct=0.15,
            payroll_monthly=210000.0,
            operating_reserve_target_days=90,
            updated_at=datetime.now(timezone.utc),
        )
    )

    session.add(
        CashflowSnapshot(
            tenant_id=tenant_id,
            captured_on=date.today(),
            bank_balance=480_000.0,
            open_ar=0.0,
            open_ap=0.0,
            vat_reserve=30_000.0,
        )
    )


def main() -> None:
    create_all()
    with session_scope() as s:
        seed_into_session(s)
    print("seeded.")


if __name__ == "__main__":
    main()
