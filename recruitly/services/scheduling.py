"""Interview slots: parsing the slot form, double-booking checks, grouping by day and .ics export.

Slot times are stored as naive "wall clock" datetimes in the org's time zone
(RECRUITLY_TIMEZONE). Everything here is a pure function so it's easy to test.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

T = TypeVar("T")

LENGTHS = (15, 20, 30, 45, 60, 90)
MIN_MINUTES, MAX_MINUTES = 5, 240
MAX_REPEAT = 16
MAX_LOCATION = 300
MAX_LABEL = 80

_TIME_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?\s*m?\.?\s*$", re.I)


# ------------------------------------------------------------------ parsing

def parse_date(text: str) -> date | None:
    """`2026-10-27` (what <input type=date> sends) or `10/27/2026`."""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_time(text: str) -> tuple[int, int] | None:
    """`18:30` (what <input type=time> sends), `6:30 PM`, `6pm`. Returns (hour, minute)."""
    m = _TIME_RE.match(text or "")
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if minute > 59:
        return None
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm == "p" else 0)
    elif m.group(2) is None or hour > 23:
        return None  # a bare "6" is ambiguous
    return hour, minute


def _int(text: str) -> int | None:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


@dataclass
class SlotInput:
    starts: list[datetime]
    minutes: int
    location: str | None
    label: str | None


def parse_slot_input(date_s: str, time_s: str, minutes_s: str, location: str = "", label: str = "",
                     repeat_s: str = "1") -> tuple[SlotInput | None, dict[str, str]]:
    """Validate the "add slots" form. `repeat` makes that many back-to-back slots."""
    errors: dict[str, str] = {}
    day = parse_date(date_s)
    if day is None:
        errors["date"] = "Pick a date."
    hm = parse_time(time_s)
    if hm is None:
        errors["time"] = "Enter a start time like 18:30 or 6:30 PM."
    minutes = _int(minutes_s)
    if minutes is None or not MIN_MINUTES <= minutes <= MAX_MINUTES:
        errors["minutes"] = f"Length must be between {MIN_MINUTES} and {MAX_MINUTES} minutes."
    repeat = _int(repeat_s or "1")
    if repeat is None or not 1 <= repeat <= MAX_REPEAT:
        errors["repeat"] = f"Make between 1 and {MAX_REPEAT} slots at a time."
    location = " ".join((location or "").split())
    if len(location) > MAX_LOCATION:
        errors["location"] = f"Keep the location under {MAX_LOCATION} characters."
    label = " ".join((label or "").split())
    if len(label) > MAX_LABEL:
        errors["label"] = f"Keep the label under {MAX_LABEL} characters."
    if errors:
        return None, errors
    first = datetime(day.year, day.month, day.day, *hm)
    starts = [first + timedelta(minutes=minutes * i) for i in range(repeat)]
    return SlotInput(starts=starts, minutes=minutes, location=location or None, label=label or None), {}


def location_url(location: str | None) -> str | None:
    """The location as a link, if it is one (a Zoom/Meet/Teams link). Only http(s) is ever linked."""
    loc = (location or "").strip()
    if re.match(r"^https?://\S+$", loc, re.I):
        return loc
    if re.match(r"^(\w[\w-]*\.)*(zoom\.us|meet\.google\.com|teams\.microsoft\.com)/\S*$", loc, re.I):
        return "https://" + loc
    return None


# ------------------------------------------------------------------ double booking

def overlaps(a_start: datetime, a_minutes: int, b_start: datetime, b_minutes: int) -> bool:
    """True if two time ranges overlap. Back-to-back (one ends as the other starts) is fine."""
    return a_start < b_start + timedelta(minutes=b_minutes) and b_start < a_start + timedelta(minutes=a_minutes)


@dataclass(frozen=True)
class Busy:
    """Something already on someone's calendar: a slot id, its start and its length."""
    key: int
    start: datetime
    minutes: int


