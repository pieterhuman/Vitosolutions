"""Xero integration. Real OAuth2 + read endpoints; write paths are gated.

In demo mode (`CFO_DEMO_MODE=true`) `FakeXeroClient` is returned, which
serves data from `seed_data/`. This keeps the rest of the codebase
ignorant of which client is in use.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_API_BASE = "https://api.xero.com/api.xro/2.0"


@dataclass
class XeroToken:
    access_token: str
    refresh_token: str
    expires_at: datetime
    tenant_id: str
    tenant_name: str


class XeroClient(Protocol):
    def list_bank_transactions(self, tenant_id: str) -> list[dict[str, Any]]: ...
    def list_invoices(self, tenant_id: str) -> list[dict[str, Any]]: ...
    def list_bills(self, tenant_id: str) -> list[dict[str, Any]]: ...
    def list_contacts(self, tenant_id: str) -> list[dict[str, Any]]: ...
    def list_chart_of_accounts(self, tenant_id: str) -> list[dict[str, Any]]: ...
    def post_reconciliation(self, tenant_id: str, payload: dict) -> dict: ...


# ---------- Real client ----------
class RealXeroClient:
    def __init__(self, token: XeroToken):
        self.token = token

    @staticmethod
    def authorize_url(state: str) -> str:
        s = get_settings()
        params = {
            "response_type": "code",
            "client_id": s.xero_client_id,
            "redirect_uri": s.xero_redirect_uri,
            "scope": s.xero_scopes,
            "state": state,
        }
        return f"{XERO_AUTH_URL}?{urlencode(params)}"

    @staticmethod
    def exchange_code(code: str) -> XeroToken:
        s = get_settings()
        with httpx.Client(timeout=20) as c:
            r = c.post(
                XERO_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": s.xero_redirect_uri,
                },
                auth=(s.xero_client_id, s.xero_client_secret),
            )
            r.raise_for_status()
            tok = r.json()
            # Resolve tenant
            tr = c.get(
                "https://api.xero.com/connections",
                headers={"Authorization": f"Bearer {tok['access_token']}"},
            )
            tr.raise_for_status()
            tenants = tr.json()
        if not tenants:
            raise RuntimeError("No Xero tenants connected")
        t0 = tenants[0]
        return XeroToken(
            access_token=tok["access_token"],
            refresh_token=tok["refresh_token"],
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=tok["expires_in"] - 60),
            tenant_id=t0["tenantId"],
            tenant_name=t0["tenantName"],
        )

    def _refresh_if_needed(self) -> None:
        if datetime.now(timezone.utc) < self.token.expires_at:
            return
        s = get_settings()
        with httpx.Client(timeout=20) as c:
            r = c.post(
                XERO_TOKEN_URL,
                data={"grant_type": "refresh_token", "refresh_token": self.token.refresh_token},
                auth=(s.xero_client_id, s.xero_client_secret),
            )
            r.raise_for_status()
            tok = r.json()
        self.token.access_token = tok["access_token"]
        self.token.refresh_token = tok["refresh_token"]
        self.token.expires_at = datetime.now(timezone.utc) + timedelta(seconds=tok["expires_in"] - 60)

    def _get(self, path: str, tenant_id: str, params: dict | None = None) -> dict:
        self._refresh_if_needed()
        with httpx.Client(timeout=30) as c:
            r = c.get(
                f"{XERO_API_BASE}{path}",
                headers={
                    "Authorization": f"Bearer {self.token.access_token}",
                    "Xero-tenant-id": tenant_id,
                    "Accept": "application/json",
                },
                params=params or {},
            )
            r.raise_for_status()
            return r.json()

    def list_bank_transactions(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._get("/BankTransactions", tenant_id).get("BankTransactions", [])

    def list_invoices(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._get("/Invoices", tenant_id, {"where": 'Type=="ACCREC"'}).get("Invoices", [])

    def list_bills(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._get("/Invoices", tenant_id, {"where": 'Type=="ACCPAY"'}).get("Invoices", [])

    def list_contacts(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._get("/Contacts", tenant_id).get("Contacts", [])

    def list_chart_of_accounts(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._get("/Accounts", tenant_id).get("Accounts", [])

    def post_reconciliation(self, tenant_id: str, payload: dict) -> dict:
        # Real reconciliation in Xero is a BankTransaction or ManualJournal POST.
        # Wired up post-MVP after approval flow is hardened.
        log.info("xero.post_reconciliation.skipped", tenant_id=tenant_id, payload=payload)
        return {"status": "skipped_in_mvp", "echo": payload}


# ---------- Fake / demo client ----------
SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data"


def _read_csv(name: str) -> list[dict[str, Any]]:
    path = SEED_DIR / name
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


class FakeXeroClient:
    def __init__(self):
        self._cache: dict[str, list[dict[str, Any]]] = {}

    def _load(self, name: str) -> list[dict[str, Any]]:
        if name not in self._cache:
            self._cache[name] = _read_csv(name)
        return self._cache[name]

    def list_bank_transactions(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._load("bank_transactions.csv")

    def list_invoices(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._load("invoices.csv")

    def list_bills(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._load("bills.csv")

    def list_contacts(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._load("contacts.csv")

    def list_chart_of_accounts(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._load("chart_of_accounts.csv")

    def post_reconciliation(self, tenant_id: str, payload: dict) -> dict:
        log.info("fake_xero.post_reconciliation", tenant_id=tenant_id, payload=payload)
        return {"status": "demo_ok", "echo": payload, "posted_at": date.today().isoformat()}


def get_xero_client(token: XeroToken | None = None) -> XeroClient:
    """Return real or fake client depending on demo mode."""
    if get_settings().demo_mode:
        return FakeXeroClient()
    if token is None:
        raise RuntimeError("Real XeroClient requires a XeroToken")
    return RealXeroClient(token)
