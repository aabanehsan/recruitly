"""Rubric and scoring rules: parsing the rubric and score-sheet forms, weighted averages, and who can see
whose scores. Everything here is a pure function over plain values so it's easy to test.

The anchoring rule: you can't see anyone else's scores or notes for an applicant in a round until you've
submitted your own sheet for that applicant in that round. Admins run deliberations, so they can always
look, but the page keeps other people's scores folded away until they choose to open them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

SCALE = (1, 2, 3, 4, 5)
SCALE_LABELS = {1: "Poor", 2: "Weak", 3: "Solid", 4: "Strong", 5: "Excellent"}
MAX_CRITERION_NAME = 60
MAX_CRITERION_HELP = 300
MAX_ROUND_NAME = 40
MAX_NOTES = 5000
MIN_WEIGHT, MAX_WEIGHT = 0.5, 10.0
DEFAULT_ROUNDS = ("First round", "Final round")


# ------------------------------------------------------------------ rubric forms

def parse_weight(text: str) -> float | None:
    """`2`, `1.5`, `x2`, `2x` or `150%` (100% = a weight of 1). Rounded to halves.
    Returns None if it isn't a usable weight."""
    t = (text or "").strip().lower().replace("×", "x").removeprefix("x").removesuffix("x").strip()
    pct = t.endswith("%")
    if pct:
        t = t[:-1].strip()
    try:
        w = float(t)
    except ValueError:
        return None
    if pct:
        w /= 100
    if w != w or not MIN_WEIGHT <= w <= MAX_WEIGHT:  # NaN or out of range
        return None
    return round(w * 2) / 2  # keep weights to halves so they read cleanly


@dataclass
class CriterionInput:
    name: str
    description: str | None
    weight: float


def parse_criterion(name: str, description: str, weight: str,
                    taken: Iterable[str] = ()) -> tuple[CriterionInput | None, dict[str, str]]:
    """Validate the add/edit criterion form. `taken` holds the other criteria's names."""
    errors: dict[str, str] = {}
    name = " ".join((name or "").split())
    desc = (description or "").strip() or None
    if not name:
        errors["name"] = "Give the criterion a name, like Communication."
    elif len(name) > MAX_CRITERION_NAME:
        errors["name"] = f"Keep the name under {MAX_CRITERION_NAME} characters."
    elif name.casefold() in {t.casefold() for t in taken}:
        errors["name"] = f"There's already a criterion called {name}."
    if desc and len(desc) > MAX_CRITERION_HELP:
        errors["description"] = f"Keep the description under {MAX_CRITERION_HELP} characters."
    w = parse_weight(weight if str(weight or "").strip() else "1")
    if w is None:
        errors["weight"] = f"Weight must be a number from {MIN_WEIGHT:g} to {MAX_WEIGHT:g}."
    if errors:
        return None, errors
    return CriterionInput(name, desc, w), {}


def parse_round_name(name: str, taken: Iterable[str] = ()) -> tuple[str | None, str | None]:
    name = " ".join((name or "").split())
    if not name:
        return None, "Give the round a name, like First round."
    if len(name) > MAX_ROUND_NAME:
        return None, f"Keep round names under {MAX_ROUND_NAME} characters."
    if name.casefold() in {t.casefold() for t in taken}:
        return None, f"There's already a round called {name}."
    return name, None


def weight_shares(weights: Mapping[int, float]) -> dict[int, int]:
    """Each criterion's share of the total weight, as whole percentages that add up to 100."""
    total = sum(weights.values())
    if total <= 0:
        return {k: 0 for k in weights}
    raw = {k: w * 100 / total for k, w in weights.items()}
    out = {k: int(v) for k, v in raw.items()}
    # hand the leftover points to the largest remainders so the column sums to exactly 100
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[: 100 - sum(out.values())]:
        out[k] += 1
    return out


def move(ids: Sequence[int], item: int, direction: str) -> list[int]:
    """Move one id up or down in an ordered list (for reordering criteria)."""
    order = list(ids)
    if item not in order:
        return order
    i = order.index(item)
    j = i - 1 if direction == "up" else i + 1 if direction == "down" else i
    if 0 <= j < len(order):
        order[i], order[j] = order[j], order[i]
    return order


# ------------------------------------------------------------------ score sheets

def parse_scores(form: Mapping[str, str], criterion_ids: Sequence[int], submit: bool,
                 notes: str = "") -> tuple[dict[int, int], str | None, dict[str, str]]:
    """Read `score_<criterion id>` fields. Drafts may be partial; submitting needs every criterion scored.

    Returns (scores, cleaned notes, errors)."""
    scores: dict[int, int] = {}
    errors: dict[str, str] = {}
    for cid in criterion_ids:
        raw = str(form.get(f"score_{cid}", "") or "").strip()
        if not raw:
            continue
        try:
            val = int(raw)
        except ValueError:
            val = 0
        if val not in SCALE:
            errors[f"score_{cid}"] = "Pick a score from 1 to 5."
        else:
            scores[cid] = val
    clean_notes = (notes or "").replace("\r\n", "\n").strip() or None
    if clean_notes and len(clean_notes) > MAX_NOTES:
        errors["notes"] = f"Notes are limited to {MAX_NOTES:,} characters."
    if submit:
        missing = [cid for cid in criterion_ids if cid not in scores and f"score_{cid}" not in errors]
        for cid in missing:
            errors[f"score_{cid}"] = "Score this before submitting."
        if not criterion_ids and not clean_notes:
            errors["notes"] = "There's no rubric yet, so write some notes before submitting."
    return scores, clean_notes, errors


