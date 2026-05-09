"""Repository pattern for database access. Keeps SQL out of agents and services."""

from app.db.repositories.base import BaseRepository
from app.db.repositories.finance import (
    BankTransactionRepository,
    BillRepository,
    ContactRepository,
    InvoiceRepository,
)
from app.db.repositories.platform import (
    AgentRecommendationRepository,
    ApprovalRepository,
    AuditLogRepository,
    ForecastRepository,
)

__all__ = [
    "BaseRepository",
    "BankTransactionRepository",
    "BillRepository",
    "ContactRepository",
    "InvoiceRepository",
    "AgentRecommendationRepository",
    "ApprovalRepository",
    "AuditLogRepository",
    "ForecastRepository",
]
