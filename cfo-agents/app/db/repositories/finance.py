from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.db.models import BankTransaction, Bill, Contact, Invoice
from app.db.repositories.base import BaseRepository


class BankTransactionRepository(BaseRepository[BankTransaction]):
    model = BankTransaction

    def unreconciled(self, tenant_id: str) -> list[BankTransaction]:
        stmt = (
            select(BankTransaction)
            .where(BankTransaction.tenant_id == tenant_id)
            .where(BankTransaction.is_reconciled.is_(False))
            .order_by(BankTransaction.posted_on.desc())
        )
        return list(self.session.execute(stmt).scalars())


class InvoiceRepository(BaseRepository[Invoice]):
    model = Invoice

    def open_invoices(self, tenant_id: str) -> list[Invoice]:
        stmt = (
            select(Invoice)
            .where(Invoice.tenant_id == tenant_id)
            .where(Invoice.amount_due > 0)
            .order_by(Invoice.due_date.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def overdue(self, tenant_id: str, as_of: date) -> list[Invoice]:
        stmt = (
            select(Invoice)
            .where(Invoice.tenant_id == tenant_id)
            .where(Invoice.amount_due > 0)
            .where(Invoice.due_date < as_of)
            .order_by(Invoice.due_date.asc())
        )
        return list(self.session.execute(stmt).scalars())


class BillRepository(BaseRepository[Bill]):
    model = Bill

    def open_bills(self, tenant_id: str) -> list[Bill]:
        stmt = (
            select(Bill)
            .where(Bill.tenant_id == tenant_id)
            .where(Bill.amount_due > 0)
            .order_by(Bill.due_date.asc())
        )
        return list(self.session.execute(stmt).scalars())


class ContactRepository(BaseRepository[Contact]):
    model = Contact

    def by_name(self, tenant_id: str, name: str) -> Contact | None:
        stmt = (
            select(Contact)
            .where(Contact.tenant_id == tenant_id)
            .where(Contact.name == name)
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()
