"""Local dry run: seed an in-memory ledger from the synthetic fixtures,
run a poll cycle, and render every principal's digest to ./out/.

No network, no Azure, no real data. Usage:

    cd donna && PYTHONPATH=src:tests python3 scripts/dry_run_local.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path[:0] = ["src", "tests"]

from conftest import ALICE, FRANK, FakeGraph, T, fixture, make_store  # noqa: E402

from donna.engine.poll import run_poll  # noqa: E402
from donna.jobs.digest import run_digest  # noqa: E402


def main() -> None:
    store = make_store()
    graph = FakeGraph()
    graph.queue(ALICE, "inbox", [fixture("m01_inbound")])
    graph.queue(ALICE, "inbox", [fixture("m03_inbound"),
                                 fixture("m03_unknown_reply")])
    graph.queue(ALICE, "sentitems", [fixture("m04_outbound")])
    graph.queue(FRANK, "inbox", [fixture("m07_inbound")])
    run_poll(graph, store, now=T("2026-07-01T12:00:00Z"))

    out = pathlib.Path("out")
    result = run_digest(graph, store, now=T("2026-07-03T04:30:00Z"),
                        token_key=b"local-dry-run-key",
                        dry_run_dir=str(out))
    print(f"rendered {result['rendered']} digests into {out.resolve()}/")


if __name__ == "__main__":
    main()
