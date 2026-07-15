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

# Literal hex only — no CSS custom properties. Outlook's rendering engine
# (Word) and several mobile mail clients don't support var(), so every
# color below is inlined at the point of use, not tokenized.
SEVERITY_COLORS = {
    "green": ("#2E7D46", "#EAF3EC", "just overdue"),
    "orange": ("#B5690E", "#FBF0E4", "overdue"),
    "red": ("#B23A2E", "#F7E9E7", "badly overdue"),
}
UNCERTAIN_COLOR = ("#3E5470", "#EAEEF3")
INK = "#20231D"
MUTED = "#6B6F63"
RULE = "#E3DFD3"
ACCENT = "#A87C2A"


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


def _overdue_severity(now: datetime, item) -> tuple[str, str, str, bool]:
    """(dot/text color, soft background, label, is_overdue) for how far
    past its OWN threshold an item is — not raw hours. A VIP item's 3h
    threshold means it reaches "badly overdue" far sooner than a regular
    24h item at the same clock-hours overdue, which is correct: VIP
    thresholds exist to demand faster attention, not just a shorter
    number. Items that haven't actually crossed their threshold yet
    (e.g. a sent-awaiting item still inside its window) get a neutral,
    uncolored treatment rather than a false "just overdue" label."""
    overdue_hours = (now - item.anchor_utc).total_seconds() / 3600 - item.threshold_hours
    if overdue_hours <= 0:
        return MUTED, "transparent", "", False
    ratio = overdue_hours / item.threshold_hours
    key = "red" if ratio >= 2 else "orange" if ratio >= 0.5 else "green"
    color, soft, label = SEVERITY_COLORS[key]
    return color, soft, label, True


def _dot(color: str) -> str:
    return (f"<span style='display:inline-block;width:9px;height:9px;"
            f"border-radius:50%;background:{color};margin-right:6px;"
            f"vertical-align:middle'></span>")


def _item_row(item, now: datetime, principal_id: int, token_key: bytes,
              base_url: str, *, uncertain: bool = False) -> str:
    expiry = int(now.timestamp()) + tokens.TOKEN_TTL_SECONDS
    token = tokens.make_token(item.id, principal_id, expiry, token_key)

    if uncertain:
        color, soft = UNCERTAIN_COLOR
        badge = (f"<span style='color:{color};background:{soft};"
                f"border-radius:3px;padding:1px 6px;font-size:0.78em;"
                f"font-weight:600;white-space:nowrap'>? needs judgement</span>")
        age_cell = f"<td style='padding:4px 12px 4px 0;white-space:nowrap;color:{color}'>{_age(now, item.anchor_utc)}</td>"
    else:
        color, soft, label, is_overdue = _overdue_severity(now, item)
        if is_overdue:
            badge = _dot(color) + (f"<span style='color:{color};"
                                   f"font-size:0.78em;font-weight:600'>{_e(label)}</span>")
            age_cell = (f"<td style='padding:4px 12px 4px 0;white-space:nowrap;"
                       f"color:{color};font-weight:600'>{_age(now, item.anchor_utc)}</td>")
        else:
            badge = f"<span style='color:{MUTED};font-size:0.78em'>not yet due</span>"
            age_cell = (f"<td style='padding:4px 12px 4px 0;white-space:nowrap;"
                       f"color:{MUTED}'>{_age(now, item.anchor_utc)}</td>")

    return (
        f"<tr style='background:{soft}'>"
        f"<td style='padding:6px 12px 6px 10px;border-radius:4px 0 0 4px'>{badge}</td>"
        f"<td style='padding:6px 12px 6px 0;color:{INK}'>{_e(item.subject)}</td>"
        f"<td style='padding:6px 12px 6px 0;color:{MUTED}'>{_e(item.counterparty_name or item.counterparty_smtp)}</td>"
        f"{age_cell}"
        "<td style='padding:6px 10px 6px 0;border-radius:0 4px 4px 0'>"
        f"<form method='post' action='{base_url}/close/{token}' "
        "style='display:inline;margin:0'>"
        f"<button type='submit' style='font:inherit;color:{ACCENT};"
        "background:none;border:none;padding:0;cursor:pointer;"
        "text-decoration:underline'>mark done</button></form></td>"
        "</tr>"
    )