def first_overlap(start: datetime, minutes: int, busy: Iterable[Busy], ignore: int | None = None) -> Busy | None:
    for b in sorted(busy, key=lambda b: b.start):
        if b.key != ignore and overlaps(start, minutes, b.start, b.minutes):
            return b
    return None


def booking_conflicts(starts: Sequence[datetime], minutes: int, people: dict[int, Iterable[Busy]],
                      ignore: int | None = None) -> dict[int, tuple[datetime, Busy]]:
    """For each person (interviewer or applicant id) → (the new start that clashes, the existing booking)."""
    out: dict[int, tuple[datetime, Busy]] = {}
    for pid, busy in people.items():
        busy = list(busy)
        for s in starts:
            hit = first_overlap(s, minutes, busy, ignore)
            if hit:
                out[pid] = (s, hit)
                break
    return out


def status_after_booking(status: str) -> str:
    """Booking an interview moves a new applicant to Interviewing; later stages are left alone."""
    return "interviewing" if status == "applied" else status


# ------------------------------------------------------------------ display

def group_by_day(items: Iterable[T], start: Callable[[T], datetime]) -> list[tuple[date, list[T]]]:
    days: dict[date, list[T]] = {}
    for it in sorted(items, key=start):
        days.setdefault(start(it).date(), []).append(it)
    return list(days.items())


def clock(d: datetime) -> str:
    """6:00 PM"""
    return f"{d.hour % 12 or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'}"


def time_range(start: datetime, minutes: int) -> str:
    """6:00 – 6:30 PM, or 11:30 AM – 12:15 PM"""
    end = start + timedelta(minutes=minutes)
    a, b = clock(start), clock(end)
    if a[-2:] == b[-2:]:
        a = a[:-3]
    return f"{a} – {b}"


def day_label(d: date, today: date | None = None) -> str:
    """Tuesday, Oct 27 (with "Today"/"Tomorrow" when it applies)."""
    base = f"{d:%A}, {d:%b} {d.day}"
    if today is not None:
        if d == today:
            return f"Today · {base}"
        if d == today + timedelta(days=1):
            return f"Tomorrow · {base}"
    if today is not None and d.year != today.year:
        base += f", {d.year}"
    return base


def slot_choice_label(start: datetime, minutes: int, location: str | None) -> str:
    """One line for a <select>: Tue Oct 27 · 6:00 – 6:30 PM · GSB 2.124"""
    parts = [f"{start:%a} {start:%b} {start.day}", time_range(start, minutes)]
    if location:
        parts.append("Zoom" if location_url(location) and "zoom" in location.lower() else
                     ("Video call" if location_url(location) else location))
    return " · ".join(parts)


# ------------------------------------------------------------------ time zones

def get_zone(name: str | None) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def local_now(tz_name: str | None) -> datetime:
    """Current wall-clock time in the org's time zone, naive like stored slot times."""
    return datetime.now(get_zone(tz_name)).replace(tzinfo=None, microsecond=0)


def to_utc(naive: datetime, tz_name: str | None) -> datetime:
    return naive.replace(tzinfo=get_zone(tz_name)).astimezone(timezone.utc)


# ------------------------------------------------------------------ .ics export

@dataclass
class CalEvent:
    uid: str
    start: datetime  # aware
    minutes: int
    summary: str
    location: str | None = None
    description: str = ""
    url: str | None = None


def ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets continue on the next line after a space."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 75:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def _utc(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(events: Iterable[CalEvent], cal_name: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Recruitly//Interview schedule//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_escape(cal_name)}"]
    for e in events:
        lines += ["BEGIN:VEVENT", f"UID:{e.uid}", f"DTSTAMP:{_utc(now)}", f"DTSTART:{_utc(e.start)}",
                  f"DTEND:{_utc(e.start + timedelta(minutes=e.minutes))}", f"SUMMARY:{ics_escape(e.summary)}"]
        if e.location:
            lines.append(f"LOCATION:{ics_escape(e.location)}")
        if e.description:
            lines.append(f"DESCRIPTION:{ics_escape(e.description)}")
        if e.url:
            lines.append(f"URL:{e.url}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
