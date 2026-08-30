"""Discovery-call slot proposal and .ics invite generation (US Eastern).

Slots are proposed inside configured ET windows on upcoming weekdays.
Booking = sending a calendar invite (.ics via Gmail SMTP) — gated behind
human approval unless booking.auto_book is true.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import Config

ET = ZoneInfo("America/New_York")


def propose_slots(cfg: Config, taken: list[datetime] | None = None) -> list[datetime]:
    """Return the next N ET slot datetimes honoring notice and windows."""
    count = cfg.s("booking.slots_to_propose", 3)
    length = cfg.s("booking.slot_length_minutes", 30)
    min_notice = timedelta(hours=cfg.s("booking.min_notice_hours", 20))
    days_ahead = cfg.s("booking.days_ahead", 5)
    windows = cfg.s("booking.windows_et", [["09:30", "12:00"], ["13:00", "16:30"]])
    taken = taken or []

    slots: list[datetime] = []
    cursor = datetime.now(ET)
    earliest = cursor + min_notice
    for day_offset in range(1, days_ahead + 7):
        day = (cursor + timedelta(days=day_offset)).date()
        if day.weekday() >= 5:
            continue
        for start_s, end_s in windows:
            start_t = time.fromisoformat(start_s)
            end_t = time.fromisoformat(end_s)
            slot = datetime.combine(day, start_t, tzinfo=ET)
            window_end = datetime.combine(day, end_t, tzinfo=ET)
            while slot + timedelta(minutes=length) <= window_end:
                if slot >= earliest and not any(
                        abs((slot - t).total_seconds()) < length * 60
                        for t in taken):
                    slots.append(slot)
                    if len(slots) >= count * 3:
                        break
                slot += timedelta(minutes=length * 2)  # space options out
            if len(slots) >= count * 3:
                break
        if len(slots) >= count * 3:
            break
    # spread across days: pick at most one per half-day until count is met
    picked: list[datetime] = []
    for slot in slots:
        if len(picked) >= count:
            break
        if all(p.date() != slot.date() or
               (p.hour < 13) != (slot.hour < 13) for p in picked):
            picked.append(slot)
    return picked or slots[:count]


def format_slots(slots: list[datetime]) -> list[str]:
    return [s.strftime("%a %b %-d, %-I:%M %p ET") for s in slots]


def build_ics(cfg: Config, *, start: datetime, attendee_email: str,
              attendee_name: str, summary: str,
              description: str = "") -> str:
    length = cfg.s("booking.slot_length_minutes", 30)
    end = start + timedelta(minutes=length)
    organizer = cfg.sender_email
    fmt = "%Y%m%dT%H%M%SZ"
    to_utc = lambda d: d.astimezone(ZoneInfo("UTC")).strftime(fmt)  # noqa: E731
    uid = f"{uuid.uuid4()}@getunicornclub.com"
    return "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Unicorn Club//Vicky Agent//EN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{to_utc(datetime.now(ET))}",
        f"DTSTART:{to_utc(start)}",
        f"DTEND:{to_utc(end)}",
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{description}",
        f"ORGANIZER;CN=Vicky Steyn:mailto:{organizer}",
        f"ATTENDEE;CN={attendee_name};RSVP=TRUE:mailto:{attendee_email}",
        f"ATTENDEE;CN=Vicky Steyn:mailto:{organizer}",
        "STATUS:CONFIRMED",
        "END:VEVENT",
        "END:VCALENDAR",
    ])
