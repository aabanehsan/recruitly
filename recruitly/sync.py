"""Settings page and one-click re-sync from a saved Google Sheet (through the normal import preview)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import resources

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .demo import DEMO_SHEET_URL
from .models import AppSetting, User, utcnow
from .services.cleaning import map_headers
from .services.importer import ImportError_, Preview, build_preview, fetch_sheet, read_csv, save_preview, sheet_csv_url
from .services.scheduling import get_zone
from .services.sync import merge_mapping, sync_summary, time_ago
from .web import redirect, require_admin, templates

SHEET_URL, SHEET_MAPPING, LAST_SYNCED, LAST_RESULT = "sheet_url", "sheet_mapping", "last_synced_at", "last_sync_result"
SYNC_SOURCE = "Google Sheet sync"

templates.env.filters["ago"] = time_ago


def to_local(d: datetime | None) -> datetime | None:
    """A stored UTC time as wall-clock time in the org's time zone."""
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(get_zone(settings.timezone)).replace(tzinfo=None)


templates.env.filters["local"] = to_local


# ------------------------------------------------------------------ key/value settings

def get_setting(session: Session, key: str) -> str | None:
    row = session.get(AppSetting, key)
    return row.value if row else None


def set_setting(session: Session, key: str, value: str | None) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def sync_state(session: Session) -> dict:
    last = get_setting(session, LAST_SYNCED)
    return {
        "url": get_setting(session, SHEET_URL) or "",
        "last": datetime.fromisoformat(last) if last else None,
        "result": get_setting(session, LAST_RESULT) or "",
    }


def save_sheet_url(session: Session, url: str) -> None:
    """Save (or clear) the sync link. A different sheet starts over: no saved mapping, never synced."""
    url = url.strip()
    if url:
        sheet_csv_url(url)  # raises ImportError_ for anything that isn't a Sheets link
    if url != (get_setting(session, SHEET_URL) or ""):
        for key in (SHEET_MAPPING, LAST_SYNCED, LAST_RESULT):
            set_setting(session, key, None)
    set_setting(session, SHEET_URL, url or None)


def fetch_for_sync(url: str) -> bytes:
    """Download the sheet. The demo's made-up sheet link reads a bundled CSV instead, so sync works offline."""
    if url == DEMO_SHEET_URL:
        return resources.files("recruitly").joinpath("sample_data", "sheet_sync.csv").read_bytes()
    return fetch_sheet(url)


def sync_preview(session: Session, url: str) -> Preview:
    headers, rows = read_csv(fetch_for_sync(url))
    saved = get_setting(session, SHEET_MAPPING)
    mapping = merge_mapping(headers, json.loads(saved) if saved else None, map_headers(headers))
    return build_preview(session, headers, rows, SYNC_SOURCE, mapping=mapping,
                         email_domain=settings.email_domain, sync=True)


def record_sync(session: Session, pv: Preview, created: int, updated: int, unchanged: int) -> None:
    set_setting(session, LAST_SYNCED, utcnow().isoformat())
    set_setting(session, LAST_RESULT, sync_summary(created, updated, unchanged))
    set_setting(session, SHEET_MAPPING, json.dumps(pv.mapping))
    session.commit()


# ------------------------------------------------------------------ routes

def register_sync_routes(app: FastAPI) -> None:
    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, msg: str = "", error: str = "", me: User = Depends(require_admin),
                      session: Session = Depends(get_session)):
        return templates.TemplateResponse(request, "settings.html", {
            "sync": sync_state(session), "msg": msg, "error": error, "demo_url": DEMO_SHEET_URL,
        })

    @app.post("/settings/sheet")
    def save_sheet(sheet_url: str = Form(""), me: User = Depends(require_admin),
                   session: Session = Depends(get_session)):
        try:
            save_sheet_url(session, sheet_url)
        except ImportError_ as e:
            return redirect("/settings", error=f"Not saved: {e}.")
        session.commit()
        return redirect("/settings", msg="Sheets link saved" if sheet_url.strip() else "Sheets link removed")

    @app.post("/sync")
    def sync_now(next: str = Form(""), me: User = Depends(require_admin), session: Session = Depends(get_session)):
        back = "/import" if next == "/import" else "/settings"
        url = get_setting(session, SHEET_URL)
        if not url:
            return redirect("/settings", error="Save a Google Sheets link first.")
        try:
            pv = sync_preview(session, url)
        except ImportError_ as e:
            return redirect(back, error=f"Sync failed: {e}")
        if pv.problems:
            save_preview(session, pv)  # let them fix the column mapping in the preview
            return redirect(f"/import/{pv.token}")
        c = pv.counts
        if not (c["create"] + c["update"]):
            record_sync(session, pv, 0, 0, c["unchanged"])
            return redirect(back, msg=f"Already up to date: no new or changed responses "
                                      f"({c['unchanged']} checked).")
        save_preview(session, pv)
        return redirect(f"/import/{pv.token}")
