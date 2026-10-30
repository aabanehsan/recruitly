"""Rubric and score sheet pages: admins define the rubric and rounds, everyone scores applicants."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .db import get_session
from .models import Applicant, Criterion, InterviewSlot, Round, Score, ScoreSheet, User, utcnow
from .services.scoring import (
    DEFAULT_ROUNDS, MAX_NOTES, SCALE, SCALE_LABELS, RoundSummary, SheetView, can_see_others, fmt_score, move,
    parse_criterion, parse_round_name, parse_scores, pick_round, score_band, submitted_rounds, summarize_round,
    visible_averages, visible_sheets, weight_shares, weighted_score,
)
from .web import current_user, redirect, require_admin, templates

templates.env.globals.update(fmt_score=fmt_score, score_band=score_band, SCALE=SCALE, SCALE_LABELS=SCALE_LABELS)


# ------------------------------------------------------------------ queries

def criteria(session: Session) -> list[Criterion]:
    return list(session.scalars(select(Criterion).order_by(Criterion.position, Criterion.id)))


def rounds(session: Session) -> list[Round]:
    return list(session.scalars(select(Round).order_by(Round.position, Round.id)))


def ensure_rounds(session: Session) -> None:
    """A fresh install starts with First round and Final round; admins can rename or add more."""
    if session.scalars(select(Round.id).limit(1)).first() is None:
        session.add_all(Round(name=n, position=i) for i, n in enumerate(DEFAULT_ROUNDS))
        session.commit()


def weights(crits: list[Criterion]) -> dict[int, float]:
    return {c.id: c.weight for c in crits}


def view_of(sheet: ScoreSheet, w: dict[int, float]) -> SheetView:
    return SheetView(sheet.id, sheet.applicant_id, sheet.round_id, sheet.user_id, sheet.submitted,
                     weighted_score(sheet.score_map, w))


def board_averages(session: Session, me: User) -> dict[int, float]:
    """Average score per applicant, as far as `me` is allowed to see (for the board)."""
    w = weights(criteria(session))
    rows = session.execute(
        select(ScoreSheet.id, ScoreSheet.applicant_id, ScoreSheet.round_id, ScoreSheet.user_id,
               ScoreSheet.submitted_at, Score.criterion_id, Score.value)
        .outerjoin(Score, Score.sheet_id == ScoreSheet.id)
    ).all()
    sheets: dict[int, tuple[tuple, dict[int, int]]] = {}
    for sid, ap, rd, uid, sub, cid, val in rows:
        head, sc = sheets.setdefault(sid, ((sid, ap, rd, uid, sub is not None), {}))
        if cid is not None:
            sc[cid] = val
    views = [SheetView(*head, weighted_score(sc, w)) for head, sc in sheets.values()]
    return visible_averages(views, me.id, me.is_admin)


def scored_by(session: Session, user_id: int) -> set[int]:
    """Applicants this user has submitted at least one sheet for."""
    return set(session.scalars(select(ScoreSheet.applicant_id).where(
        ScoreSheet.user_id == user_id, ScoreSheet.submitted_at.is_not(None))))


def forget_applicant_scores(session: Session, applicant_id: int) -> None:
    for sheet in session.scalars(select(ScoreSheet).where(ScoreSheet.applicant_id == applicant_id)):
        session.delete(sheet)


def forget_scorer(session: Session, user_id: int) -> None:
    """Keep a removed member's sheets (they still count), shown as "Former member"."""
    session.execute(update(ScoreSheet).where(ScoreSheet.user_id == user_id).values(user_id=None))


@dataclass
class RoundBlock:
    round: Round
    summary: RoundSummary
    mine: ScoreSheet | None
    mine_total: float | None
    others: list[tuple[ScoreSheet, float | None]]
    unlocked: bool  # the viewer submitted here (or is allowed to look)
    admin_peek: bool  # an admin who hasn't scored this round yet: others are folded away


