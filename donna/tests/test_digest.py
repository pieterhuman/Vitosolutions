"""Digest rendering: dry-run to files, sorting, CEO counts-only rollup."""
from __future__ import annotations

from donna.engine.poll import run_poll
from donna.jobs.digest import run_digest

from conftest import ALICE, CEO, FRANK, T, fixture

KEY = b"test-signing-key"


def _seed(graph, store):
    graph.queue(FRANK, "inbox", [fixture("m07_inbound")])   # 08:50, oldest
    graph.queue(ALICE, "inbox", [fixture("m03_inbound")])   # 08:20
    graph.queue(ALICE, "inbox", [fixture("m01_inbound")])   # 08:00
    graph.queue(ALICE, "inbox", [fixture("m03_unknown_reply")])  # uncertain
    graph.queue(ALICE, "sentitems", [fixture("m04_outbound")])
    run_poll(graph, store, now=T("2026-07-01T12:00:00Z"))


def test_dry_run_renders_files_not_mail(graph, store, tmp_path):
    _seed(graph, store)
    result = run_digest(graph, store, now=T("2026-07-03T04:30:00Z"),
                        token_key=KEY, dry_run_dir=str(tmp_path))
    assert graph.sent_mail == [], "dry-run must not send"
    assert result["rendered"] == 7  # one per active principal
    files = sorted(tmp_path.glob("*.html"))
    assert len(files) == 7
    assert store.last_success_utc("digest") is not None


def test_digest_content_sorting_and_sections(graph, store, tmp_path):
    _seed(graph, store)
    run_digest(graph, store, now=T("2026-07-03T04:30:00Z"),
               token_key=KEY, dry_run_dir=str(tmp_path))
    html = next(tmp_path.glob("digest_alice*.html")).read_text()

    # Overdue inbound sorted by age: oldest (08:00) before newer (08:20 item
    # is uncertain, so the two overdue lists don't collide — check sections).
    assert "Trust deed amendments" in html
    assert html.index("Needs a reply") < html.index("Waiting on others")
    assert "Uncertain" in html and "Property transfer" in html
    # Mark-as-done link present and signed.
    assert "/close/" in html

    frank_html = next(tmp_path.glob("digest_frank*.html")).read_text()
    assert "FX facility renewal" in frank_html


def test_overdue_sorted_oldest_first(graph, store, tmp_path):
    graph.queue(ALICE, "inbox", [fixture("m01_inbound")])   # 08:00
    graph.queue(ALICE, "inbox", [fixture("m08_inbound")])   # 09:00
    run_poll(graph, store, now=T("2026-07-01T12:00:00Z"))
    run_digest(graph, store, now=T("2026-07-03T04:30:00Z"),
               token_key=KEY, dry_run_dir=str(tmp_path))
    html = next(tmp_path.glob("digest_alice*.html")).read_text()
    assert html.index("Trust deed amendments") < html.index("Lease agreement")


def test_ceo_rollup_is_counts_only(graph, store, tmp_path):
    _seed(graph, store)
    run_digest(graph, store, now=T("2026-07-03T04:30:00Z"),
               token_key=KEY, dry_run_dir=str(tmp_path))
    ceo_html = next(tmp_path.glob("digest_ceo*.html")).read_text()

    assert "Team rollup" in ceo_html
    # Counts only: no other principal's subjects or counterparties.
    for leaked in ("FX facility renewal", "Trust deed amendments",
                   "Property transfer", "lawyer@sterlinglaw.example",
                   "banker@privatebank.example"):
        assert leaked not in ceo_html, f"CEO rollup leaked: {leaked}"
    # But the per-person names/counts are there.
    assert "Frank Joubert" in ceo_html


def test_non_ceo_digest_has_no_rollup(graph, store, tmp_path):
    _seed(graph, store)
    run_digest(graph, store, now=T("2026-07-03T04:30:00Z"),
               token_key=KEY, dry_run_dir=str(tmp_path))
    html = next(tmp_path.glob("digest_alice*.html")).read_text()
    assert "Team rollup" not in html


