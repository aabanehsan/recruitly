"""Two-step import: build a preview of cleaned rows, then apply it once the user confirms."""

from __future__ import annotations

import csv
import io
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Applicant, ImportPreview
from .cleaning import HEADER_KEYWORDS, clean_row, map_headers
from .headshots import HeadshotError, download_url, save_headshot

MAPPABLE_FIELDS = list(HEADER_KEYWORDS)
PROFILE_KEYS = [
    "first_name", "last_name", "preferred_name", "email", "eid", "phone", "major", "second_major", "minor",
    "classification", "grad_term", "gpa", "hometown", "linkedin", "resume_url", "instagram", "involvement",
    "why_join", "fun_fact", "availability",
]


class ImportError_(ValueError):
    pass


# ---------------------------------------------------------------- reading input


def read_csv(data: bytes) -> tuple[list[str], list[list[str]]]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ImportError_("the file is empty")
    headers = [h.strip() for h in rows[0]]
    if len(headers) < 2:
        raise ImportError_("couldn't find columns; export the responses sheet as CSV (File → Download → .csv)")
    body = [r + [""] * (len(headers) - len(r)) for r in rows[1:]]
    return headers, body


SHEET_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")


def sheet_csv_url(url: str) -> str:
    m = SHEET_RE.search(url)
    if not m:
        raise ImportError_("that isn't a Google Sheets link")
    gid = re.search(r"[#&?]gid=(\d+)", url)
    out = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"
    return out + (f"&gid={gid.group(1)}" if gid else "")


def fetch_sheet(url: str, client: httpx.Client | None = None) -> bytes:
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True)
    try:
        r = client.get(sheet_csv_url(url))
    except httpx.HTTPError as e:
        raise ImportError_(f"couldn't reach Google Sheets: {e}") from e
    finally:
        if own:
            client.close()
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or "text/html" in ctype:
        raise ImportError_(
            "Google wouldn't share that sheet. In the sheet, click Share → General access → "
            "'Anyone with the link' (Viewer), or download it as CSV and upload the file instead."
        )
    return r.content


# ---------------------------------------------------------------- preview


@dataclass
class PreviewRow:
    row_num: int
    values: dict[str, Any]
    issues: list[dict[str, str]]
    action: str  # create | update | skip | duplicate
    existing_id: int | None = None
    reason: str = ""