def weighted_score(scores: Mapping[int, int], weights: Mapping[int, float]) -> float | None:
    """Weighted mean of one sheet's scores over the criteria that still exist. None if nothing is scored."""
    pairs = [(scores[c], w) for c, w in weights.items() if c in scores and w > 0]
    total = sum(w for _, w in pairs)
    if not total:
        return None
    return sum(s * w for s, w in pairs) / total


def mean(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def fmt_score(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def score_band(value: float | None) -> str:
    """A CSS class for colouring an average: low / mid / high."""
    if value is None:
        return "none"
    return "high" if value >= 4 else "mid" if value >= 3 else "low"


# ------------------------------------------------------------------ who sees what

@dataclass(frozen=True)
class SheetView:
    """The bits of a score sheet the visibility rules need."""
    sheet_id: int
    applicant_id: int
    round_id: int
    user_id: int | None  # None once the scorer's account was removed
    submitted: bool
    total: float | None  # weighted score of this sheet


def submitted_rounds(sheets: Iterable[SheetView], viewer_id: int) -> set[tuple[int, int]]:
    """(applicant id, round id) pairs the viewer has submitted a sheet for."""
    return {(s.applicant_id, s.round_id) for s in sheets if s.user_id == viewer_id and s.submitted}


def can_see_others(viewer_id: int, is_admin: bool, applicant_id: int, round_id: int,
                   mine: set[tuple[int, int]]) -> bool:
    return is_admin or (applicant_id, round_id) in mine


def visible_sheets(sheets: Sequence[SheetView], viewer_id: int, is_admin: bool) -> list[SheetView]:
    """Sheets the viewer may read: their own (draft or not), plus others' submitted sheets in rounds
    they've unlocked. Other people's drafts are never shown to anyone."""
    mine = submitted_rounds(sheets, viewer_id)
    return [s for s in sheets if s.user_id == viewer_id
            or (s.submitted and can_see_others(viewer_id, is_admin, s.applicant_id, s.round_id, mine))]


def visible_averages(sheets: Sequence[SheetView], viewer_id: int, is_admin: bool) -> dict[int, float]:
    """Applicant id → average weighted score over the submitted sheets the viewer may see.

    A member who hasn't scored an applicant gets no average for them, so the board can't anchor them
    either (sorting by score only uses these visible averages)."""
    mine = submitted_rounds(sheets, viewer_id)
    by_applicant: dict[int, list[float]] = {}
    for s in sheets:
        if not s.submitted or s.total is None:
            continue
        if s.user_id == viewer_id or can_see_others(viewer_id, is_admin, s.applicant_id, s.round_id, mine):
            by_applicant.setdefault(s.applicant_id, []).append(s.total)
    return {a: sum(v) / len(v) for a, v in by_applicant.items()}


def sort_by_score(ids: Sequence[int], averages: Mapping[int, float]) -> list[int]:
    """Highest average first; applicants without a (visible) average go last, keeping their order."""
    scored = sorted((i for i in ids if i in averages), key=lambda i: -averages[i])
    return scored + [i for i in ids if i not in averages]


def pick_round(rounds: Sequence[tuple[int, str]], interview_labels: Sequence[str],
               requested: int | None = None) -> int | None:
    """Which round the score sheet opens on: the one asked for, else the round named like the applicant's
    latest interview label (e.g. a "Final round" slot), else the first round."""
    ids = [r for r, _ in rounds]
    if requested in ids:
        return requested
    names = {n.casefold(): r for r, n in rounds}
    for label in reversed(list(interview_labels)):
        if label and label.casefold() in names:
            return names[label.casefold()]
    return ids[0] if ids else None


@dataclass
class CriterionStat:
    criterion_id: int
    average: float | None
    count: int


@dataclass
class RoundSummary:
    round_id: int
    submitted: int  # everyone's submitted sheets, shown even while hidden ("3 scored")
    average: float | None  # None when hidden from the viewer
    per_criterion: list[CriterionStat] = field(default_factory=list)


def summarize_round(round_id: int, sheets: Sequence[tuple[SheetView, Mapping[int, int]]],
                    criterion_ids: Sequence[int], unlocked: bool) -> RoundSummary:
    """Round-level numbers for a profile. `sheets` are every submitted sheet in the round with its scores."""
    subs = [(v, sc) for v, sc in sheets if v.round_id == round_id and v.submitted]
    if not unlocked:
        return RoundSummary(round_id, len(subs), None)
    per = []
    for cid in criterion_ids:
        vals = [sc[cid] for _, sc in subs if cid in sc]
        per.append(CriterionStat(cid, mean(vals), len(vals)))
    return RoundSummary(round_id, len(subs), mean(v.total for v, _ in subs), per)
