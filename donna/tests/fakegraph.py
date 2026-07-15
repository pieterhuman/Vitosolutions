"""FakeGraph: a synthetic double for donna.graph.GraphClient's surface.

Split out of conftest.py so it has no pytest dependency — the Docker
demo (demo/server.py) imports this module directly without needing the
test runner installed in its image.
"""
from __future__ import annotations

from datetime import datetime

from donna.errors import CursorGone


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
