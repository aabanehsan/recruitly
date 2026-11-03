"""Decisions dashboard: applicants ranked by score, deliberation sessions with votes, results, bulk status
changes and the funnel charts."""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_session
from .models import Applicant, Deliberation, InterviewSlot, Status, User, Vote, utcnow
from .schedule import now_local
from .scoring import sheet_views
from .services.auth import safe_next
from .services.decisions import (
    BULK_FIRST, CLOSED_STATUSES, ago, VERDICT_LABELS, VOTE_CHOICES, VOTE_LABELS, Flag, ScoreStats, Tally, can_see_tally,
    can_vote, flags_for, funnel, parse_bulk, parse_session_name, parse_vote, rank, rank_results, score_stats,
    status_mix, tally_votes,
)
from .services.scoring import visible_averages
from .web import current_user, redirect, require_admin, templates

templates.env.globals.update(VOTE_CHOICES=VOTE_CHOICES, VOTE_LABELS=VOTE_LABELS, VERDICT_LABELS=VERDICT_LABELS,
                             CLOSED_STATUSES=CLOSED_STATUSES)
templates.env.filters["ago"] = lambda d: ago(_aware(d), utcnow())
SORTS = (("score", "Score"), ("votes", "Votes"), ("name", "Name"))


def _aware(d):
    """SQLite hands back naive datetimes even for timezone=True columns; they're stored in UTC."""
    from datetime import timezone

    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


# ------------------------------------------------------------------ queries

def open_deliberation(session: Session) -> Deliberation | None:
    return session.scalars(select(Deliberation).where(Deliberation.closed_at.is_(None))
                           .order_by(Deliberation.opened_at.desc())).first()


def get_deliberation(session: Session, deliberation_id: int) -> Deliberation:
    d = session.get(Deliberation, deliberation_id)
    if d is None:
        raise HTTPException(404, "Deliberation not found")
    return d


def interviewed_ids(session: Session) -> set[int]:
    """Applicants with a booked slot that has already started."""
    now = now_local()
    return set(session.scalars(select(InterviewSlot.applicant_id).where(
        InterviewSlot.applicant_id.is_not(None), InterviewSlot.starts_at <= now)))


def votes_in(session: Session, d: Deliberation) -> list[Vote]:
    return list(session.scalars(select(Vote).where(Vote.deliberation_id == d.id)))


def voter_count(votes: list[Vote]) -> int:
    return len({v.user_id if v.user_id is not None else f"x{v.id}" for v in votes})


def past_deliberations(session: Session) -> list[tuple[Deliberation, int, int]]:
    """Closed sessions, newest first, with (votes, voters)."""
    out = []
    for d in session.scalars(select(Deliberation).where(Deliberation.closed_at.is_not(None))
                             .order_by(Deliberation.closed_at.desc())):
        vs = votes_in(session, d)
        out.append((d, len(vs), voter_count(vs)))
    return out


def forget_applicant_votes(session: Session, applicant_id: int) -> None:
    session.execute(delete(Vote).where(Vote.applicant_id == applicant_id))


def forget_voter(session: Session, user_id: int) -> None:
    """Keep a removed member's votes (they still count); they were never shown per person anyway."""
    session.execute(update(Vote).where(Vote.user_id == user_id).values(user_id=None))


# ------------------------------------------------------------------ page contexts

@dataclass
class Row:
    ap: Applicant
    rank: int | None
    average: float | None
    stats: ScoreStats
    flags: list[Flag] = field(default_factory=list)
    my_vote: str | None = None
    tally: Tally | None = None


