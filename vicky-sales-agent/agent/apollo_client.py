"""Thin Apollo.io REST client with retries and rate-limit awareness.

Mirrors the Apollo connector's tool surface so the same operations can be
driven either from this code (headless daily loop, APOLLO_API_KEY) or
interactively through the Apollo MCP connector in a Claude session.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger("vicky.apollo")

BASE = "https://api.apollo.io/api/v1"
MAX_RETRIES = 4
BACKOFF = 2.0  # seconds, doubles per retry


class ApolloError(RuntimeError):
    pass


class ApolloClient:
    def __init__(self, api_key: str, min_interval: float = 0.6):
        if not api_key:
            raise ApolloError("APOLLO_API_KEY is not set")
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        })
        self.min_interval = min_interval  # simple client-side throttle
        self._last_call = 0.0

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f"{BASE}/{path.lstrip('/')}"
        for attempt in range(MAX_RETRIES + 1):
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

            resp = self.session.request(method, url, timeout=60, **kwargs)
            if resp.status_code == 429:
                delay = float(resp.headers.get("Retry-After", BACKOFF * 2**attempt))
                log.warning("Apollo 429 on %s; sleeping %.1fs", path, delay)
                time.sleep(delay)
                continue
            if resp.status_code >= 500 and attempt < MAX_RETRIES:
                delay = BACKOFF * 2**attempt
                log.warning("Apollo %s on %s; retry in %.1fs",
                            resp.status_code, path, delay)
                time.sleep(delay)
                continue
            if not resp.ok:
                raise ApolloError(f"{method} {path} -> {resp.status_code}: "
                                  f"{resp.text[:500]}")
            return resp.json() if resp.text else {}
        raise ApolloError(f"{method} {path}: retries exhausted")

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict | None = None) -> dict:
        return self._request("POST", path, json=json or {})

    def put(self, path: str, json: dict | None = None) -> dict:
        return self._request("PUT", path, json=json or {})

    # ----------------------------------------------------- people search -----
    def search_people(self, *, titles: list[str], locations: list[str],
                      employee_ranges: list[str], page: int = 1,
                      per_page: int = 25, keywords: str | None = None) -> dict:
        body: dict[str, Any] = {
            "person_titles": titles,
            "person_locations": locations,
            "organization_num_employees_ranges": employee_ranges,
            "contact_email_status": ["verified"],
            "page": page,
            "per_page": per_page,
        }
        if keywords:
            body["q_keywords"] = keywords
        return self.post("mixed_people/search", body)

    def enrich_person(self, *, person_id: str | None = None,
                      email: str | None = None,
                      linkedin_url: str | None = None) -> dict:
        body = {"reveal_personal_emails": False}
        if person_id:
            body["id"] = person_id
        if email:
            body["email"] = email
        if linkedin_url:
            body["linkedin_url"] = linkedin_url
        return self.post("people/match", body)

    def org_job_postings(self, org_id: str) -> dict:
        return self.get(f"organizations/{org_id}/job_postings")

    # ---------------------------------------------------------- contacts -----
    def create_contact(self, **fields) -> dict:
        return self.post("contacts", fields)

    def update_contact(self, contact_id: str, **fields) -> dict:
        return self.put(f"contacts/{contact_id}", fields)

    def search_contacts(self, q_keywords: str = "", page: int = 1,
                        per_page: int = 25) -> dict:
        return self.post("contacts/search", {
            "q_keywords": q_keywords, "page": page, "per_page": per_page,
        })

    # --------------------------------------------------------- sequences -----
    def search_sequences(self, q_name: str = "") -> dict:
        return self.post("emailer_campaigns/search", {"q_name": q_name})

    def create_sequence(self, payload: dict) -> dict:
        return self.post("emailer_campaigns", payload)

    def update_sequence(self, sequence_id: str, payload: dict) -> dict:
        return self.put(f"emailer_campaigns/{sequence_id}", payload)

    def add_contacts_to_sequence(self, sequence_id: str, contact_ids: list[str],
                                 email_account_id: str) -> dict:
        return self.post(f"emailer_campaigns/{sequence_id}/add_contact_ids", {
            "emailer_campaign_id": sequence_id,
            "contact_ids": contact_ids,
            "send_email_from_email_account_id": email_account_id,
            "sequence_active_in_other_campaigns": False,
            "sequence_same_company_in_same_campaign": False,
        })

    def remove_contacts_from_sequence(self, sequence_id: str,
                                      contact_ids: list[str],
                                      mode: str = "mark_as_finished") -> dict:
        return self.post(
            f"emailer_campaigns/{sequence_id}/remove_or_stop_contact_ids",
            {"contact_ids": contact_ids, "mode": mode},
        )

    # ----------------------------------------------------------- account -----
    def email_accounts(self) -> list[dict]:
        return self.get("email_accounts").get("email_accounts", [])

    def find_sender_account(self, address: str) -> dict | None:
        for acct in self.email_accounts():
            if acct.get("email", "").lower() == address.lower():
                return acct
        return None

    # ------------------------------------------------------------- tasks -----
    def create_tasks(self, tasks: list[dict]) -> dict:
        return self.post("tasks/bulk_create", {"tasks": tasks})

    def search_tasks(self, open_only: bool = True) -> dict:
        body: dict[str, Any] = {"per_page": 100}
        if open_only:
            body["open_factor_names"] = ["task"]
        return self.post("tasks/search", body)
