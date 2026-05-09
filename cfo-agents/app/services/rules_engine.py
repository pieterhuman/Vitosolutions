"""Deterministic rules. Run BEFORE any AI reasoning.

The engine answers two questions cheaply and predictably:
  1. Can we map a bank line to a known invoice / bill outright? (exact-match
     reconciliation)
  2. Should we apply a normalization (e.g. 'AWS  USA' -> 'Amazon Web Services')
     or a fixed account-code suggestion?

If a deterministic match exists, the agent uses it and skips the Claude call.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.db.models import Bill, Invoice


# ---------- Merchant normalisation ----------
_NORMALIZE: list[tuple[re.Pattern[str], str]] = [
    # Most specific first so AWS isn't shadowed by the broader Amazon pattern.
    (re.compile(r"(?i)\baws\b|amazon\s*web\s*services"), "Amazon Web Services"),
    (re.compile(r"(?i)\bamzn\b|amazon"), "Amazon"),
    (re.compile(r"(?i)\buber\b"), "Uber"),
    (re.compile(r"(?i)\bgoogle\s*(workspace|cloud)?"), "Google"),
    (re.compile(r"(?i)\bmicrosoft|azure\b"), "Microsoft"),
    (re.compile(r"(?i)\bslack\b"), "Slack"),
    (re.compile(r"(?i)\bxero\b"), "Xero"),
    (re.compile(r"(?i)\bcheckers|woolworths|pick\s*n\s*pay\b"), "Groceries"),
]


def normalize_merchant(raw: str) -> str:
    s = unicodedata.normalize("NFKD", raw or "").strip()
    for pat, repl in _NORMALIZE:
        if pat.search(s):
            return repl
    # Strip city/state suffixes like "  USA", "  GB", trailing dates.
    s = re.sub(r"\s+(USA|US|UK|GB|ZA|EU)\s*$", "", s)
    s = re.sub(r"\s+\d{2,4}-\d{2}-\d{2}.*$", "", s)
    return s.strip().title()


# ---------- Account-code suggestion ----------
_ACCOUNT_CODE: list[tuple[re.Pattern[str], tuple[str, str]]] = [
    (re.compile(r"(?i)aws|google\s*cloud|azure|digitalocean"), ("420", "Hosting & SaaS")),
    (re.compile(r"(?i)slack|notion|figma|github|linear"), ("420", "Hosting & SaaS")),
    (re.compile(r"(?i)uber|bolt|taxi"), ("493", "Travel")),
    (re.compile(r"(?i)flight|airline|kulula|ba\.com|emirates"), ("493", "Travel")),
    (re.compile(r"(?i)hotel|airbnb|booking\.com"), ("493", "Travel")),
    (re.compile(r"(?i)bank\s*charges?|fee"), ("404", "Bank Fees")),
    (re.compile(r"(?i)salar|payroll|wages"), ("477", "Wages & Salaries")),
    (re.compile(r"(?i)vat\b|sars\b"), ("820", "VAT Payable")),
]


def suggest_account_code(description: str) -> tuple[str, str] | None:
    for pat, code in _ACCOUNT_CODE:
        if pat.search(description or ""):
            return code
    return None


# ---------- Exact-match reconciliation ----------
@dataclass
class ExactMatch:
    invoice_id: str | None = None
    bill_id: str | None = None
    confidence: float = 0.0
    reason: str = ""


def match_bank_line(
    *,
    amount: float,
    description: str,
    open_invoices: list[Invoice],
    open_bills: list[Bill],
) -> ExactMatch | None:
    """Match a bank line to an invoice (inflow) or bill (outflow).

    Strategy:
      - inflow (amount > 0)  -> invoices.amount_due == amount
      - outflow (amount < 0) -> bills.amount_due == abs(amount)
      - tighten with description containing invoice/bill number
    """
    desc = (description or "").lower()
    if amount >= 0:
        for inv in open_invoices:
            if abs(float(inv.amount_due) - amount) < 0.01:
                conf = 0.95 if inv.invoice_number.lower() in desc else 0.75
                return ExactMatch(invoice_id=inv.id, confidence=conf, reason="amount match")
    else:
        target = abs(amount)
        for b in open_bills:
            if abs(float(b.amount_due) - target) < 0.01:
                conf = 0.95 if b.bill_number.lower() in desc else 0.75
                return ExactMatch(bill_id=b.id, confidence=conf, reason="amount match")
    return None


# ---------- Duplicate bill detection ----------
def find_duplicate_bills(bills: list[Bill]) -> list[tuple[Bill, Bill]]:
    pairs: list[tuple[Bill, Bill]] = []
    for i, a in enumerate(bills):
        for b in bills[i + 1 :]:
            if a.contact_id and a.contact_id == b.contact_id and float(a.total) == float(b.total):
                # Same supplier + same total within 7 days -> likely dup.
                if abs((a.issue_date - b.issue_date).days) <= 7:
                    pairs.append((a, b))
    return pairs
