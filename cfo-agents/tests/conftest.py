"""Shared pytest fixtures."""

from __future__ import annotations

import os

# Force demo mode and fresh in-memory DB before importing the app.
os.environ["CFO_DEMO_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = ""  # ensure deterministic fallbacks
os.environ["CFO_SECRET_KEY"] = "test-secret-key-test-secret-key-32"

import pytest
from sqlalchemy.orm import Session

from app.db.models import create_all
from app.db.session import session_scope
from scripts.seed_local import seed_into_session


@pytest.fixture
def db_session() -> Session:
    create_all()
    with session_scope() as s:
        seed_into_session(s, tenant_id="demo")
    with session_scope() as s:
        yield s
