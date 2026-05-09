"""FastAPI entrypoint."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import agents, approvals, dashboard, health, sync, xero_oauth
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.models import create_all

configure_logging()
log = get_logger(__name__)

app = FastAPI(title="CFO Agents", version="0.1.0")

app.include_router(health.router)
app.include_router(sync.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(approvals.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(xero_oauth.router, prefix="/api")


@app.on_event("startup")
def _startup() -> None:
    settings = get_settings()
    if settings.demo_mode:
        # Spin up SQLite schema and seed demo data on first boot.
        create_all()
        from scripts.seed_local import seed_into_session
        from app.db.session import session_scope

        with session_scope() as s:
            seed_into_session(s, tenant_id="demo")
        log.info("demo.seeded")
    else:
        log.info("startup.prod_mode")
