"""Test harness: synthetic Graph client + seeded in-memory ledger.

Everything here is synthetic. No real tenant data ever appears in this
repository (hard constraint 6).
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from donna.errors import CursorGone
from donna.store import Store

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures" / "messages"

ALICE = "alice@familyoffice.example"
BOB = "bob@familyoffice.example"
CAROL = "carol@familyoffice.example"
DAN = "dan@familyoffice.example"
ERIN = "erin@familyoffice.example"
FRANK = "frank@familyoffice.example"
CEO = "ceo@familyoffice.example"

PRINCIPALS = [
    (CEO, "Nomsa Dlamini", True),
    (ALICE, "Alice Meyer", False),
    (BOB, "Bob Naidoo", False),
    (CAROL, "Carol van Wyk", False),
    (DAN, "Dan Botha", False),
    (ERIN, "Erin Sithole", False),
    (FRANK, "Frank Joubert", False),
]


def fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


def T(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(
        timezone.utc)


class FakeGraph:
    """Same surface as donna.graph.GraphClient, fed from fixtures."""

    def __init__(self):
        self._queues: dict[tuple[str, str], list[list[dict]]] = {}
        self._gone: set[tuple[str, str]] = set()
        self._cursor_seq = 0
        self.sent_mail: list[dict] = []
        self.calendar: dict[str, list[dict]] = {}
        self.tasks: dict[str, list[dict]] = {}
        self.planner: dict[str, list[dict]] = {}
        self.delta_calls: list[tuple[str, str, str | None]] = []

    # -- test wiring -----------------------------------------------------
    def queue(self, upn: str, folder: str, messages: list[dict]) -> None:
        self._queues.setdefault((upn.casefold(), folder), []).append(messages)

    def mark_cursor_gone(self, upn: str, folder: str) -> None:
        self._gone.add((upn.casefold(), folder))

    # -- GraphClient surface ----------------------------------------------
    def delta_messages(self, upn: str, folder: str,
                       delta_link: str | None) -> tuple[list[dict], str]:
        key = (upn.casefold(), folder)
        self.delta_calls.append((upn.casefold(), folder, delta_link))
        if delta_link is not None and key in self._gone:
            self._gone.discard(key)
            raise CursorGone(f"410 gone for {folder}")
        # A real delta sync follows @odata.nextLink until exhausted, so
        # one call drains every page queued since the last sync.
        pages = self._queues.pop(key, [])
        messages = [m for page in pages for m in page]
        self._cursor_seq += 1
        return messages, f"delta-link-{self._cursor_seq}"

    def calendar_view(self, upn: str, start: datetime,
                      end: datetime) -> list[dict]:
        return self.calendar.get(upn.casefold(), [])

    def tasks_due(self, upn: str, today: datetime) -> list[dict]:
        return self.tasks.get(upn.casefold(), [])

    def planner_overdue(self, upn: str, now: datetime) -> list[dict]:
        return self.planner.get(upn.casefold(), [])

    def send_mail(self, *, from_upn: str, to_upn: str, subject: str,
                  html_body: str) -> None:
        self.sent_mail.append({"from": from_upn, "to": to_upn,
                               "subject": subject, "html": html_body})


def make_store() -> Store:
    engine = sa.create_engine(
        "sqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False}, future=True)
    store = Store(engine)
    store.ensure_schema()
    for upn, name, is_ceo in PRINCIPALS:
        store.add_principal(upn, name, is_ceo=is_ceo)
    store.add_vip(smtp="vip@bigclient.example", label="Key Client",
                  threshold_hours=3)
    store.add_exclusion("domain", "spamlist.example")
    store.config_set("internal_domains", "familyoffice.example")
    store.config_set("service_mailbox_upn", "donna@familyoffice.example")
    store.config_set("close_base_url", "https://donna.example/api")
    return store


@pytest.fixture
def store() -> Store:
    return make_store()


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph()


def pid(store: Store, upn: str) -> int:
    return store.principal_by_upn(upn).id