def profile_scores(session: Session, ap: Applicant, me: User) -> dict:
    """Everything the profile's Scores panel needs, already filtered by the anchoring rule."""
    crits = criteria(session)
    w = weights(crits)
    rds = rounds(session)
    sheets = list(session.scalars(select(ScoreSheet).where(ScoreSheet.applicant_id == ap.id)
                                  .order_by(ScoreSheet.submitted_at.is_(None), ScoreSheet.submitted_at)))
    views = {s.id: view_of(s, w) for s in sheets}
    allowed = {v.sheet_id for v in visible_sheets(list(views.values()), me.id, me.is_admin)}
    mine_rounds = submitted_rounds(views.values(), me.id)
    blocks = []
    for rd in rds:
        in_round = [s for s in sheets if s.round_id == rd.id]
        mine = next((s for s in in_round if s.user_id == me.id), None)
        unlocked = can_see_others(me.id, me.is_admin, ap.id, rd.id, mine_rounds)
        summary = summarize_round(rd.id, [(views[s.id], s.score_map) for s in in_round], [c.id for c in crits],
                                  unlocked)
        others = [(s, views[s.id].total) for s in in_round
                  if s.id in allowed and s.user_id != me.id and s.submitted]
        blocks.append(RoundBlock(rd, summary, mine, views[mine.id].total if mine else None, others, unlocked,
                                 me.is_admin and (ap.id, rd.id) not in mine_rounds))
    overall = visible_averages(list(views.values()), me.id, me.is_admin).get(ap.id)
    counted = sum(1 for s in sheets if s.id in allowed and s.submitted and views[s.id].total is not None)
    return {"crits": crits, "shares": weight_shares(w), "blocks": blocks, "overall": overall,
            "overall_count": counted, "has_rubric": bool(crits)}


# ------------------------------------------------------------------ page contexts

def rubric_ctx(session: Session, errors: dict | None = None, values: dict | None = None,
               form: str = "") -> dict:
    crits = criteria(session)
    rds = rounds(session)
    sheet_counts = dict(session.execute(
        select(ScoreSheet.round_id, func.count()).group_by(ScoreSheet.round_id)).all())
    scored = dict(session.execute(select(Score.criterion_id, func.count()).group_by(Score.criterion_id)).all())
    return {"crits": crits, "shares": weight_shares(weights(crits)), "rounds": rds, "sheet_counts": sheet_counts,
            "scored": scored, "errors": errors or {}, "values": values or {}, "form": form}


def get_or_404(session: Session, model, key: int, what: str):
    obj = session.get(model, key)
    if obj is None:
        raise HTTPException(404, f"{what} not found")
    return obj


def renumber(session: Session, items) -> None:
    for i, item in enumerate(items):
        item.position = i


