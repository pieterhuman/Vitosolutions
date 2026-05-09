"""SQLAlchemy ORM models for the normalized finance data layer + platform tables.

Source-of-truth tables (Xero snapshots) carry `xero_id`, `tenant_id`,
`synced_at`, and `version`. Updates write a NEW row (versioned) — the previous
row is kept. This is enforced by repositories, not by the ORM.

Platform tables (`agent_recommendations`, `approvals`, `audit_logs`, etc.)
are append-only by convention except for status fields on `approvals`.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------- Enums ----------
class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    AUTO_APPROVED = "AUTO_APPROVED"
    EXPIRED = "EXPIRED"


class SyncStatus(str, enum.Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


# ---------- Source-of-truth (Xero snapshots) ----------
class XeroConnection(Base):
    __tablename__ = "xero_connections"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    tenant_name: Mapped[str] = mapped_column(String, nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = (UniqueConstraint("xero_id", "version"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    xero_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    bank_account_id: Mapped[str] = mapped_column(String, index=True)
    posted_on: Mapped[datetime] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="ZAR")
    description: Mapped[str] = mapped_column(Text, default="")
    counterparty_name: Mapped[str] = mapped_column(String, default="")
    is_reconciled: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("xero_id", "version"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    xero_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    contact_id: Mapped[str | None] = mapped_column(String, index=True)
    invoice_number: Mapped[str] = mapped_column(String, index=True)
    issue_date: Mapped[datetime] = mapped_column(Date)
    due_date: Mapped[datetime] = mapped_column(Date, index=True)
    total: Mapped[float] = mapped_column(Numeric(18, 2))
    amount_due: Mapped[float] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="ZAR")
    status: Mapped[str] = mapped_column(String, default="AUTHORISED")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (UniqueConstraint("xero_id", "version"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    xero_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    contact_id: Mapped[str | None] = mapped_column(String, index=True)
    bill_number: Mapped[str] = mapped_column(String, index=True)
    issue_date: Mapped[datetime] = mapped_column(Date)
    due_date: Mapped[datetime] = mapped_column(Date, index=True)
    total: Mapped[float] = mapped_column(Numeric(18, 2))
    amount_due: Mapped[float] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="ZAR")
    status: Mapped[str] = mapped_column(String, default="AUTHORISED")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("xero_id", "version"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    xero_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String, index=True)
    is_customer: Mapped[bool] = mapped_column(Boolean, default=False)
    is_supplier: Mapped[bool] = mapped_column(Boolean, default=False)
    email: Mapped[str | None] = mapped_column(String)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChartOfAccount(Base):
    __tablename__ = "chart_of_accounts"
    __table_args__ = (UniqueConstraint("xero_id", "version"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    xero_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    code: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)  # REVENUE, EXPENSE, etc
    tax_type: Mapped[str | None] = mapped_column(String)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Journal(Base):
    __tablename__ = "journals"
    __table_args__ = (UniqueConstraint("xero_id", "version"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    xero_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    posted_on: Mapped[datetime] = mapped_column(Date)
    narration: Mapped[str] = mapped_column(Text, default="")
    lines: Mapped[dict] = mapped_column(JSON, default=dict)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------- Platform tables ----------
class Reconciliation(Base):
    __tablename__ = "reconciliations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    bank_transaction_id: Mapped[str] = mapped_column(String, index=True)
    matched_invoice_id: Mapped[str | None] = mapped_column(String)
    matched_bill_id: Mapped[str | None] = mapped_column(String)
    suggested_account_code: Mapped[str | None] = mapped_column(String)
    suggested_tax_type: Mapped[str | None] = mapped_column(String)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="SUGGESTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentRecommendation(Base):
    __tablename__ = "agent_recommendations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    agent_name: Mapped[str] = mapped_column(String, index=True)
    task_type: Mapped[str] = mapped_column(String, index=True)
    summary: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    confidence_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[RiskLevel] = mapped_column(Enum(RiskLevel))
    source_records: Mapped[list] = mapped_column(JSON, default=list)
    reasoning_summary: Mapped[str] = mapped_column(Text)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    suggested_action: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    approvals: Mapped[list["Approval"]] = relationship(back_populates="recommendation")


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    recommendation_id: Mapped[str] = mapped_column(
        String, ForeignKey("agent_recommendations.id"), index=True
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus), default=ApprovalStatus.PENDING, index=True
    )
    decided_by: Mapped[str | None] = mapped_column(String)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posting_result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    recommendation: Mapped[AgentRecommendation] = relationship(back_populates="approvals")


class Forecast(Base):
    __tablename__ = "forecasts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer)
    opening_balance: Mapped[float] = mapped_column(Numeric(18, 2))
    closing_balance: Mapped[float] = mapped_column(Numeric(18, 2))
    runway_days: Mapped[int | None] = mapped_column(Integer)
    series: Mapped[list] = mapped_column(JSON)  # [{date, inflow, outflow, balance}]
    commentary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CashflowSnapshot(Base):
    __tablename__ = "cashflow_snapshots"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    captured_on: Mapped[datetime] = mapped_column(Date, index=True)
    bank_balance: Mapped[float] = mapped_column(Numeric(18, 2))
    open_ar: Mapped[float] = mapped_column(Numeric(18, 2))
    open_ap: Mapped[float] = mapped_column(Numeric(18, 2))
    vat_reserve: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True)
    actor: Mapped[str] = mapped_column(String, index=True)  # 'system', 'agent:recon', 'user:abc'
    action: Mapped[str] = mapped_column(String, index=True)
    target_type: Mapped[str] = mapped_column(String)
    target_id: Mapped[str | None] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class FinanceRule(Base):
    __tablename__ = "finance_rules"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    rule_type: Mapped[str] = mapped_column(String)  # MERCHANT_NORMALIZE, ACCOUNT_CODE, VAT, ...
    pattern: Mapped[str] = mapped_column(String)
    action: Mapped[dict] = mapped_column(JSON)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CompanySettings(Base):
    __tablename__ = "company_settings"
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(3), default="ZAR")
    vat_rate: Mapped[float] = mapped_column(Float, default=0.15)
    vat_reserve_pct: Mapped[float] = mapped_column(Float, default=0.15)
    payroll_monthly: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    operating_reserve_target_days: Mapped[int] = mapped_column(Integer, default=90)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), default=SyncStatus.OK)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


def create_all() -> None:
    """Create all tables on the configured engine. Used in demo mode."""
    from app.db.session import get_engine

    Base.metadata.create_all(get_engine())
