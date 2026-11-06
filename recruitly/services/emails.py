"""Email templates: placeholders, validation, rendering drafts and mailto: links. Nothing here sends email."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote

from .scheduling import clock

# placeholder → what it becomes (shown on the templates page)
PLACEHOLDERS: dict[str, str] = {
    "first_name": "Preferred name if they gave one, otherwise first name",
    "last_name": "Last name",
    "full_name": "First (or preferred) and last name",
    "email": "Applicant's email",
    "slot_time": "Their next interview, e.g. Thursday, Nov 12 at 6:00 PM",
    "slot_date": "Just the day, e.g. Thursday, Nov 12",
    "slot_length": "Interview length, e.g. 30 minutes",
    "slot_location": "Room or video link of their next interview",
    "org_name": "Your org's name",
    "cycle_name": "Recruiting cycle, e.g. Fall Rush",
    "sender_name": "Your name (the admin making the drafts)",
}
SLOT_PLACEHOLDERS = {"slot_time", "slot_date", "slot_length", "slot_location"}

# who gets a draft by default; status values are added by the app
AUDIENCE_INTERVIEW = "interview"
AUDIENCE_ALL = "all"

TOKEN = re.compile(r"\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")
MAILTO_SAFE_LENGTH = 1800  # some email apps cut off longer mailto: links

MAX_NAME, MAX_SUBJECT, MAX_BODY = 60, 200, 10_000


def placeholders_in(text: str) -> list[str]:
    """Placeholder names used in text, in order, without repeats. `{{` and `}}` are literal braces."""
    seen: list[str] = []
    for m in TOKEN.finditer(text or ""):
        name = m.group(1)
        if name and name not in seen:
            seen.append(name)
    return seen


def validate_template(name: str, subject: str, body: str) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not name.strip():
        errors["name"] = "Give the template a name."
    elif len(name.strip()) > MAX_NAME:
        errors["name"] = f"Keep the name under {MAX_NAME} characters."
    if not subject.strip():
        errors["subject"] = "Add a subject line."
    elif len(subject) > MAX_SUBJECT or "\n" in subject.strip():
        errors["subject"] = f"Keep the subject to one line under {MAX_SUBJECT} characters."
    if not body.strip():
        errors["body"] = "Write the email body."
    elif len(body) > MAX_BODY:
        errors["body"] = f"Keep the body under {MAX_BODY:,} characters."
    for key, text in (("subject", subject), ("body", body)):
        unknown = [p for p in placeholders_in(text) if p not in PLACEHOLDERS]
        if unknown and key not in errors:
            errors[key] = ("Unknown placeholder " + ", ".join("{" + p + "}" for p in unknown)
                           + ". Check the list of placeholders below.")
    return errors


def render(text: str, values: dict[str, str | None]) -> tuple[str, list[str]]:
    """Fill placeholders. Ones without a value stay as {name} so they stand out; they're returned as missing."""
    missing: list[str] = []

    def sub(m: re.Match) -> str:
        tok = m.group(0)
        if tok in ("{{", "}}"):
            return tok[0]
        val = values.get(m.group(1))
        if val is None or val == "":
            if m.group(1) not in missing:
                missing.append(m.group(1))
            return tok
        return str(val)

    return TOKEN.sub(sub, text or ""), missing


def slot_day(d: datetime) -> str:
    return f"{d:%A}, {d:%b} {d.day}"


def draft_values(*, first_name: str, last_name: str, preferred_name: str | None, email: str,
                 slot_start: datetime | None = None, slot_minutes: int | None = None,
                 slot_location: str | None = None, org_name: str = "", cycle_name: str = "",
                 sender_name: str = "") -> dict[str, str | None]:
    first = (preferred_name or first_name or "").strip()
    out: dict[str, str | None] = {
        "first_name": first, "last_name": (last_name or "").strip(),
        "full_name": f"{first} {last_name or ''}".strip(), "email": email,
        "org_name": org_name, "cycle_name": cycle_name, "sender_name": sender_name,
        "slot_time": None, "slot_date": None, "slot_length": None, "slot_location": None,
    }
    if slot_start is not None:
        out["slot_time"] = f"{slot_day(slot_start)} at {clock(slot_start)}"
        out["slot_date"] = slot_day(slot_start)
        if slot_minutes:
            out["slot_length"] = f"{slot_minutes} minutes"
        out["slot_location"] = (slot_location or "").strip() or None
    return out


def mailto_link(to: str, subject: str, body: str) -> str:
    """A mailto: URL that opens a filled-in draft in the user's email app. Line breaks become CRLF (RFC 6068)."""
    body = re.sub(r"\r?\n", "\r\n", body)
    return f"mailto:{quote(to, safe='@+')}?subject={quote(subject, safe='')}&body={quote(body, safe='')}"


@dataclass
class Draft:
    applicant_id: int
    name: str
    to: str
    subject: str
    body: str
    missing: list[str] = field(default_factory=list)

    @property
    def mailto(self) -> str:
        return mailto_link(self.to, self.subject, self.body)

    @property
    def mailto_too_long(self) -> bool:
        return len(self.mailto) > MAILTO_SAFE_LENGTH


def make_draft(applicant_id: int, name: str, subject: str, body: str, values: dict[str, str | None]) -> Draft:
    subj, m1 = render(subject, values)
    text, m2 = render(body, values)
    missing = m1 + [m for m in m2 if m not in m1]
    return Draft(applicant_id, name, values.get("email") or "", subj.strip(), text, missing)


DEFAULT_TEMPLATES: list[tuple[str, str, str, str]] = [
    # (name, audience, subject, body)
    ("Interview invite", AUDIENCE_INTERVIEW, "{org_name} interview: {slot_time}",
     "Hi {first_name},\n\n"
     "Thanks for applying to {org_name}! We'd love to get to know you better, so you're invited to interview "
     "with us on {slot_time}.\n\n"
     "Where: {slot_location}\nHow long: {slot_length}\n\n"
     "If that time doesn't work anymore, just reply to this email and we'll find another one.\n\n"
     "See you soon,\n{sender_name}\n{org_name}"),
    ("Offer", "offered", "Welcome to {org_name}!",
     "Hi {first_name},\n\n"
     "Congratulations! We're thrilled to offer you a spot in {org_name}. Everyone who met you during "
     "{cycle_name} was impressed, and we can't wait to have you on the team.\n\n"
     "Please reply to this email to accept your offer. We'll follow up with details about new member "
     "orientation.\n\n"
     "Congrats again,\n{sender_name}\n{org_name}"),
    ("Rejection", "cut", "Your {org_name} application",
     "Hi {first_name},\n\n"
     "Thank you for the time you put into applying to {org_name} this {cycle_name}. We had a lot of strong "
     "applicants, and unfortunately we aren't able to offer you a spot this time.\n\n"
     "This was a hard decision, and we'd love to see you apply again in a future semester.\n\n"
     "Best,\n{sender_name}\n{org_name}"),
]