def test_planner_overdue_in_owner_digest(graph, store, tmp_path):
    _seed(graph, store)
    graph.planner[ALICE] = [
        {"title": "File FICA documentation", "plan": "Compliance",
         "due": "2026-06-28"},
        {"title": "Renew office lease", "plan": "Operations",
         "due": "2026-06-30"},
    ]
    run_digest(graph, store, now=T("2026-07-03T04:30:00Z"),
               token_key=KEY, dry_run_dir=str(tmp_path))
    html = next(tmp_path.glob("digest_alice*.html")).read_text()
    assert "Overdue in Planner" in html
    assert "File FICA documentation" in html and "Compliance" in html
    assert "due 2026-06-28" in html

    frank_html = next(tmp_path.glob("digest_frank*.html")).read_text()
    assert "Nothing overdue in Planner" in frank_html


def test_planner_counts_only_in_ceo_rollup(graph, store, tmp_path):
    _seed(graph, store)
    graph.planner[ALICE] = [
        {"title": "File FICA documentation", "plan": "Compliance",
         "due": "2026-06-28"},
    ]
    run_digest(graph, store, now=T("2026-07-03T04:30:00Z"),
               token_key=KEY, dry_run_dir=str(tmp_path))
    ceo_html = next(tmp_path.glob("digest_ceo*.html")).read_text()
    assert "tasks overdue" in ceo_html, "rollup carries the overdue count"
    assert "File FICA documentation" not in ceo_html, \
        "CEO rollup must never leak task titles"
    assert "Compliance" not in ceo_html


def test_planner_failure_never_blocks_briefing(graph, store, tmp_path):
    _seed(graph, store)

    def broken(upn, now):
        raise RuntimeError("planner unavailable")

    graph.planner_overdue = broken
    result = run_digest(graph, store, now=T("2026-07-03T04:30:00Z"),
                        token_key=KEY, dry_run_dir=str(tmp_path))
    assert result["rendered"] == 7, "Planner is additive, never blocking"


def test_severity_scales_with_threshold_not_raw_hours(graph, store, tmp_path):
    """A VIP item's 3h threshold means the SAME clock-hours overdue reads
    far more severe than a regular item's 24h threshold — ratio-based,
    not absolute-hours-based."""
    graph.queue(FRANK, "inbox", [fixture("m10_vip_inbound")])  # 3h threshold
    graph.queue(ALICE, "inbox", [fixture("m01_inbound")])       # 24h threshold
    run_poll(graph, store, now=T("2026-07-01T08:10:00Z"))
    # 6 hours later: VIP is 3h past its 3h threshold (ratio 1.0 -> orange),
    # Alice's item isn't overdue at all yet (6h < 24h threshold).
    run_digest(graph, store, now=T("2026-07-01T14:10:00Z"),
               token_key=KEY, dry_run_dir=str(tmp_path))

    frank_html = next(tmp_path.glob("digest_frank*.html")).read_text()
    assert "#B5690E" in frank_html, "VIP item should already read orange"

    alice_html = next(tmp_path.glob("digest_alice*.html")).read_text()
    assert "Trust deed amendments" not in alice_html, \
        "not yet past its 24h threshold, should not appear as overdue"


def test_not_yet_due_awaiting_item_is_neutral_not_falsely_green(graph, store, tmp_path):
    _seed(graph, store)  # includes a sent item 44h into its 72h window
    run_digest(graph, store, now=T("2026-07-03T04:30:00Z"),
               token_key=KEY, dry_run_dir=str(tmp_path))
    html = next(tmp_path.glob("digest_alice*.html")).read_text()
    assert "not yet due" in html
    assert "just overdue" not in html, \
        "an item still inside its window must not be mislabeled overdue"


def test_uncertain_items_use_slate_not_traffic_light_colors(graph, store, tmp_path):
    _seed(graph, store)
    run_digest(graph, store, now=T("2026-07-03T04:30:00Z"),
               token_key=KEY, dry_run_dir=str(tmp_path))
    html = next(tmp_path.glob("digest_alice*.html")).read_text()
    assert "needs judgement" in html
    assert "#3E5470" in html


def test_live_send_uses_service_mailbox(graph, store):
    _seed(graph, store)
    run_digest(graph, store, now=T("2026-07-03T04:30:00Z"), token_key=KEY,
               dry_run_dir=None)
    assert len(graph.sent_mail) == 7
    assert all(m["from"] == "donna@familyoffice.example"
               for m in graph.sent_mail), "always FROM the service mailbox"
    assert {m["to"] for m in graph.sent_mail} == {
        p.upn for p in store.active_principals()}
