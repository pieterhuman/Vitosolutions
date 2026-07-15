"""Local Docker demo server.

Seeds the ledger with synthetic mail, runs the same poll -> urgent ->
digest -> suggest pipeline the Azure Functions host runs on a schedule,
and serves the results over plain HTTP so a browser can click through
what Donna produces — including a real, working mark-as-done link.

This file exists ONLY for local demonstration. It bypasses
donna.config (no Managed Identity, no Key Vault, no Graph) and talks
directly to Postgres and a synthetic in-memory Graph double. Nothing
here runs in Azure; function_app.py is the production entry point.
"""
from __future__ import annotations

import glob
import html
import json
import os
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

sys.path[:0] = ["src", "tests"]

import sqlalchemy as sa  # noqa: E402

from demo import seed  # noqa: E402
from fakegraph import FakeGraph  # noqa: E402
from donna.engine.poll import run_poll  # noqa: E402
from donna.http_close import handle_close  # noqa: E402
from donna.jobs.digest import run_digest  # noqa: E402
from donna.jobs.suggest import run_suggest  # noqa: E402
from donna.jobs.urgent import run_urgent  # noqa: E402
from donna.store import Store  # noqa: E402

DB_URL = os.environ.get(
    "DONNA_DB_URL",
    "postgresql+psycopg://donna:donna-demo-local-only@db:5432/donna")
HMAC_KEY = os.environ.get(
    "DONNA_DEMO_HMAC_KEY", "local-demo-signing-key-not-for-production"
).encode("utf-8")
PORT = int(os.environ.get("PORT", "8080"))
OUT_DIR = "/app/demo_out"

state = {"graph": None, "store": None, "card": None, "seeded_at": None}


def _connect_with_retry(url: str, attempts: int = 20) -> sa.Engine:
    last_err = None
    for _ in range(attempts):
        try:
            engine = sa.create_engine(url, future=True)
            with engine.begin() as cx:
                cx.execute(sa.text("SELECT 1"))
            return engine
        except Exception as exc:  # noqa: BLE001 — retry loop, not a handler
            last_err = exc
            time.sleep(1)
    raise RuntimeError(f"could not reach Postgres after {attempts}s") from last_err


def run_pipeline(now: datetime) -> None:
    store = state["store"]
    graph = FakeGraph()
    seed.build_graph(graph, now)
    run_poll(graph, store, now=now)
    state["card"] = None

    def capture(payload: dict) -> None:
        state["card"] = payload

    run_urgent(store, capture, now=now)
    run_digest(graph, store, now=now, token_key=HMAC_KEY, dry_run_dir=OUT_DIR)
    run_suggest(store, now=now, report_dir=OUT_DIR)
    state["graph"] = graph
    state["seeded_at"] = now


def bootstrap() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    engine = _connect_with_retry(DB_URL)
    store = Store(engine)
    store.ensure_schema()
    seed.seed_principals_and_config(store)
    state["store"] = store
    run_pipeline(datetime.now(timezone.utc))


def _latest(pattern: str) -> str | None:
    matches = sorted(glob.glob(os.path.join(OUT_DIR, pattern)),
                     key=os.path.getmtime, reverse=True)
    return matches[0] if matches else None


def _page(title: str, body: str) -> bytes:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title></head>"
        "<body style='font-family:Segoe UI,Arial,sans-serif;"
        "max-width:820px;margin:32px auto;padding:0 16px'>"
        f"{body}</body></html>"
    ).encode("utf-8")


def _index() -> bytes:
    store = state["store"]
    rows = []
    for p in store.active_principals():
        slug = p.upn.split("@", 1)[0]
        tag = " (CEO rollup)" if p.is_ceo else ""
        rows.append(
            f"<li><a href='/digest/{slug}'>{html.escape(p.display_name)}"
            f"{tag}</a></li>")
    card = state["card"]
    card_line = ("<a href='/teams-card'>1 urgent alert pending</a>"
                if card else "no urgent alerts currently pending")
    seeded = state["seeded_at"]
    body = f"""
    <h1>Donna Minimal — local demo</h1>
    <p style="color:#666">All data below is synthetic (see
    <code>demo/seed.py</code>) — nothing here is a real mailbox.
    Rendered {seeded:%Y-%m-%d %H:%M UTC} on this container's clock.</p>
    <h2>Briefings</h2>
    <ul>{''.join(rows)}</ul>
    <h2>Weekly recurring-pattern review</h2>
    <p><a href="/suggestions">Suggestion report</a> — advisory only,
    never changes an item's state on its own (see RUNBOOK.md).</p>
    <h2>Urgent (Teams webhook payload)</h2>
    <p>{card_line}</p>
    <hr>
    <p>
      <a href="/refresh">Re-run poll + refresh briefings</a> —
      after clicking a "mark done" link, use this to see the item drop
      off the digest.<br>
      <a href="/reset">Reset demo data</a> — wipes the ledger and
      reseeds from scratch.
    </p>
    """
    return _page("Donna — demo", body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003 — stdlib signature
        pass  # keep container logs quiet; nothing sensitive to hide, just noise

    def _send(self, status: int, body: bytes, content_type: str = "text/html"):
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 — stdlib method name
        path = unquote(self.path)
        if path in ("/", ""):
            self._send(200, _index())
        elif path.startswith("/digest/"):
            slug = path.removeprefix("/digest/")
            latest = _latest(f"digest_{slug}_*.html")
            if not latest:
                self._send(404, _page("Not found", "<p>No digest for that person.</p>"))
                return
            self._send(200, open(latest, "rb").read())
        elif path == "/suggestions":
            latest = _latest("suggestions_*.html")
            if not latest:
                self._send(200, _page("Suggestions", "<p>No report yet.</p>"))
                return
            self._send(200, open(latest, "rb").read())
        elif path == "/teams-card":
            card = state["card"]
            body = (f"<pre>{html.escape(json.dumps(card, indent=2))}</pre>"
                    if card else "<p>No urgent alert is currently pending.</p>")
            self._send(200, _page("Teams webhook payload", body))
        elif path == "/refresh":
            run_pipeline(datetime.now(timezone.utc))
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
        elif path == "/reset":
            with state["store"].engine.begin() as cx:
                for table in ("item_event", "open_item", "delta_cursor",
                             "suggestion", "known_alias", "job_run"):
                    cx.execute(sa.text(f"DELETE FROM {table}"))
            run_pipeline(datetime.now(timezone.utc))
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self._send(404, _page("Not found", "<p>Unknown page.</p>"))

    def do_POST(self):  # noqa: N802 — stdlib method name
        path = unquote(self.path)
        if path.startswith("/close/"):
            token = path.removeprefix("/close/")
            status, resp_body = handle_close(
                state["store"], token, HMAC_KEY, now=datetime.now(timezone.utc))
            body = (
                f"<h1>{'Closed' if status == 200 else 'Could not close'}</h1>"
                f"<pre>{html.escape(json.dumps(resp_body, indent=2))}</pre>"
                "<p><a href='/refresh'>Refresh briefings</a> to see the "
                "change, or <a href='/'>back to the list</a>.</p>"
            )
            self._send(status, _page("Mark as done", body))
        else:
            self._send(404, _page("Not found", "<p>Unknown page.</p>"))


def main() -> None:
    bootstrap()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Donna demo ready: http://localhost:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
