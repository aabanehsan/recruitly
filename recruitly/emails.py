"""Email templates and per-applicant drafts (copy, or open as a mailto: link). Recruitly never sends email."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .models import Applicant, EmailTemplate, InterviewSlot, Status, User
from .schedule import next_interviews
from .services.emails import (
    AUDIENCE_ALL, AUDIENCE_INTERVIEW, DEFAULT_TEMPLATES, MAILTO_SAFE_LENGTH, PLACEHOLDERS, SLOT_PLACEHOLDERS,
    draft_values, make_draft, placeholders_in, validate_template,
)
from .sync import get_setting, set_setting
from .web import redirect, require_admin, templates

SEEDED = "email_templates_seeded"


def audiences() -> list[tuple[str, str]]:
    return ([(AUDIENCE_INTERVIEW, "Booked for an upcoming interview")]
            + [(s.value, f"Status: {s.label}") for s in Status] + [(AUDIENCE_ALL, "Everyone")])


AUDIENCE_LABELS = dict(audiences())
templates.env.globals.update(AUDIENCE_LABELS=AUDIENCE_LABELS)


def ensure_email_templates(session: Session) -> None:
    """Add the starter invite / offer / rejection templates once. Deleted ones don't come back."""
    if get_setting(session, SEEDED):
        return
    if session.scalars(select(EmailTemplate.id).limit(1)).first() is None:
        for i, (name, audience, subject, body) in enumerate(DEFAULT_TEMPLATES):
            session.add(EmailTemplate(name=name, audience=audience, subject=subject, body=body, position=i))
    set_setting(session, SEEDED, "1")
    session.commit()


def all_templates(session: Session) -> list[EmailTemplate]:
    return list(session.scalars(select(EmailTemplate).order_by(EmailTemplate.position, EmailTemplate.id)))


def profile_templates(session: Session) -> list[EmailTemplate]:
    return all_templates(session)


def get_template(session: Session, template_id: int) -> EmailTemplate:
    t = session.get(EmailTemplate, template_id)
    if t is None:
        raise HTTPException(404, "Email template not found")
    return t


def recipients(session: Session, audience: str) -> list[tuple[Applicant, InterviewSlot | None]]:
    nxt = next_interviews(session)
    if audience == AUDIENCE_INTERVIEW:
        aps = {a.id: a for a in session.scalars(select(Applicant).where(Applicant.id.in_(list(nxt))))}
        return [(aps[i], s) for i, s in sorted(nxt.items(), key=lambda kv: kv[1].starts_at) if i in aps]
    stmt = select(Applicant).order_by(Applicant.last_name, Applicant.first_name)
    if audience != AUDIENCE_ALL:
        stmt = stmt.where(Applicant.status == audience)
    return [(a, nxt.get(a.id)) for a in session.scalars(stmt)]


def audience_counts(session: Session) -> dict[str, int]:
    counts = dict(session.execute(select(Applicant.status, func.count()).group_by(Applicant.status)).all())
    counts[AUDIENCE_ALL] = sum(counts.values())
    counts[AUDIENCE_INTERVIEW] = len(next_interviews(session))
    return counts


def draft_for(t: EmailTemplate, ap: Applicant, slot: InterviewSlot | None, me: User):
    values = draft_values(
        first_name=ap.first_name, last_name=ap.last_name, preferred_name=ap.preferred_name, email=ap.email,
        slot_start=slot.starts_at if slot else None, slot_minutes=slot.minutes if slot else None,
        slot_location=slot.location if slot else None, org_name=settings.org_name, cycle_name=settings.cycle_name,
        sender_name=me.name,
    )
    return make_draft(ap.id, ap.display_name, t.subject, t.body, values)


def _form_ctx(t: EmailTemplate | None, values: dict, errors: dict) -> dict:
    return {"t": t, "values": values, "errors": errors, "audiences": audiences(), "placeholders": PLACEHOLDERS}


