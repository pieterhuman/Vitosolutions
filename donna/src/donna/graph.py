"""Microsoft Graph client.

Auth (hard constraint 2): Managed Identity exchanging a federated
credential for an app-registration token. No client secrets anywhere.
The Function App's user-assigned managed identity is registered as a
federated identity credential on the single-tenant app registration;
azure-identity's ClientAssertionCredential performs the exchange.

Application permissions requested (hard constraint 5): Mail.Read,
Mail.Send, Calendars.Read, Tasks.Read.All, User.Read.All — and an
Exchange Application Access Policy limits them to sg-donna-monitored
(see OPERATOR.md). This client only ever writes via sendMail from the
service mailbox.

Throttling: honors Retry-After on 429/503. Requests are serial per
mailbox, well under the 4-concurrent-per-mailbox cap.
"""
from __future__ import annotations

import time
from datetime import datetime

import requests

from .errors import CursorGone
from .telemetry import get_logger

log = get_logger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "https://graph.microsoft.com/.default"
EXCHANGE_AUDIENCE = "api://AzureADTokenExchange/.default"

# Minimal field set; internetMessageHeaders is required for the
# auto-reply and bulk-mail rules.
SELECT_FIELDS = ",".join([
    "id", "internetMessageId", "conversationId", "subject", "from",
    "sender", "toRecipients", "ccRecipients", "receivedDateTime",
    "sentDateTime", "internetMessageHeaders",
])

FOLDER_IDS = {"inbox": "inbox", "sentitems": "sentitems"}

MAX_RETRIES = 6


def build_credential(tenant_id: str, client_id: str,
                     mi_client_id: str | None):
    """ClientAssertionCredential fed by the managed identity token."""
    from azure.identity import ClientAssertionCredential, \
        ManagedIdentityCredential

    mi = ManagedIdentityCredential(client_id=mi_client_id) \
        if mi_client_id else ManagedIdentityCredential()

    def assertion() -> str:
        return mi.get_token(EXCHANGE_AUDIENCE).token

    return ClientAssertionCredential(tenant_id, client_id, assertion)


class GraphClient:
    def __init__(self, credential, session: requests.Session | None = None):
        self._credential = credential
        self._session = session or requests.Session()

    def _headers(self) -> dict:
        token = self._credential.get_token(SCOPE).token
        return {"Authorization": f"Bearer {token}"}

    def _get(self, url: str, params: dict | None = None) -> dict:
        for attempt in range(MAX_RETRIES):
            resp = self._session.get(url, params=params,
                                     headers=self._headers(), timeout=60)
            if resp.status_code == 410:
                raise CursorGone(url.split("?")[0])
            if resp.status_code in (429, 503):
                delay = int(resp.headers.get("Retry-After", "5"))
                log.info("graph throttled status=%d retry_after=%d",
                         resp.status_code, delay)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("graph retry budget exhausted")

    # -- surface used by the jobs (mirrored by tests' FakeGraph) ----------

    def delta_messages(self, upn: str, folder: str,
                       delta_link: str | None) -> tuple[list[dict], str]:
        if delta_link:
            url, params = delta_link, None
        else:
            url = (f"{GRAPH}/users/{upn}/mailFolders/"
                   f"{FOLDER_IDS[folder]}/messages/delta")
            params = {"$select": SELECT_FIELDS, "$top": "50"}
        messages: list[dict] = []
        while True:
            page = self._get(url, params)
            params = None
            messages.extend(m for m in page.get("value", [])
                            if "@removed" not in m)
            if "@odata.nextLink" in page:
                url = page["@odata.nextLink"]
                continue
            return messages, page["@odata.deltaLink"]

    def calendar_view(self, upn: str, start: datetime,
                      end: datetime) -> list[dict]:
        page = self._get(
            f"{GRAPH}/users/{upn}/calendarView",
            {"startDateTime": start.isoformat(),
             "endDateTime": end.isoformat(),
             "$select": "subject,start,end,location",
             "$orderby": "start/dateTime", "$top": "25"})
        return [
            {"subject": ev.get("subject", ""),
             "start": ev.get("start", {}).get("dateTime", "")[11:16]}
            for ev in page.get("value", [])
        ]

    def tasks_due(self, upn: str, today: datetime) -> list[dict]:
        cutoff = today.strftime("%Y-%m-%dT23:59:59")
        lists = self._get(f"{GRAPH}/users/{upn}/todo/lists").get("value", [])
        due: list[dict] = []
        for lst in lists:
            page = self._get(
                f"{GRAPH}/users/{upn}/todo/lists/{lst['id']}/tasks",
                {"$filter": ("status ne 'completed' and "
                             f"dueDateTime/dateTime le '{cutoff}'"),
                 "$top": "50"})
            due.extend({"title": t.get("title", "")}
                       for t in page.get("value", []))
        return due

    def planner_overdue(self, upn: str, now: datetime) -> list[dict]:
        """Planner tasks assigned to the user, incomplete and past due.
        Covered by the Tasks.Read.All application permission."""
        cutoff = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        page = self._get(f"{GRAPH}/users/{upn}/planner/tasks")
        plan_titles: dict[str, str] = {}
        overdue: list[dict] = []
        for task in page.get("value", []):
            due = task.get("dueDateTime")
            if not due or task.get("percentComplete", 0) >= 100:
                continue
            if due >= cutoff:
                continue
            plan_id = task.get("planId", "")
            if plan_id and plan_id not in plan_titles:
                try:
                    plan = self._get(f"{GRAPH}/planner/plans/{plan_id}")
                    plan_titles[plan_id] = plan.get("title", "")
                except Exception:
                    plan_titles[plan_id] = ""
            overdue.append({"title": task.get("title", ""),
                            "plan": plan_titles.get(plan_id, ""),
                            "due": due[:10]})
        return sorted(overdue, key=lambda t: t["due"])

    def send_mail(self, *, from_upn: str, to_upn: str, subject: str,
                  html_body: str) -> None:
        resp = self._session.post(
            f"{GRAPH}/users/{from_upn}/sendMail",
            headers=self._headers(),
            json={"message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html_body},
                "toRecipients": [
                    {"emailAddress": {"address": to_upn}}],
            }, "saveToSentItems": True},
            timeout=60)
        resp.raise_for_status()