def decisions_ctx(session: Session, me: User, status: str, sort: str) -> dict:
    aps = list(session.scalars(select(Applicant).order_by(Applicant.last_name, Applicant.first_name)))
    views = sheet_views(session)
    avgs = visible_averages(views, me.id, me.is_admin)
    stats = score_stats(views, me.id, me.is_admin)
    done = interviewed_ids(session)
    live = open_deliberation(session)
    votes = votes_in(session, live) if live else []
    mine = {v.applicant_id: v.choice for v in votes if v.user_id == me.id}
    show_tally = live is not None and can_see_tally(me.is_admin, True)
    tallies = tally_votes((v.applicant_id, v.choice) for v in votes) if show_tally else {}

    by_id = {a.id: a for a in aps}
    ranks = dict((i, r) for r, i in rank([a.id for a in aps], avgs))
    # unscored applicants who are already out (cut / declined) sink to the bottom
    by_score = [i for _, i in rank([a.id for a in aps], avgs)]
    by_score = ([i for i in by_score if i in avgs or by_id[i].status not in CLOSED_STATUSES]
                + [i for i in by_score if i not in avgs and by_id[i].status in CLOSED_STATUSES])
    if sort not in dict(SORTS) or (sort == "votes" and not show_tally):
        sort = "score"
    if sort == "name":
        order = [a.id for a in aps]
    elif sort == "votes":
        voted = rank_results(tallies)
        order = voted + [i for i in by_score if i not in tallies]
    else:
        order = by_score
    rows = [Row(by_id[i], ranks[i], avgs.get(i), stats.get(i, ScoreStats()),
                flags_for(stats.get(i), by_id[i].status, i in done), mine.get(i), tallies.get(i))
            for i in order if not status or by_id[i].status == status]

    counts = dict(session.execute(select(Applicant.status, func.count()).group_by(Applicant.status)).all())
    statuses = {a.id: a.status for a in aps}
    return {
        "rows": rows, "counts": counts, "total": len(aps), "f": {"status": status, "sort": sort}, "sorts": SORTS,
        "live": live, "live_votes": len(votes), "live_voters": voter_count(votes), "my_votes": len(mine),
        "show_tally": show_tally, "past": past_deliberations(session),
        "funnel": funnel(statuses, done), "mix": status_mix(statuses.values(), [s.value for s in Status]),
        "bulk_statuses": bulk_statuses(), "scored_any": bool(avgs),
    }


def bulk_statuses() -> list[Status]:
    first = [Status(s) for s in BULK_FIRST]
    return first + [s for s in Status if s not in first]


def results_ctx(session: Session, me: User, d: Deliberation) -> dict:
    votes = votes_in(session, d)
    visible = can_see_tally(me.is_admin, d.is_open)
    mine = {v.applicant_id: v.choice for v in votes if v.user_id == me.id}
    tallies = tally_votes((v.applicant_id, v.choice) for v in votes)
    ids = rank_results(tallies) if visible else sorted(mine)
    aps = {a.id: a for a in session.scalars(select(Applicant).where(Applicant.id.in_(ids)))} if ids else {}
    if not visible:
        ids = sorted(aps, key=lambda i: (aps[i].last_name, aps[i].first_name))
    avgs = visible_averages(sheet_views(session), me.id, me.is_admin)
    rows = [(aps[i], tallies[i] if visible else None, mine.get(i), avgs.get(i)) for i in ids if i in aps]
    summary = {k: sum(1 for t in tallies.values() if t.verdict == k) for k in VERDICT_LABELS} if visible else {}
    return {"d": d, "rows": rows, "visible": visible, "votes": len(votes), "voters": voter_count(votes),
            "summary": summary, "bulk_statuses": bulk_statuses()}


def profile_votes(session: Session, ap: Applicant, me: User) -> dict:
    """The profile's Votes panel: your vote in the open session, and results from closed ones."""
    live = open_deliberation(session)
    out: dict = {"live": live, "mine": None, "tally": None, "past": []}
    if live:
        vs = [v for v in votes_in(session, live) if v.applicant_id == ap.id]
        out["mine"] = next((v.choice for v in vs if v.user_id == me.id), None)
        if can_see_tally(me.is_admin, True):
            out["tally"] = tally_votes((v.applicant_id, v.choice) for v in vs).get(ap.id, Tally())
        out["votable"] = can_vote(True, ap.status) is None
    rows = session.execute(
        select(Deliberation, Vote.choice).join(Vote, Vote.deliberation_id == Deliberation.id)
        .where(Vote.applicant_id == ap.id, Deliberation.closed_at.is_not(None))
        .order_by(Deliberation.closed_at.desc())).all()
    past: dict[int, tuple[Deliberation, Tally]] = {}
    for d, choice in rows:
        _, t = past.setdefault(d.id, (d, Tally()))
        if choice in VOTE_CHOICES:
            setattr(t, choice, getattr(t, choice) + 1)
    out["past"] = list(past.values())
    return out


# ------------------------------------------------------------------ routes