def register_email_routes(app: FastAPI) -> None:
    @app.get("/emails", response_class=HTMLResponse)
    def emails_page(request: Request, msg: str = "", me: User = Depends(require_admin),
                    session: Session = Depends(get_session)):
        return templates.TemplateResponse(request, "emails.html", {
            "templates_": all_templates(session), "counts": audience_counts(session), "msg": msg,
            "placeholders": PLACEHOLDERS,
        })

    @app.get("/emails/new", response_class=HTMLResponse)
    def new_template_page(request: Request, me: User = Depends(require_admin)):
        return templates.TemplateResponse(request, "email_edit.html", _form_ctx(None, {"audience": AUDIENCE_ALL}, {}))

    @app.get("/emails/{template_id}/edit", response_class=HTMLResponse)
    def edit_template_page(request: Request, template_id: int, me: User = Depends(require_admin),
                           session: Session = Depends(get_session)):
        t = get_template(session, template_id)
        values = {"name": t.name, "audience": t.audience, "subject": t.subject, "body": t.body}
        return templates.TemplateResponse(request, "email_edit.html", _form_ctx(t, values, {}))

    def _save(request: Request, session: Session, t: EmailTemplate | None, name: str, audience: str,
              subject: str, body: str):
        values = {"name": name, "audience": audience, "subject": subject, "body": body}
        errors = validate_template(name, subject, body)
        if audience not in AUDIENCE_LABELS:
            errors["audience"] = "Pick who this email is for."
        if errors:
            return templates.TemplateResponse(request, "email_edit.html", _form_ctx(t, values, errors),
                                              status_code=422)
        creating = t is None
        if creating:
            last = session.scalars(select(func.max(EmailTemplate.position))).first()
            t = EmailTemplate(position=(last or 0) + 1)
            session.add(t)
        t.name, t.audience, t.subject, t.body = name.strip(), audience, subject.strip(), body.replace("\r\n", "\n")
        session.commit()
        return redirect("/emails", msg=f"Template “{t.name}” {'added' if creating else 'saved'}")

    @app.post("/emails/new", response_class=HTMLResponse)
    def create_template(request: Request, name: str = Form(""), audience: str = Form(AUDIENCE_ALL),
                        subject: str = Form(""), body: str = Form(""), me: User = Depends(require_admin),
                        session: Session = Depends(get_session)):
        return _save(request, session, None, name, audience, subject, body)

    @app.post("/emails/{template_id}/edit", response_class=HTMLResponse)
    def update_template(request: Request, template_id: int, name: str = Form(""), audience: str = Form(AUDIENCE_ALL),
                        subject: str = Form(""), body: str = Form(""), me: User = Depends(require_admin),
                        session: Session = Depends(get_session)):
        return _save(request, session, get_template(session, template_id), name, audience, subject, body)

    @app.post("/emails/{template_id}/delete")
    def delete_template(template_id: int, me: User = Depends(require_admin), session: Session = Depends(get_session)):
        t = get_template(session, template_id)
        name = t.name
        session.delete(t)
        session.commit()
        return redirect("/emails", msg=f"Deleted “{name}”")

    @app.get("/emails/{template_id}/drafts", response_class=HTMLResponse)
    def drafts_page(request: Request, template_id: int, audience: str = "", applicant: int | None = None,
                    me: User = Depends(require_admin), session: Session = Depends(get_session)):
        t = get_template(session, template_id)
        single = None
        if applicant is not None:
            single = session.get(Applicant, applicant)
            if single is None:
                raise HTTPException(404, "Applicant not found")
            people = [(single, next_interviews(session).get(single.id))]
            audience = ""
        else:
            audience = audience if audience in AUDIENCE_LABELS else t.audience
            people = recipients(session, audience)
        drafts = [draft_for(t, ap, slot, me) for ap, slot in people]
        uses_slot = bool(SLOT_PLACEHOLDERS & set(placeholders_in(t.subject + t.body)))
        return templates.TemplateResponse(request, "email_drafts.html", {
            "t": t, "drafts": drafts, "audience": audience, "audiences": audiences(),
            "counts": audience_counts(session), "single": single, "uses_slot": uses_slot,
            "all_to": ", ".join(d.to for d in drafts if d.to), "mailto_max": MAILTO_SAFE_LENGTH,
        })