def _section(title: str, rows: list[str], empty: str,
            accent: str | None = None) -> str:
    rule_color = accent or RULE
    body = (f"<table cellspacing='0' cellpadding='0' style='width:100%;"
            f"border-collapse:separate;border-spacing:0 3px'>{''.join(rows)}</table>"
            if rows else f"<p style='color:{MUTED};margin:4px 0 0'>{_e(empty)}</p>")
    return (
        f"<div style='margin:22px 0 8px;padding-left:10px;"
        f"border-left:3px solid {rule_color}'>"
        f"<h3 style='margin:0;font-family:Segoe UI,Arial,sans-serif;"
        f"font-size:1.02em;color:{INK}'>{_e(title)}</h3></div>{body}"
    )


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

    red, orange, slate = (SEVERITY_COLORS["red"][0], SEVERITY_COLORS["orange"][0],
                         UNCERTAIN_COLOR[0])

    parts = [
        f"<div style='font-family:Segoe UI,Arial,sans-serif;max-width:720px;color:{INK}'>",
        f"<table cellspacing='0' cellpadding='0' style='width:100%;"
        f"border-collapse:collapse;margin:0 0 18px'><tr>"
        f"<td style='background:{ACCENT};height:4px;line-height:4px;"
        f"font-size:0;border-radius:2px'>&nbsp;</td></tr></table>",
        f"<h2 style='margin:0 0 4px;font-size:1.5em'>Donna briefing</h2>"
        f"<p style='margin:0 0 4px;color:{MUTED}'>{_e(p.display_name)} — "
        f"{now:%A %d %B %Y, %H:%M} UTC</p>",
        _section("Needs a reply",
                 [_item_row(i, now, p.id, token_key, base_url)
                  for i in overdue],
                 "Nothing overdue.", accent=red),
        _section("Waiting on others",
                 [_item_row(i, now, p.id, token_key, base_url)
                  for i in awaiting],
                 "Nothing outstanding.", accent=orange),
        _section("Uncertain — needs your judgement",
                 [_item_row(i, now, p.id, token_key, base_url, uncertain=True)
                  for i in uncertain],
                 "Nothing uncertain.", accent=slate),
        _section("Today's calendar",
                 [f"<tr><td style='padding:4px 12px 4px 0;white-space:nowrap;color:{MUTED}'>"
                  f"{_e(ev.get('start', ''))}</td>"
                  f"<td style='padding:4px 0;color:{INK}'>{_e(ev.get('subject', ''))}</td></tr>"
                  for ev in events],
                 "No meetings today."),
        _section("Tasks due today and overdue",
                 [f"<tr><td style='padding:4px 0;color:{INK}'>{_e(t.get('title', ''))}"
                  f"</td></tr>" for t in tasks],
                 "No tasks due."),
        _section("Overdue in Planner",
                 [f"<tr><td style='padding:4px 12px 4px 0;color:{INK}'>{_e(t.get('title', ''))}</td>"
                  f"<td style='padding:4px 12px 4px 0;color:{MUTED}'>{_e(t.get('plan', ''))}</td>"
                  f"<td style='padding:4px 0;white-space:nowrap;color:{red}'>due {_e(t.get('due', ''))}</td></tr>"
                  for t in planner_overdue],
                 "Nothing overdue in Planner.", accent=red),
    ]

    if rollup is not None:
        def stat(n: int, word: str, color: str) -> str:
            c = color if n else MUTED
            weight = "font-weight:600;" if n else ""
            return f"<span style='color:{c};{weight}'>{n} {word}</span>"

        rows = [
            f"<tr><td style='padding:5px 12px 5px 0;color:{INK};font-weight:600'>{_e(name)}</td>"
            f"<td style='padding:5px 12px 5px 0'>{stat(c['inbound'], 'inbound', red)}</td>"
            f"<td style='padding:5px 12px 5px 0'>{stat(c['awaiting'], 'awaiting', orange)}</td>"
            f"<td style='padding:5px 12px 5px 0'>{stat(c['uncertain'], 'uncertain', slate)}</td>"
            f"<td style='padding:5px 0'>{stat(c['tasks_overdue'], 'tasks overdue', red)}</td></tr>"
            for name, c in rollup
        ]
        parts.append(_section("Team rollup (counts only)", rows, ""))

    parts.append("</div>")
    return "".join(parts)