@dataclass
class Preview:
    token: str
    source_name: str
    headers: list[str]
    raw_rows: list[list[str]]
    mapping: dict[str, str | None]
    rows: list[PreviewRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        c = {"create": 0, "update": 0, "skip": 0, "duplicate": 0, "fixed": 0, "warning": 0}
        for r in self.rows:
            c[r.action] += 1
            c["fixed"] += sum(1 for i in r.issues if i["level"] == "fixed")
            c["warning"] += sum(1 for i in r.issues if i["level"] == "warning")
        return c

    def to_json(self) -> str:
        return json.dumps({"headers": self.headers, "raw_rows": self.raw_rows, "mapping": self.mapping})


def build_preview(
    session: Session,
    headers: list[str],
    raw_rows: list[list[str]],
    source_name: str,
    mapping: dict[str, str | None] | None = None,
    email_domain: str | None = None,
    token: str | None = None,
) -> Preview:
    mapping = mapping or map_headers(headers)
    pv = Preview(token or secrets.token_urlsafe(16), source_name, headers, raw_rows, mapping)

    mapped = set(v for v in mapping.values() if v)
    if "email" not in mapped:
        pv.problems.append("No column is mapped to Email. Pick the email column below so applicants can be matched.")
    if not ({"first_name", "full_name"} & mapped):
        pv.problems.append("No column is mapped to a name. Pick the name column(s) below.")

    cleaned: list[PreviewRow] = []
    for i, raw in enumerate(raw_rows, start=2):  # row 1 is the header
        row: dict[str, str] = {}
        for col, h in enumerate(headers):
            fld = mapping.get(h)
            if fld and col < len(raw):
                row[fld] = raw[col]
        res = clean_row(row, email_domain=email_domain)
        pr = PreviewRow(i, res.values, [x.to_dict() for x in res.issues], "create" if res.ok else "skip")
        if not res.ok:
            pr.reason = "; ".join(f"{x.field}: {x.message}" for x in res.issues if x.level == "error")
        cleaned.append(pr)

    # Duplicate submissions in the same file: keep the newest one per email.
    latest: dict[str, PreviewRow] = {}
    for pr in cleaned:
        email = pr.values.get("email")
        if pr.action == "skip" or not email:
            continue
        prev = latest.get(email)
        if prev is None or (pr.values.get("submitted_at") or "") >= (prev.values.get("submitted_at") or ""):
            if prev:
                prev.action, prev.reason = "duplicate", f"newer submission in row {pr.row_num}"
            latest[email] = pr
        else:
            pr.action, pr.reason = "duplicate", f"newer submission in row {prev.row_num}"

    # Existing applicants → update instead of create.
    for pr in latest.values():
        email, eid = pr.values.get("email"), pr.values.get("eid")
        conds = [Applicant.email == email] + ([Applicant.eid == eid] if eid else [])
        existing = session.scalars(select(Applicant).where(or_(*conds))).first()
        if existing:
            pr.action, pr.existing_id = "update", existing.id
            pr.reason = f"matches existing profile #{existing.id} ({existing.display_name})"

    pv.rows = cleaned
    return pv


def save_preview(session: Session, pv: Preview) -> None:
    existing = session.get(ImportPreview, pv.token)
    if existing:
        existing.payload = pv.to_json()
    else:
        session.add(ImportPreview(token=pv.token, source_name=pv.source_name, payload=pv.to_json()))
    session.commit()


def load_preview(session: Session, token: str, email_domain: str | None = None,
                 mapping: dict[str, str | None] | None = None) -> Preview:
    stored = session.get(ImportPreview, token)
    if stored is None:
        raise ImportError_("this import preview expired; upload the file again")
    data = json.loads(stored.payload)
    return build_preview(session, data["headers"], data["raw_rows"], stored.source_name,
                         mapping=mapping or data["mapping"], email_domain=email_domain, token=token)


# ---------------------------------------------------------------- apply


@dataclass
class ImportSummary:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    headshots_saved: int = 0
    headshots_missing: list[str] = field(default_factory=list)
    applicant_ids: list[int] = field(default_factory=list)


def apply_preview(session: Session, pv: Preview, fetch_headshots: bool = True,
                  client: httpx.Client | None = None) -> ImportSummary:
    if pv.problems:
        raise ImportError_(pv.problems[0])
    summary = ImportSummary()
    for pr in pv.rows:
        if pr.action in ("skip", "duplicate"):
            summary.skipped += 1
            continue
        v = pr.values
        ap = session.get(Applicant, pr.existing_id) if pr.existing_id else None
        if ap is None:
            ap = Applicant(source="import", status="applied", first_name=v["first_name"],
                           last_name=v.get("last_name") or "", email=v["email"])
            session.add(ap)
            summary.created += 1
        else:
            summary.updated += 1

        for k in PROFILE_KEYS:
            val = v.get(k)
            if val is not None and val != "":
                setattr(ap, k, val)

        # EID must be unique; don't let a typo steal someone else's.
        new_eid, ap.eid = ap.eid, None
        session.flush()  # gives a new applicant its id before the uniqueness check
        if new_eid:
            clash = session.scalars(select(Applicant).where(Applicant.eid == new_eid, Applicant.id != ap.id)).first()
            if clash:
                pr.issues.append({"field": "eid", "level": "warning",
                                  "message": f"EID {new_eid} already belongs to {clash.display_name}; left blank"})
            else:
                ap.eid = new_eid
        if v.get("submitted_at"):
            ap.submitted_at = datetime.fromisoformat(v["submitted_at"])
        ap.import_notes = json.dumps([i for i in pr.issues if i["level"] in ("fixed", "warning")])
        session.flush()
        summary.applicant_ids.append(ap.id)

        src = v.get("headshot_source")
        if src and src != ap.headshot_source:
            ap.headshot_source = src
            data = download_url(src, client) if fetch_headshots else None
            if data:
                try:
                    ap.headshot_path = save_headshot(data, ap.headshot_path)
                    summary.headshots_saved += 1
                except HeadshotError:
                    summary.headshots_missing.append(ap.display_name)
            elif not ap.headshot_path:
                summary.headshots_missing.append(ap.display_name)
        elif src is None and not ap.headshot_path:
            summary.headshots_missing.append(ap.display_name)

    stored = session.get(ImportPreview, pv.token)
    if stored:
        session.delete(stored)
    session.commit()
    return summary