def register_scoring_routes(app: FastAPI) -> None:
    # ------------------------------------------------------------ rubric

    @app.get("/rubric", response_class=HTMLResponse)
    def rubric_page(request: Request, msg: str = "", error: str = "", me: User = Depends(current_user),
                    session: Session = Depends(get_session)):
        return templates.TemplateResponse(request, "rubric.html", rubric_ctx(session) | {"msg": msg, "error": error})

    def rubric_error(request: Request, session: Session, errors: dict, values: dict, form: str):
        ctx = rubric_ctx(session, errors, values, form)
        return templates.TemplateResponse(request, "rubric.html", ctx | {"msg": "", "error": ""}, status_code=422)

    @app.post("/rubric/criteria", response_class=HTMLResponse)
    def add_criterion(request: Request, name: str = Form(""), description: str = Form(""), weight: str = Form("1"),
                      me: User = Depends(require_admin), session: Session = Depends(get_session)):
        crits = criteria(session)
        parsed, errors = parse_criterion(name, description, weight, [c.name for c in crits])
        if errors:
            return rubric_error(request, session, errors, {"name": name, "description": description,
                                                           "weight": weight}, "new")
        session.add(Criterion(name=parsed.name, description=parsed.description, weight=parsed.weight,
                              position=len(crits)))
        session.commit()
        return redirect("/rubric", msg=f"Added {parsed.name}.")

    @app.post("/rubric/criteria/{criterion_id}/edit", response_class=HTMLResponse)
    def edit_criterion(request: Request, criterion_id: int, name: str = Form(""), description: str = Form(""),
                       weight: str = Form("1"), me: User = Depends(require_admin),
                       session: Session = Depends(get_session)):
        crit = get_or_404(session, Criterion, criterion_id, "Criterion")
        others = [c.name for c in criteria(session) if c.id != crit.id]
        parsed, errors = parse_criterion(name, description, weight, others)
        if errors:
            return rubric_error(request, session, errors, {"name": name, "description": description,
                                                           "weight": weight}, f"c{crit.id}")
        crit.name, crit.description, crit.weight = parsed.name, parsed.description, parsed.weight
        session.commit()
        return redirect("/rubric", msg=f"Saved {crit.name}.")

    @app.post("/rubric/criteria/{criterion_id}/move")
    def move_criterion(criterion_id: int, direction: str = Form(""), me: User = Depends(require_admin),
                       session: Session = Depends(get_session)):
        crits = criteria(session)
        get_or_404(session, Criterion, criterion_id, "Criterion")
        order = move([c.id for c in crits], criterion_id, direction)
        by_id = {c.id: c for c in crits}
        renumber(session, [by_id[i] for i in order])
        session.commit()
        return redirect("/rubric")

    @app.post("/rubric/criteria/{criterion_id}/delete")
    def delete_criterion(criterion_id: int, me: User = Depends(require_admin),
                         session: Session = Depends(get_session)):
        crit = get_or_404(session, Criterion, criterion_id, "Criterion")
        name = crit.name
        session.query(Score).filter(Score.criterion_id == crit.id).delete()
        session.delete(crit)
        session.flush()
        renumber(session, criteria(session))
        session.commit()
        return redirect("/rubric", msg=f"Removed {name}. Weighted averages now use the remaining criteria.")

    @app.post("/rubric/rounds", response_class=HTMLResponse)
    def add_round(request: Request, name: str = Form(""), me: User = Depends(require_admin),
                  session: Session = Depends(get_session)):
        rds = rounds(session)
        clean, err = parse_round_name(name, [r.name for r in rds])
        if err:
            return rubric_error(request, session, {"round": err}, {"round": name}, "round")
        session.add(Round(name=clean, position=len(rds)))
        session.commit()
        return redirect("/rubric", msg=f"Added {clean}.")

    @app.post("/rubric/rounds/{round_id}/edit", response_class=HTMLResponse)
    def rename_round(request: Request, round_id: int, name: str = Form(""), me: User = Depends(require_admin),
                     session: Session = Depends(get_session)):
        rd = get_or_404(session, Round, round_id, "Round")
        clean, err = parse_round_name(name, [r.name for r in rounds(session) if r.id != rd.id])
        if err:
            return rubric_error(request, session, {"round": err}, {"round": name}, f"r{rd.id}")
        rd.name = clean
        session.commit()
        return redirect("/rubric", msg=f"Renamed to {clean}.")

    @app.post("/rubric/rounds/{round_id}/delete")
    def delete_round(round_id: int, me: User = Depends(require_admin), session: Session = Depends(get_session)):
        rd = get_or_404(session, Round, round_id, "Round")
        rds = rounds(session)
        if len(rds) <= 1:
            return redirect("/rubric", error="Keep at least one round.")
        if session.scalars(select(ScoreSheet.id).where(ScoreSheet.round_id == rd.id).limit(1)).first():
            return redirect("/rubric", error=f"{rd.name} already has score sheets, so it can't be deleted. "
                                             "Rename it instead.")
        session.delete(rd)
        session.flush()
        renumber(session, rounds(session))
        session.commit()
        return redirect("/rubric", msg=f"Deleted {rd.name}.")

    # ------------------------------------------------------------ score sheets

    def sheet_ctx(session: Session, ap: Applicant, me: User, rd: Round, sheet: ScoreSheet | None,
                  values: dict | None = None, errors: dict | None = None) -> dict:
        crits = criteria(session)
        rds = rounds(session)
        mine = {s.round_id: s for s in session.scalars(select(ScoreSheet).where(
            ScoreSheet.applicant_id == ap.id, ScoreSheet.user_id == me.id))}
        if values is None:
            values = {f"score_{k}": str(v) for k, v in (sheet.score_map if sheet else {}).items()}
            values["notes"] = sheet.notes or "" if sheet else ""
        return {"ap": ap, "round": rd, "rounds": rds, "crits": crits, "shares": weight_shares(weights(crits)),
                "sheet": sheet, "mine": mine, "values": values, "errors": errors or {}, "max_notes": MAX_NOTES,
                "total": weighted_score(sheet.score_map, weights(crits)) if sheet else None}

    def find_round(session: Session, ap: Applicant, requested: int | None) -> Round:
        rds = rounds(session)
        if not rds:
            ensure_rounds(session)
            rds = rounds(session)
        labels = list(session.scalars(select(InterviewSlot.label).where(InterviewSlot.applicant_id == ap.id)
                                      .order_by(InterviewSlot.starts_at)))
        rid = pick_round([(r.id, r.name) for r in rds], [lb or "" for lb in labels], requested)
        return next(r for r in rds if r.id == rid)

    def my_sheet(session: Session, ap: Applicant, me: User, rd: Round) -> ScoreSheet | None:
        return session.scalars(select(ScoreSheet).where(ScoreSheet.applicant_id == ap.id,
                                                        ScoreSheet.user_id == me.id,
                                                        ScoreSheet.round_id == rd.id)).first()

    @app.get("/applicants/{applicant_id}/score", response_class=HTMLResponse)
    def score_page(request: Request, applicant_id: int, round: int | None = None, msg: str = "",
                   me: User = Depends(current_user), session: Session = Depends(get_session)):
        ap = get_or_404(session, Applicant, applicant_id, "Applicant")
        rd = find_round(session, ap, round)
        ctx = sheet_ctx(session, ap, me, rd, my_sheet(session, ap, me, rd))
        return templates.TemplateResponse(request, "score.html", ctx | {"msg": msg})

    @app.post("/applicants/{applicant_id}/score", response_class=HTMLResponse)
    async def save_score(request: Request, applicant_id: int, me: User = Depends(current_user),
                         session: Session = Depends(get_session)):
        ap = get_or_404(session, Applicant, applicant_id, "Applicant")
        form = await request.form()
        rid = str(form.get("round_id", ""))
        rd = session.get(Round, int(rid)) if rid.isdigit() else None
        if rd is None:
            raise HTTPException(400, "Pick a round to score.")
        submit = form.get("action") == "submit"
        crits = criteria(session)
        fields = {k: str(v) for k, v in form.items() if k.startswith("score_")}
        scores, notes, errors = parse_scores(fields, [c.id for c in crits], submit, str(form.get("notes", "")))
        sheet = my_sheet(session, ap, me, rd)
        if not submit and sheet is not None and sheet.submitted and len(scores) < len(crits):
            errors["action"] = "This sheet is already submitted, so every criterion needs a score."
        if errors:
            values = fields | {"notes": str(form.get("notes", ""))}
            ctx = sheet_ctx(session, ap, me, rd, sheet, values, errors)
            return templates.TemplateResponse(request, "score.html", ctx | {"msg": ""}, status_code=422)
        if sheet is None:
            sheet = ScoreSheet(applicant_id=ap.id, user_id=me.id, round_id=rd.id)
            session.add(sheet)
        sheet.notes = notes
        existing = {sc.criterion_id: sc for sc in sheet.scores}
        for cid, sc in existing.items():
            if cid not in scores:
                sheet.scores.remove(sc)
        for cid, val in scores.items():
            if cid in existing:
                existing[cid].value = val
            else:
                sheet.scores.append(Score(criterion_id=cid, value=val))
        first_submit = submit and not sheet.submitted
        if submit and not sheet.submitted:
            sheet.submitted_at = utcnow()
        session.commit()
        if not submit and not sheet.submitted:
            return redirect(f"/applicants/{ap.id}/score", round=str(rd.id),
                            msg="Draft saved. Only you can see it until you submit.")
        total = fmt_score(weighted_score(scores, weights(crits)))
        if first_submit:
            msg = f"Scores submitted ({total}). You can now see everyone's {rd.name} scores."
        else:
            msg = f"Scores updated ({total})."
        return redirect(f"/applicants/{ap.id}", msg=msg)

    @app.post("/applicants/{applicant_id}/score/delete")
    def delete_score(applicant_id: int, round_id: int = Form(...), me: User = Depends(current_user),
                     session: Session = Depends(get_session)):
        ap = get_or_404(session, Applicant, applicant_id, "Applicant")
        rd = get_or_404(session, Round, round_id, "Round")
        sheet = my_sheet(session, ap, me, rd)
        if sheet is not None:
            session.delete(sheet)
            session.commit()
        return redirect(f"/applicants/{ap.id}", msg=f"Your {rd.name} sheet was deleted." if sheet else "")

