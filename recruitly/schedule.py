"""Interview scheduling pages: the schedule, adding/editing slots, booking applicants and .ics export."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .models import Applicant, InterviewSlot, Status, User, slot_interviewers
from .services.auth import safe_next
from .services.scheduling import (
    LENGTHS, MAX_REPEAT, Busy, CalEvent, booking_conflicts, build_ics, clock, day_label, group_by_day, local_now,
    location_url, parse_slot_input, slot_choice_label, status_after_booking, time_range, to_utc,
)
from .web import current_user, redirect, require_admin, templates

templates.env.globals.update(location_url=location_url, time_range=time_range, slot_choice_label=slot_choice_label,
                             clock=clock)
templates.env.filters["slotday"] = lambda d: f"{d:%a} {d:%b} {d.day}" if d else ""

UNBOOKABLE = {Status.CUT.value, Status.DECLINED.value}


def now_local() -> datetime:
    return local_now(settings.timezone)


def get_slot(session: Session, slot_id: int) -> InterviewSlot:
    slot = session.get(InterviewSlot, slot_id)
    if slot is None:
        raise HTTPException(404, "Interview slot not found")
    return slot


def _busy(slots) -> list[Busy]:
    return [Busy(s.id, s.starts_at, s.minutes) for s in slots]


def interviewer_busy(session: Session, user_ids) -> dict[int, list[Busy]]:
    out: dict[int, list[Busy]] = {uid: [] for uid in user_ids}
    if not out:
        return out
    rows = session.execute(
        select(slot_interviewers.c.user_id, InterviewSlot.id, InterviewSlot.starts_at, InterviewSlot.minutes)
        .join(InterviewSlot, InterviewSlot.id == slot_interviewers.c.slot_id)
        .where(slot_interviewers.c.user_id.in_(list(out)))
    ).all()
    for uid, sid, start, minutes in rows:
        out[uid].append(Busy(sid, start, minutes))
    return out


def applicant_busy(session: Session, applicant_id: int) -> list[Busy]:
    return _busy(session.scalars(select(InterviewSlot).where(InterviewSlot.applicant_id == applicant_id)))


def describe_clash(start: datetime, busy: Busy) -> str:
    return f"{start:%a} {start:%b} {start.day} {clock(start)} overlaps their {clock(busy.start)} slot"


def interviewer_errors(session: Session, starts, minutes: int, users: list[User], ignore: int | None = None) -> str:
    clashes = booking_conflicts(starts, minutes, interviewer_busy(session, [u.id for u in users]), ignore)
    names = {u.id: u.name for u in users}
    return " ".join(f"{names[uid]} is already interviewing then ({describe_clash(s, b)})."
                    for uid, (s, b) in clashes.items())


def book(session: Session, slot: InterviewSlot, ap: Applicant) -> tuple[str | None, str]:
    """Put an applicant in a slot. Returns (error, success message)."""
    if slot.applicant_id == ap.id:
        return None, f"{ap.display_name} is already booked in that slot."
    if slot.applicant_id is not None:
        return f"That slot already has {slot.applicant.display_name}. Unbook them first.", ""
    if ap.status in UNBOOKABLE:
        return f"{ap.display_name} is marked {ap.status_enum.label}, so they can't be scheduled.", ""
    clash = booking_conflicts([slot.starts_at], slot.minutes, {ap.id: applicant_busy(session, ap.id)}, slot.id)
    if clash:
        s, b = clash[ap.id]
        return f"{ap.display_name} is already booked then ({describe_clash(s, b)}).", ""
    slot.applicant_id = ap.id
    when = f"{slot.starts_at:%a} {slot.starts_at:%b} {slot.starts_at.day}, {clock(slot.starts_at)}"
    msg = f"Booked {ap.display_name} for {when}."
    new_status = status_after_booking(ap.status)
    if new_status != ap.status:
        ap.status = new_status
        msg += f" Status moved to {ap.status_enum.label}."
    session.commit()
    return None, msg


def _users(session: Session, ids) -> list[User]:
    ids = {int(i) for i in ids}
    return list(session.scalars(select(User).where(User.id.in_(ids)).order_by(User.name))) if ids else []


def slot_event(slot: InterviewSlot, base: str, host: str) -> CalEvent:
    ap = slot.applicant
    title = f"Interview: {ap.display_name}" if ap else "Open interview slot"
    if slot.label:
        title += f" ({slot.label})"
    lines = []
    if slot.interviewers:
        lines.append("Interviewers: " + ", ".join(u.name for u in slot.interviewers))
    if ap:
        facts = " · ".join(x for x in [ap.major, ap.classification] if x)
        lines.append(f"Applicant: {ap.display_name}" + (f" ({facts})" if facts else ""))
        lines.append(f"Profile: {base}/applicants/{ap.id}")
    url = location_url(slot.location)
    if url:
        lines.append(f"Join: {url}")
    stamp = slot.created_at.strftime("%Y%m%d%H%M%S") if slot.created_at else "0"
    return CalEvent(uid=f"recruitly-slot-{slot.id}-{stamp}@{host}", start=to_utc(slot.starts_at, settings.timezone),
                    minutes=slot.minutes, summary=title, location=slot.location, description="\n".join(lines), url=url)


def schedule_ctx(session: Session, me: User, view: str, past: bool, values: dict | None = None,
                 errors: dict | None = None) -> dict:
    now = now_local()
    all_slots = list(session.scalars(select(InterviewSlot).order_by(InterviewSlot.starts_at)))
    upcoming = [s for s in all_slots if s.ends_at > now]
    shown = all_slots if past else upcoming
    if view == "mine":
        shown = [s for s in shown if me.id in s.interviewer_ids]
    elif view == "open":
        shown = [s for s in shown if s.applicant_id is None]
    ctx = {
        "days": group_by_day(shown, lambda s: s.starts_at), "today": now.date(), "now": now,
        "view": view, "past": past, "past_count": len(all_slots) - len(upcoming),
        "counts": {"all": len(upcoming), "open": sum(1 for s in upcoming if s.applicant_id is None),
                   "mine": sum(1 for s in upcoming if me.id in s.interviewer_ids)},
        "booked": sum(1 for s in upcoming if s.applicant_id), "day_label": day_label,
        "values": values or {}, "errors": errors or {}, "lengths": LENGTHS, "max_repeat": MAX_REPEAT,
        "tz": settings.timezone,
    }
    if me.is_admin:
        booked_at: dict[int, InterviewSlot] = {}
        for s in upcoming:
            if s.applicant_id and s.applicant_id not in booked_at:
                booked_at[s.applicant_id] = s
        ctx["bookable"] = list(session.scalars(select(Applicant).where(Applicant.status.not_in(UNBOOKABLE))
                                               .order_by(Applicant.last_name, Applicant.first_name)))
        ctx["booked_at"] = booked_at
        ctx["users"] = list(session.scalars(select(User).order_by(User.name)))
        if not values:
            tomorrow = now.date() + timedelta(days=1)
            ctx["values"] = {"date": tomorrow.isoformat(), "time": "18:00", "minutes": "30", "repeat": "4",
                             "interviewers": []}
    return ctx


def register_schedule_routes(app: FastAPI) -> None:
    @app.get("/schedule", response_class=HTMLResponse)
    def schedule(request: Request, view: str = "all", past: int = 0, msg: str = "", error: str = "",
                 me: User = Depends(current_user), session: Session = Depends(get_session)):
        view = view if view in ("all", "mine", "open") else "all"
        ctx = schedule_ctx(session, me, view, bool(past))
        return templates.TemplateResponse(request, "schedule.html", ctx | {"msg": msg, "error": error})

    @app.post("/schedule/slots", response_class=HTMLResponse)
    def add_slots(request: Request, date: str = Form(""), time: str = Form(""), minutes: str = Form("30"),
                  repeat: str = Form("1"), location: str = Form(""), label: str = Form(""),
                  interviewers: list[int] = Form([]), me: User = Depends(require_admin),
                  session: Session = Depends(get_session)):
        values = {"date": date, "time": time, "minutes": minutes, "repeat": repeat, "location": location,
                  "label": label, "interviewers": interviewers}
        parsed, errors = parse_slot_input(date, time, minutes, location, label, repeat)
        users = _users(session, interviewers)
        if parsed:
            clash = interviewer_errors(session, parsed.starts, parsed.minutes, users)
            if clash:
                errors["interviewers"] = clash
        if errors:
            ctx = schedule_ctx(session, me, "all", False, values, errors)
            return templates.TemplateResponse(request, "schedule.html", ctx | {"open_form": True}, status_code=422)
        for start in parsed.starts:
            session.add(InterviewSlot(starts_at=start, minutes=parsed.minutes, location=parsed.location,
                                      label=parsed.label, interviewers=list(users)))
        session.commit()
        first = parsed.starts[0]
        n = len(parsed.starts)
        return redirect("/schedule", msg=f"Added {n} slot{'' if n == 1 else 's'} on {first:%a} {first:%b} {first.day} "
                                         f"starting {clock(first)}.")

    @app.get("/schedule/slots/{slot_id}/edit", response_class=HTMLResponse)
    def edit_slot_page(request: Request, slot_id: int, me: User = Depends(require_admin),
                       session: Session = Depends(get_session)):
        slot = get_slot(session, slot_id)
        values = {"date": slot.starts_at.date().isoformat(), "time": f"{slot.starts_at:%H:%M}",
                  "minutes": str(slot.minutes), "location": slot.location or "", "label": slot.label or "",
                  "interviewers": sorted(slot.interviewer_ids)}
        users = list(session.scalars(select(User).order_by(User.name)))
        return templates.TemplateResponse(request, "slot_edit.html", {
            "slot": slot, "values": values, "errors": {}, "users": users, "lengths": LENGTHS})

    @app.post("/schedule/slots/{slot_id}/edit", response_class=HTMLResponse)
    def edit_slot(request: Request, slot_id: int, date: str = Form(""), time: str = Form(""),
                  minutes: str = Form("30"), location: str = Form(""), label: str = Form(""),
                  interviewers: list[int] = Form([]), me: User = Depends(require_admin),
                  session: Session = Depends(get_session)):
        slot = get_slot(session, slot_id)
        values = {"date": date, "time": time, "minutes": minutes, "location": location, "label": label,
                  "interviewers": interviewers}
        parsed, errors = parse_slot_input(date, time, minutes, location, label, "1")
        users = _users(session, interviewers)
        if parsed:
            clash = interviewer_errors(session, parsed.starts, parsed.minutes, users, ignore=slot.id)
            if clash:
                errors["interviewers"] = clash
            if slot.applicant_id:
                hit = booking_conflicts(parsed.starts, parsed.minutes,
                                        {slot.applicant_id: applicant_busy(session, slot.applicant_id)}, slot.id)
                if hit:
                    s, b = hit[slot.applicant_id]
                    errors["time"] = f"{slot.applicant.display_name} is booked in another slot then ({describe_clash(s, b)})."
        if errors:
            all_users = list(session.scalars(select(User).order_by(User.name)))
            return templates.TemplateResponse(request, "slot_edit.html", {
                "slot": slot, "values": values, "errors": errors, "users": all_users, "lengths": LENGTHS},
                status_code=422)
        slot.starts_at, slot.minutes = parsed.starts[0], parsed.minutes
        slot.location, slot.label, slot.interviewers = parsed.location, parsed.label, users
        session.commit()
        return redirect("/schedule", msg="Slot saved.")

    @app.post("/schedule/slots/{slot_id}/delete")
    def delete_slot(slot_id: int, next: str = Form(""), me: User = Depends(require_admin),
                    session: Session = Depends(get_session)):
        slot = get_slot(session, slot_id)
        who = f" ({slot.applicant.display_name} is unbooked)" if slot.applicant else ""
        session.delete(slot)
        session.commit()
        return redirect(safe_next(next, "/schedule"), msg=f"Slot deleted{who}.")

    @app.post("/schedule/slots/{slot_id}/book")
    def book_slot(slot_id: int, applicant_id: str = Form(""), next: str = Form(""),
                  me: User = Depends(require_admin), session: Session = Depends(get_session)):
        slot = get_slot(session, slot_id)
        dest = safe_next(next, "/schedule")
        ap = session.get(Applicant, int(applicant_id)) if applicant_id.isdigit() else None
        if ap is None:
            return redirect(dest, error="Pick an applicant to book.")
        err, msg = book(session, slot, ap)
        return redirect(dest, error=err) if err else redirect(dest, msg=msg)

    @app.post("/schedule/slots/{slot_id}/unbook")
    def unbook_slot(slot_id: int, next: str = Form(""), me: User = Depends(require_admin),
                    session: Session = Depends(get_session)):
        slot = get_slot(session, slot_id)
        name = slot.applicant.display_name if slot.applicant else None
        slot.applicant_id = None
        session.commit()
        return redirect(safe_next(next, "/schedule"), msg=f"Unbooked {name}. The slot is open again." if name else "")

    @app.post("/applicants/{applicant_id}/book")
    def book_from_profile(applicant_id: int, slot_id: str = Form(""), me: User = Depends(require_admin),
                          session: Session = Depends(get_session)):
        ap = session.get(Applicant, applicant_id)
        if ap is None:
            raise HTTPException(404, "Applicant not found")
        slot = session.get(InterviewSlot, int(slot_id)) if slot_id.isdigit() else None
        dest = f"/applicants/{ap.id}"
        if slot is None:
            return redirect(dest, error="Pick a slot to book.")
        err, msg = book(session, slot, ap)
        return redirect(dest, error=err) if err else redirect(dest, msg=msg)

    @app.get("/schedule.ics")
    def schedule_ics(request: Request, mine: int = 0, past: int = 0, me: User = Depends(current_user),
                     session: Session = Depends(get_session)):
        now = now_local()
        slots = [s for s in session.scalars(select(InterviewSlot).order_by(InterviewSlot.starts_at))
                 if (past or s.ends_at > now) and (not mine or me.id in s.interviewer_ids)]
        base = str(request.base_url).rstrip("/")
        host = request.url.hostname or "recruitly"
        name = f"{settings.org_name} interviews" + (f" ({me.name})" if mine else "")
        body = build_ics([slot_event(s, base, host) for s in slots], name)
        fname = "my-interviews.ics" if mine else "interviews.ics"
        return Response(body, media_type="text/calendar; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"', "Cache-Control": "no-store"})


# ------------------------------------------------------------------ used by other pages

def applicant_interviews(session: Session, applicant_id: int) -> list[InterviewSlot]:
    return list(session.scalars(select(InterviewSlot).where(InterviewSlot.applicant_id == applicant_id)
                                .order_by(InterviewSlot.starts_at)))


def open_upcoming_slots(session: Session) -> list[InterviewSlot]:
    now = now_local()
    return [s for s in session.scalars(select(InterviewSlot).where(InterviewSlot.applicant_id.is_(None))
                                       .order_by(InterviewSlot.starts_at)) if s.starts_at > now]


def next_interviews(session: Session) -> dict[int, InterviewSlot]:
    """Applicant id → their next upcoming interview, for the board."""
    now = now_local()
    out: dict[int, InterviewSlot] = {}
    for s in session.scalars(select(InterviewSlot).where(InterviewSlot.applicant_id.is_not(None))
                             .order_by(InterviewSlot.starts_at)):
        if s.ends_at > now and s.applicant_id not in out:
            out[s.applicant_id] = s
    return out


def forget_applicant(session: Session, applicant_id: int) -> None:
    """Open up an applicant's slots before they're deleted (SQLite doesn't enforce ON DELETE)."""
    session.execute(update(InterviewSlot).where(InterviewSlot.applicant_id == applicant_id).values(applicant_id=None))


def forget_interviewer(session: Session, user_id: int) -> None:
    session.execute(delete(slot_interviewers).where(slot_interviewers.c.user_id == user_id))
