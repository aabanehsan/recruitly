"""Pure helpers for re-syncing a saved Google Sheet: what changed, which mapping to use, and "synced 2h ago"."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

# Labels for the fields a sync can change, in display order.
SYNC_FIELD_LABELS: dict[str, str] = {
    "first_name": "First name", "last_name": "Last name", "preferred_name": "Preferred name", "email": "Email",
    "eid": "UT EID", "phone": "Phone", "major": "Major", "second_major": "Second major", "minor": "Minor",
    "classification": "Classification", "grad_term": "Graduation", "gpa": "GPA", "hometown": "Hometown",
    "linkedin": "LinkedIn", "resume_url": "Resume", "instagram": "Instagram", "involvement": "Involvement",
    "why_join": "Why join", "fun_fact": "Fun fact", "availability": "Availability", "headshot_source": "Headshot",
}


def _same(old: Any, new: Any) -> bool:
    if isinstance(old, (int, float)) or isinstance(new, (int, float)):
        try:
            return abs(float(old) - float(new)) < 1e-9
        except (TypeError, ValueError):
            return False
    return str(old if old is not None else "").strip() == str(new if new is not None else "").strip()


def changed_fields(existing: Mapping[str, Any], incoming: Mapping[str, Any],
                   fields: Iterable[str] = SYNC_FIELD_LABELS) -> list[str]:
    """Fields an import would overwrite. Blank incoming answers never erase saved data, so they don't count."""
    out = []
    for f in fields:
        new = incoming.get(f)
        if new is None or new == "":
            continue
        if not _same(existing.get(f), new):
            out.append(f)
    return out


def describe_changes(fields: Iterable[str], limit: int = 4) -> str:
    labels = [SYNC_FIELD_LABELS.get(f, f) for f in fields]
    if len(labels) > limit:
        return ", ".join(labels[:limit]) + f" +{len(labels) - limit} more"
    return ", ".join(labels)


def merge_mapping(headers: list[str], saved: Mapping[str, str | None] | None,
                  auto: Mapping[str, str | None]) -> dict[str, str | None]:
    """Reuse the column mapping an admin fixed on an earlier sync; new or renamed columns get the automatic guess."""
    saved = saved or {}
    return {h: (saved[h] if h in saved else auto.get(h)) for h in headers}


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def time_ago(then: datetime | None, now: datetime | None = None) -> str:
    """'just now', '5 minutes ago', '3 hours ago', 'yesterday', '4 days ago', or a date for older times."""
    if then is None:
        return "never"
    now = _aware(now or datetime.now(timezone.utc))
    secs = (now - _aware(then)).total_seconds()
    if secs < 60:
        return "just now"
    mins = int(secs // 60)
    if mins < 60:
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    then = _aware(then)
    return f"{then:%b} {then.day}, {then.year}"


def sync_summary(created: int, updated: int, unchanged: int) -> str:
    parts = [f"{created} new", f"{updated} updated", f"{unchanged} unchanged"]
    return ", ".join(parts)