def register_decision_routes(app: FastAPI) -> None:
    @app.get("/decisions", response_class=HTMLResponse)
    def decisions(request: Request, status: str = "", sort: str = "score", msg: str = "", error: str = "",
                  me: User = Depends(current_user), session: Session = Depends(get_session)):
        if status and status not in {s.value for s in Status}:
            status = ""
        ctx = decisions_ctx(session, me, status, sort)
        return templates.TemplateResponse(request, "decisions.html", ctx | {"msg": msg, "error": error})

    @app.post("/decisions/sessions")
    async def open_session(request: Request, me: User = Depends(require_admin),
                           session: Session = Depends(get_session)):
        form = await request.form()
        if open_deliberation(session):
            return redirect("/decisions", error="A deliberation is already open. Close it before starting another.")
        today = now_local()
        name, err = parse_session_name(str(form.get("name", "")), f"Deliberation {today:%b} {today.day}")
        if err:
            return redirect("/decisions", error=err)
        session.add(Deliberation(name=name, opened_by_id=me.id))
        session.commit()
        return redirect("/decisions", msg=f"{name} is open. Everyone can vote now; results unlock when you close it.")

    @app.post("/decisions/sessions/{deliberation_id}/close")
    def close_session(deliberation_id: int, me: User = Depends(require_admin),
                      session: Session = Depends(get_session)):
        d = get_deliberation(session, deliberation_id)
        if d.is_open:
            d.closed_at = utcnow()
            session.commit()
        return redirect(f"/decisions/sessions/{d.id}", msg=f"{d.name} is closed. Results are visible to everyone.")

    @app.post("/decisions/sessions/{deliberation_id}/delete")
    def delete_session(deliberation_id: int, me: User = Depends(require_admin),
                       session: Session = Depends(get_session)):
        d = get_deliberation(session, deliberation_id)
        name = d.name
        session.execute(delete(Vote).where(Vote.deliberation_id == d.id))
        session.delete(d)
        session.commit()
        return redirect("/decisions", msg=f"Deleted {name} and its votes.")

    @app.get("/decisions/sessions/{deliberation_id}", response_class=HTMLResponse)
    def results(request: Request, deliberation_id: int, msg: str = "", error: str = "",
                me: User = Depends(current_user), session: Session = Depends(get_session)):
        d = get_deliberation(session, deliberation_id)
        return templates.TemplateResponse(request, "results.html",
                                          results_ctx(session, me, d) | {"msg": msg, "error": error})

    @app.post("/decisions/sessions/{deliberation_id}/vote")
    async def vote(request: Request, deliberation_id: int, me: User = Depends(current_user),
                   session: Session = Depends(get_session)):
        form = await request.form()
        d = get_deliberation(session, deliberation_id)
        raw = str(form.get("applicant_id", ""))
        ap = session.get(Applicant, int(raw)) if raw.isdigit() else None
        if ap is None:
            raise HTTPException(404, "Applicant not found")
        back = safe_next(str(form.get("next", "")), "/decisions")
        err = can_vote(d.is_open, ap.status)
        existing = session.scalars(select(Vote).where(Vote.deliberation_id == d.id, Vote.applicant_id == ap.id,
                                                      Vote.user_id == me.id)).first()
        choice, perr = parse_vote(str(form.get("choice", "")), existing.choice if existing else None)
        err = err or perr
        if err:
            return redirect(_with_param(back, "error", err))
        if choice is None:
            if existing:
                session.delete(existing)
        elif existing:
            existing.choice = choice
        else:
            session.add(Vote(deliberation_id=d.id, applicant_id=ap.id, user_id=me.id, choice=choice))
        try:
            session.commit()
        except IntegrityError:  # double click: the other request already saved this vote
            session.rollback()
        return redirect(_with_param(back))

    @app.post("/decisions/bulk-status")
    async def bulk_status(request: Request, me: User = Depends(require_admin),
                          session: Session = Depends(get_session)):
        form = await request.form()
        back = safe_next(str(form.get("next", "")), "/decisions")
        known = session.scalars(select(Applicant.id)).all()
        ids, status, err = parse_bulk(form.getlist("applicant_id"), str(form.get("status", "")),
                                      [s.value for s in Status], known)
        if err:
            return redirect(_with_param(back, "error", err))
        for ap in session.scalars(select(Applicant).where(Applicant.id.in_(ids))):
            ap.status = status
        session.commit()
        n = len(ids)
        return redirect(_with_param(back, "msg", f"Set {n} applicant{'' if n == 1 else 's'} to {Status(status).label}."))


def _with_param(url: str, key: str | None = None, value: str = "") -> str:
    """Add ?key=value to an in-app URL, before any #fragment, dropping an earlier msg/error."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("msg", "error")] + ([(key, value)] if key else [])
    return urlunsplit(("", "", parts.path, urlencode(q), parts.fragment))
