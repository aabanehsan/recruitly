from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Status(str, Enum):
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    FINAL_ROUND = "final_round"
    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CUT = "cut"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


# Fields an applicant profile holds, in display order. The importer and the
# edit form both use this so they never drift apart.
PROFILE_FIELDS: list[tuple[str, str]] = [
    ("first_name", "First name"),
    ("last_name", "Last name"),
    ("preferred_name", "Preferred name"),
    ("email", "Email"),
    ("eid", "UT EID"),
    ("phone", "Phone"),
    ("major", "Major"),
    ("second_major", "Second major"),
    ("minor", "Minor / certificate"),
    ("classification", "Classification"),
    ("grad_term", "Expected graduation"),
    ("gpa", "GPA"),
    ("hometown", "Hometown"),
    ("linkedin", "LinkedIn"),
    ("resume_url", "Resume link"),
    ("instagram", "Instagram"),
    ("involvement", "Involvement & experience"),
    ("why_join", "Why do you want to join?"),
    ("fun_fact", "Fun fact"),
    ("availability", "Availability"),
]
LONG_TEXT_FIELDS = {"involvement", "why_join", "fun_fact", "availability"}


class Applicant(Base):
    __tablename__ = "applicants"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    preferred_name: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    eid: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    major: Mapped[str | None] = mapped_column(String(120))
    second_major: Mapped[str | None] = mapped_column(String(120))
    minor: Mapped[str | None] = mapped_column(String(200))
    classification: Mapped[str | None] = mapped_column(String(30))
    grad_term: Mapped[str | None] = mapped_column(String(20))
    gpa: Mapped[float | None] = mapped_column(Float)
    hometown: Mapped[str | None] = mapped_column(String(120))
    linkedin: Mapped[str | None] = mapped_column(String(300))
    resume_url: Mapped[str | None] = mapped_column(String(500))
    instagram: Mapped[str | None] = mapped_column(String(80))
    involvement: Mapped[str | None] = mapped_column(Text)
    why_join: Mapped[str | None] = mapped_column(Text)
    fun_fact: Mapped[str | None] = mapped_column(Text)
    availability: Mapped[str | None] = mapped_column(Text)

    headshot_path: Mapped[str | None] = mapped_column(String(300))
    headshot_source: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default=Status.APPLIED.value)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # JSON list of {"field", "message"} notes from the cleaning step
    import_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def display_name(self) -> str:
        first = self.preferred_name or self.first_name
        return f"{first} {self.last_name}".strip()

    @property
    def initials(self) -> str:
        return ((self.first_name[:1] or "") + (self.last_name[:1] or "")).upper() or "?"

    @property
    def status_enum(self) -> Status:
        try:
            return Status(self.status)
        except ValueError:
            return Status.APPLIED

    @property
    def notes_list(self) -> list[dict]:
        try:
            return json.loads(self.import_notes or "[]")
        except json.JSONDecodeError:
            return []


class ImportPreview(Base):
    """Cleaned rows waiting for the user to confirm an import."""

    __tablename__ = "import_previews"

    token: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(300))
    payload: Mapped[str] = mapped_column(Text)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
