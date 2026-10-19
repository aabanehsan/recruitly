"""FastAPI app: pages for the applicant board, profiles, editing and imports."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import __version__
from .config import settings
from .db import get_session, init_db
from .models import LONG_TEXT_FIELDS, PROFILE_FIELDS, Applicant, Status
from .services.cleaning import HEADER_KEYWORDS, MAJORS, clean_row
from .services.headshots import HeadshotError, delete_headshot, match_zip, save_headshot
from .services.importer import (
    PROFILE_KEYS, ImportError_, apply_preview, build_preview, fetch_sheet, load_preview, read_csv, save_preview,
)

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals.update(settings=settings, Status=Status, version=__version__)
templates.env.filters["combine"] = lambda a, b: {**a, **b}
templates.env.filters["shortdate"] = lambda d: f"{d:%b} {d.day}" if d else ""
templates.env.filters["longdate"] = lambda d: (f"{d:%b} {d.day}, {d.year} {d.hour % 12 or 12}:{d:%M} "
                                               f"{'AM' if d.hour < 12 else 'PM'}") if d else ""

FIELD_LABELS = dict(PROFILE_FIELDS) | {
    "full_name": "Full name", "submitted_at": "Timestamp", "headshot": "Headshot upload",
}


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="Recruitly", version=__version__)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.mount("/headshots", StaticFiles(directory=settings.headshot_dir), name="headshots")
    register_routes(app)
    return app


def redirect(url: str, **params: str) -> RedirectResponse:
    q = {k: v for k, v in params.items() if v}
    return RedirectResponse(url + (("?" + urlencode(q)) if q else ""), status_code=303)


def get_applicant(session: Session, applicant_id: int) -> Applicant:
    ap = session.get(Applicant, applicant_id)
    if ap is None:
        raise HTTPException(404, "Applicant not found")
    return ap


def register_routes(app: FastAPI) -> None:
    # ------------------------------------------------------------ board

    @app.get("/", response_class=HTMLResponse)
    def board(request: Request, q: str = "", status: str = "", major: str = "", year: str = "",
              sort: str = "name", msg: str = "", session: Session = Depends(get_session)):
        stmt = select(Applicant)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(
                Applicant.first_name.ilike(like), Applicant.last_name.ilike(like),
                Applicant.preferred_name.ilike(like), Applicant.email.ilike(like),
                Applicant.eid.ilike(like), Applicant.major.ilike(like), Applicant.hometown.ilike(like),
            ))
        if status:
            stmt = stmt.where(Applicant.status == status)
        if major:
            stmt = stmt.where(or_(Applicant.major == major, Applicant.second_major == major))
        if year:
            stmt = stmt.where(Applicant.classification == year)
        order = {
            "name": [Applicant.last_name, Applicant.first_name],
            "newest": [Applicant.created_at.desc()],
            "gpa": [Applicant.gpa.desc().nulls_last()],
            "status": [Applicant.status, Applicant.last_name],
        }.get(sort, [Applicant.last_name])
        applicants = session.scalars(stmt.order_by(*order)).all()

        counts = dict(session.execute(select(Applicant.status, func.count()).group_by(Applicant.status)).all())
        total = sum(counts.values())
        majors = sorted({m for m in session.scalars(select(Applicant.major).distinct()) if m})
        years = [y for y in ["Freshman", "Sophomore", "Junior", "Senior", "Transfer", "Graduate"]
                 if y in set(session.scalars(select(Applicant.classification).distinct()))]
        return templates.TemplateResponse(request, "board.html", {
            "applicants": applicants, "counts": counts, "total": total, "majors": majors, "years": years,
            "f": {"q": q, "status": status, "major": major, "year": year, "sort": sort}, "msg": msg,
        })

    # ------------------------------------------------------------ profiles

    @app.get("/applicants/new", response_class=HTMLResponse)
    def new_form(request: Request):
        return templates.TemplateResponse(request, "edit.html", form_ctx(None, {}, []))

    @app.post("/applicants/new", response_class=HTMLResponse)
    async def create(request: Request, session: Session = Depends(get_session)):
        form = await request.form()
        raw = {k: str(form.get(k, "")) for k in PROFILE_KEYS}
        return save_profile(request, session, None, raw)

    @app.get("/applicants/{applicant_id}", response_class=HTMLResponse)
    def profile(request: Request, applicant_id: int, msg: str = "", session: Session = Depends(get_session)):
        ap = get_applicant(session, applicant_id)
        ids = session.scalars(select(Applicant.id).order_by(Applicant.last_name, Applicant.first_name)).all()
        pos = ids.index(ap.id)
        nav = {"prev": ids[pos - 1] if pos > 0 else None, "next": ids[pos + 1] if pos + 1 < len(ids) else None,
               "pos": pos + 1, "total": len(ids)}
        return templates.TemplateResponse(request, "profile.html", {
            "ap": ap, "fields": PROFILE_FIELDS, "long_fields": LONG_TEXT_FIELDS, "msg": msg, "nav": nav,
        })

    @app.get("/applicants/{applicant_id}/edit", response_class=HTMLResponse)
    def edit_form(request: Request, applicant_id: int, session: Session = Depends(get_session)):
        ap = get_applicant(session, applicant_id)
        values = {k: getattr(ap, k) if getattr(ap, k) is not None else "" for k in PROFILE_KEYS}
        return templates.TemplateResponse(request, "edit.html", form_ctx(ap, values, []))

    @app.post("/applicants/{applicant_id}/edit", response_class=HTMLResponse)
    async def update(request: Request, applicant_id: int, session: Session = Depends(get_session)):
        ap = get_applicant(session, applicant_id)
        form = await request.form()
        raw = {k: str(form.get(k, "")) for k in PROFILE_KEYS}
        return save_profile(request, session, ap, raw)

    @app.post("/applicants/{applicant_id}/status")
    def set_status(applicant_id: int, status: str = Form(...), next: str = Form(""),
                   session: Session = Depends(get_session)):
        ap = get_applicant(session, applicant_id)
        try:
            ap.status = Status(status).value
        except ValueError:
            raise HTTPException(400, "unknown status") from None
        session.commit()
        if next.startswith("/"):
            return RedirectResponse(next, status_code=303)
        return redirect(f"/applicants/{ap.id}", msg=f"Status set to {ap.status_enum.label}")

    @app.post("/applicants/{applicant_id}/headshot")
    async def upload_headshot(applicant_id: int, file: UploadFile = File(...), session: Session = Depends(get_session)):
        ap = get_applicant(session, applicant_id)
        data = await file.read()
        try:
            ap.headshot_path = save_headshot(data, ap.headshot_path)
        except HeadshotError as e:
            return redirect(f"/applicants/{ap.id}", msg=f"Headshot not saved: {e}")
        session.commit()
        return redirect(f"/applicants/{ap.id}", msg="Headshot updated")

    @app.post("/applicants/{applicant_id}/headshot/delete")
    def remove_headshot(applicant_id: int, session: Session = Depends(get_session)):
        ap = get_applicant(session, applicant_id)
        if ap.headshot_path:
            delete_headshot(ap.headshot_path)
            ap.headshot_path = None
            session.commit()
        return redirect(f"/applicants/{ap.id}", msg="Headshot removed")

    @app.post("/applicants/{applicant_id}/delete")
    def delete(applicant_id: int, session: Session = Depends(get_session)):
        ap = get_applicant(session, applicant_id)
        name = ap.display_name
        if ap.headshot_path:
            delete_headshot(ap.headshot_path)
        session.delete(ap)
        session.commit()
        return redirect("/", msg=f"Deleted {name}")

    # ------------------------------------------------------------ import

    @app.get("/import", response_class=HTMLResponse)
    def import_page(request: Request, error: str = ""):
        return templates.TemplateResponse(request, "import.html", {"error": error})

    @app.post("/import")
    async def import_upload(file: UploadFile | None = File(None), sheet_url: str = Form(""),
                            session: Session = Depends(get_session)):
        try:
            if sheet_url.strip():
                data, name = fetch_sheet(sheet_url.strip()), "Google Sheet"
            elif file is not None and file.filename:
                data, name = await file.read(), file.filename
            else:
                raise ImportError_("choose a CSV file or paste a Google Sheets link")
            headers, rows = read_csv(data)
            pv = build_preview(session, headers, rows, name, email_domain=settings.email_domain)
            save_preview(session, pv)
        except ImportError_ as e:
            return redirect("/import", error=str(e))
        return redirect(f"/import/{pv.token}")

    @app.get("/import/{token}", response_class=HTMLResponse)
    def import_preview(request: Request, token: str, session: Session = Depends(get_session)):
        try:
            pv = load_preview(session, token, settings.email_domain)
        except ImportError_ as e:
            return redirect("/import", error=str(e))
        return templates.TemplateResponse(request, "preview.html", {
            "pv": pv, "field_labels": FIELD_LABELS, "mappable": list(HEADER_KEYWORDS),
        })

    @app.post("/import/{token}/mapping")
    async def import_remap(request: Request, token: str, session: Session = Depends(get_session)):
        form = await request.form()
        try:
            pv = load_preview(session, token, settings.email_domain)
        except ImportError_ as e:
            return redirect("/import", error=str(e))
        mapping: dict[str, str | None] = {}
        for i, h in enumerate(pv.headers):
            val = str(form.get(f"col_{i}", ""))
            mapping[h] = val if val in HEADER_KEYWORDS else None
        pv = build_preview(session, pv.headers, pv.raw_rows, pv.source_name, mapping=mapping,
                           email_domain=settings.email_domain, token=token)
        save_preview(session, pv)
        return redirect(f"/import/{token}")

    @app.post("/import/{token}/confirm", response_class=HTMLResponse)
    def import_confirm(request: Request, token: str, session: Session = Depends(get_session)):
        try:
            pv = load_preview(session, token, settings.email_domain)
            summary = apply_preview(session, pv, fetch_headshots=settings.fetch_headshots)
        except ImportError_ as e:
            return redirect(f"/import/{token}" if "expired" not in str(e) else "/import", error=str(e))
        return templates.TemplateResponse(request, "import_done.html", {"s": summary})

    # ------------------------------------------------------------ bulk headshots

    @app.get("/headshots-bulk", response_class=HTMLResponse)
    def bulk_page(request: Request):
        return templates.TemplateResponse(request, "bulk.html", {"result": None, "error": ""})

    @app.post("/headshots-bulk", response_class=HTMLResponse)
    async def bulk_upload(request: Request, file: UploadFile = File(...), overwrite: str = Form(""),
                          session: Session = Depends(get_session)):
        applicants = session.scalars(select(Applicant)).all()
        if not overwrite:
            applicants = [a for a in applicants if not a.headshot_path]
        try:
            matches, unmatched = match_zip(await file.read(), applicants)
        except HeadshotError as e:
            return templates.TemplateResponse(request, "bulk.html", {"result": None, "error": str(e)})
        saved, failed = [], []
        for m in matches:
            ap = session.get(Applicant, m.applicant_id)
            try:
                ap.headshot_path = save_headshot(m.data, ap.headshot_path)
                saved.append((ap, m.filename))
            except HeadshotError as e:
                failed.append(f"{m.filename}: {e}")
        session.commit()
        missing = [a for a in session.scalars(select(Applicant).order_by(Applicant.last_name)) if not a.headshot_path]
        return templates.TemplateResponse(request, "bulk.html", {
            "result": {"saved": saved, "unmatched": unmatched, "failed": failed, "missing": missing}, "error": "",
        })

    # ------------------------------------------------------------ export

    @app.get("/export.csv")
    def export_csv(session: Session = Depends(get_session)):
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = ["id"] + PROFILE_KEYS + ["status", "source", "submitted_at"]
        w.writerow(cols)
        for ap in session.scalars(select(Applicant).order_by(Applicant.last_name)):
            w.writerow([getattr(ap, c) if getattr(ap, c) is not None else "" for c in cols])
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=applicants.csv"})


def form_ctx(ap: Applicant | None, values: dict, issues: list[dict]) -> dict:
    return {"ap": ap, "values": values, "issues": issues, "fields": PROFILE_FIELDS,
            "long_fields": LONG_TEXT_FIELDS, "majors": MAJORS}


def save_profile(request: Request, session: Session, ap: Applicant | None, raw: dict[str, str]):
    """Run manual edits through the same cleaning as imports, so data stays consistent."""
    res = clean_row(raw, email_domain=settings.email_domain)
    issues = [i.to_dict() for i in res.issues if i.level != "fixed" and i.field != "headshot"]
    v = res.values
    if v.get("email"):
        clash = session.scalars(select(Applicant).where(Applicant.email == v["email"])).first()
        if clash and (ap is None or clash.id != ap.id):
            issues.append({"field": "email", "level": "error",
                           "message": f"already used by {clash.display_name}"})
    if v.get("eid"):
        clash = session.scalars(select(Applicant).where(Applicant.eid == v["eid"])).first()
        if clash and (ap is None or clash.id != ap.id):
            issues.append({"field": "eid", "level": "error", "message": f"already used by {clash.display_name}"})
    if any(i["level"] == "error" for i in issues):
        return templates.TemplateResponse(request, "edit.html", form_ctx(ap, raw, issues), status_code=422)

    creating = ap is None
    if creating:
        ap = Applicant(first_name=v["first_name"], last_name=v["last_name"], email=v["email"], source="manual")
        session.add(ap)
    for k in PROFILE_KEYS:
        setattr(ap, k, v.get(k) if v.get(k) != "" else None)
    ap.last_name = v.get("last_name") or ""
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        issues.append({"field": "email", "level": "error", "message": "email or EID already in use"})
        return templates.TemplateResponse(request, "edit.html", form_ctx(ap, raw, issues), status_code=422)
    return redirect(f"/applicants/{ap.id}", msg="Profile created" if creating else "Profile saved")
