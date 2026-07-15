"""Fast, Docker-free smoke test for the demo pipeline (CI-friendly).

Runs the exact seed -> poll -> urgent -> digest -> suggest sequence
demo/server.py runs at startup, against SQLite instead of Postgres, and
asserts the shape of what comes out. This is what would have caught the
mark-done GET/POST mismatch before it reached a live demo.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone

sys.path[:0] = ["src", "tests"]

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from demo import seed  # noqa: E402
from donna.engine.poll import run_poll  # noqa: E402
from donna.http_close import handle_close  # noqa: E402
from donna.jobs.digest import run_digest  # noqa: E402
from donna.jobs.suggest import run_suggest  # noqa: E402
from donna.jobs.urgent import run_urgent  # noqa: E402
from donna.store import Store  # noqa: E402
from fakegraph import FakeGraph  # noqa: E402
import re  # noqa: E402


def main() -> None:
    engine = sa.create_engine(
        "sqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False}, future=True)
    store = Store(engine)
    store.ensure_schema()
    seed.seed_principals_and_config(store)
    assert len(store.active_principals()) == 7

    now = datetime.now(timezone.utc)
    graph = FakeGraph()
    seed.build_graph(graph, now)
    poll_result = run_poll(graph, store, now=now)
    assert poll_result["created"] > 0, "demo dataset should create items"

    cards = []
    run_urgent(store, cards.append, now=now)
    assert len(cards) == 1, "the VIP fixture should fire exactly one alert"

    with tempfile.TemporaryDirectory() as out_dir:
        key = b"smoke-test-key"
        digest_result = run_digest(graph, store, now=now, token_key=key,
                                   dry_run_dir=out_dir)
        assert digest_result["rendered"] == 7

        suggest_result = run_suggest(store, now=now, report_dir=out_dir)
        assert suggest_result["pending"] == 1, \
            "the recurring-alias fixture should cross the review threshold"

        alice_html = open(f"{out_dir}/digest_alice_{now:%Y%m%dT%H%M}.html"
                          ).read()
        assert "<form method='post'" in alice_html, \
            "mark-done must be a POST form, not a GET link"

        token = re.search(r"action='[^']*?/close/([^']+)'", alice_html).group(1)
        status, _ = handle_close(store, token, key, now=now)
        assert status == 200, "the token rendered in the digest must verify"

    print("demo smoke test OK: "
         f"created={poll_result['created']} cards={len(cards)} "
         f"suggestions={suggest_result['pending']}")


if __name__ == "__main__":
    main()
