"""Digest job: twice-daily briefing email per principal.

Sent via Graph sendMail FROM the dedicated service mailbox, never
send-as a person. In dry-run mode the rendered HTML goes to local files
instead. The CEO additionally gets a per-person rollup with COUNTS
ONLY — no subjects, no senders.
"""
from __future__ import annotations

import html as _html
import pathlib
from datetime import datetime, timedelta

from .. import states, tokens
from ..store import Store
from ..telemetry import get_logger

log = get_logger(__name__)


def run_digest(graph, store: Store, now: datetime, token_key: bytes,
               dry_run_dir: str | None = None) -> dict:
    service_upn = store.config_get("service_mailbox_upn")
    base_url = store.config_get("close_base_url").rstrip("/")
    principals = store.active_principals()

    planner = {p.upn: _planner_overdue_safe(graph, p.upn, now)
               for p in principals}
    rollup = [
        (p.display_name,
         _counts(store, p.id) | {"tasks_overdue": len(planner[p.upn])})
        for p in principals
    ]

    rendered = 0
    for p in principals:
        body = _render(graph, store, p, now, token_key, base_url,
                       rollup if p.is_ceo else None, planner[p.upn])
        subject = f"Donna briefing — {now:%a %d %b %Y}"
        if dry_run_dir is not None:
            out = pathlib.Path(dry_run_dir)
            out.mkdir(parents=True, exist_ok=True)
            local = p.upn.split("@", 1)[0]
            path = out / f"digest_{local}_{now:%Y%m%dT%H%M}.html"
            path.write_text(body, encoding="utf-8")
        else:
            graph.send_mail(from_upn=service_upn, to_upn=p.upn,
                            subject=subject, html_body=body)
        rendered += 1

    store.record_job_run("digest", "success", now,
                         detail=f"rendered={rendered}"
                                + (" dry_run" if dry_run_dir else ""))
    log.info("digest complete rendered=%d dry_run=%s", rendered,
             bool(dry_run_dir))
    return {"rendered": rendered, "dry_run": dry_run_dir is not None}


def _planner_overdue_safe(graph, upn: str, now: datetime) -> list[dict]:
    """Planner is additive: a Planner outage or missing license must
    never block the briefing itself."""
    try:
        return graph.planner_overdue(upn, now)
    except Exception:
        log.warning("planner read failed for a principal; section omitted")
        return []


def _counts(store: Store, principal_id: int) -> dict[str, int]:
    return {
        "inbound": len(store.items(principal_id=principal_id,
                                   kind=states.KIND_INBOUND,
                                   item_states=(states.OPEN,))),
        "awaiting": len(store.items(principal_id=principal_id,
                                    kind=states.KIND_SENT_AWAITING,
                                    item_states=(states.OPEN,))),
        "uncertain": len(store.items(principal_id=principal_id,
                                     item_states=(states.UNCERTAIN,))),
    }


def _age(now: datetime, anchor: datetime) -> str:
    hours = int((now - anchor).total_seconds() // 3600)
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def _e(text: str) -> str:
    return _html.escape(text, quote=True)


def _item_row(item, now: datetime, principal_id: int, token_key: bytes,
              base_url: str) -> str:
    expiry = int(now.timestamp()) + tokens.TOKEN_TTL_SECONDS
    token = tokens.make_token(item.id, principal_id, expiry, token_key)
    return (
        "<tr>"
        f"<td style='padding:4px 12px 4px 0'>{_e(item.subject)}</td>"
        f"<td style='padding:4px 12px 4px 0'>{_e(item.counterparty_name or item.counterparty_smtp)}</td>"
        f"<td style='padding:4px 12px 4px 0;white-space:nowrap'>{_age(now, item.anchor_utc)}</td>"
        f"<td style='padding:4px 0'><a href='{base_url}/close/{token}'>mark done</a></td>"
        "</tr>"
    )


def _section(title: str, rows: list[str], empty: str) -> str:
    body = (f"<table cellspacing='0' cellpadding='0'>{''.join(rows)}</table>"
            if rows else f"<p style='color:#666'>{_e(empty)}</p>")
    return (f"<h3 style='margin:18px 0 6px;font-family:Segoe UI,Arial,"
            f"sans-serif'>{_e(title)}</h3>{body}")


def _render(graph, store: Store, p, now: datetime, token_key: bytes,
            base_url: str, rollup, planner_overdue: list[dict]) -> str:
    overdue = [i for i in store.items(principal_id=p.id,
                                      kind=states.KIND_INBOUND,
                                      item_states=(states.OPEN,))
               if now > i.anchor_utc + timedelta(hours=i.threshold_hours)]
    # store.items orders by anchor ascending: oldest first.
    awaiting = store.items(principal_id=p.id,
                           kind=states.KIND_SENT_AWAITING,
                           item_states=(states.OPEN,))
    uncertain = store.items(principal_id=p.id,
                            item_states=(states.UNCERTAIN,))

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = graph.calendar_view(p.upn, day_start,
                                 day_start + timedelta(days=1))
    tasks = graph.tasks_due(p.upn, now)

    parts = [
        "<div style='font-family:Segoe UI,Arial,sans-serif;max-width:720px'>",
        f"<h2 style='margin:0 0 4px'>Donna briefing</h2>"
        f"<p style='margin:0 0 12px;color:#666'>{_e(p.display_name)} — "
        f"{now:%A %d %B %Y, %H:%M} UTC</p>",
        _section("Needs a reply",
                 [_item_row(i, now, p.id, token_key, base_url)
                  for i in overdue],
                 "Nothing overdue."),
        _section("Waiting on others",
                 [_item_row(i, now, p.id, token_key, base_url)
                  for i in awaiting],
                 "Nothing outstanding."),
        _section("Uncertain — needs your judgement",
                 [_item_row(i, now, p.id, token_key, base_url)
                  for i in uncertain],
                 "Nothing uncertain."),
        _section("Today's calendar",
                 [f"<tr><td style='padding:4px 12px 4px 0;white-space:nowrap'>"
                  f"{_e(ev.get('start', ''))}</td>"
                  f"<td style='padding:4px 0'>{_e(ev.get('subject', ''))}</td></tr>"
                  for ev in events],
                 "No meetings today."),
        _section("Tasks due today and overdue",
                 [f"<tr><td style='padding:4px 0'>{_e(t.get('title', ''))}"
                  f"</td></tr>" for t in tasks],
                 "No tasks due."),
        _section("Overdue in Planner",
                 [f"<tr><td style='padding:4px 12px 4px 0'>{_e(t.get('title', ''))}</td>"
                  f"<td style='padding:4px 12px 4px 0;color:#666'>{_e(t.get('plan', ''))}</td>"
                  f"<td style='padding:4px 0;white-space:nowrap'>due {_e(t.get('due', ''))}</td></tr>"
                  for t in planner_overdue],
                 "Nothing overdue in Planner."),
    ]

    if rollup is not None:
        rows = [
            f"<tr><td style='padding:4px 12px 4px 0'>{_e(name)}</td>"
            f"<td style='padding:4px 12px 4px 0'>{c['inbound']} inbound</td>"
            f"<td style='padding:4px 12px 4px 0'>{c['awaiting']} awaiting</td>"
            f"<td style='padding:4px 12px 4px 0'>{c['uncertain']} uncertain</td>"
            f"<td style='padding:4px 0'>{c['tasks_overdue']} tasks overdue</td></tr>"
            for name, c in rollup
        ]
        parts.append(_section("Team rollup (counts only)", rows, ""))

    parts.append("</div>")
    return "".join(parts)
