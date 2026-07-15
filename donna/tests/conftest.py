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

from donna.store import Store
from fakegraph import FakeGraph

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
