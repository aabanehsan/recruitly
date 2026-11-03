"""Decision rules: ranking applicants by score, flags worth a second look, deliberation votes and the
recruitment funnel. Everything here is a pure function over plain values so it's easy to test.

Voting follows the same idea as the scoring anchoring rule: while a deliberation is open, members only see
their own votes (and how many people have voted), so nobody votes with the room. Admins run the session and
see the live tally. Once the admin closes the session, everyone sees the counts. Votes are never shown per
person, only as counts.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .scoring import SheetView, can_see_others, submitted_rounds, weight_shares

VOTE_CHOICES = ("yes", "no", "abstain")
VOTE_LABELS = {"yes": "Yes", "no": "No", "abstain": "Abstain"}
# applicants with these statuses are out of the running, so they can't be voted on
CLOSED_STATUSES = frozenset({"cut", "declined"})
# statuses the bulk action offers first: the two decisions people make in bulk
BULK_FIRST = ("offered", "cut")
MAX_SESSION_NAME = 60
SPLIT_GAP = 1.5  # sheets this far apart (on the 1-5 scale) get a "Split" flag


# ------------------------------------------------------------------ ranking and flags

@dataclass
class ScoreStats:
    scorers: int = 0  # people with a submitted sheet (any round); shown even while scores are hidden
    drafts: int = 0  # unsubmitted sheets, by anyone
    spread: float | None = None  # max - min sheet score, over the sheets the viewer may see


def score_stats(sheets: Sequence[SheetView], viewer_id: int, is_admin: bool) -> dict[int, ScoreStats]:
    """Per-applicant counts for the decisions table. The spread only uses sheets the viewer is allowed to
    see, so a "Split" flag never leaks scores a member hasn't unlocked."""
    mine = submitted_rounds(sheets, viewer_id)
    out: dict[int, ScoreStats] = {}
    scorers: dict[int, set] = {}
    seen: dict[int, list[float]] = {}
    for s in sheets:
        st = out.setdefault(s.applicant_id, ScoreStats())
        if not s.submitted:
            st.drafts += 1
            continue
        # a removed member's sheets still count; give each one its own key so they're not merged
        scorers.setdefault(s.applicant_id, set()).add(s.user_id if s.user_id is not None else f"x{s.sheet_id}")
        visible = s.user_id == viewer_id or can_see_others(viewer_id, is_admin, s.applicant_id, s.round_id, mine)
        if visible and s.total is not None:
            seen.setdefault(s.applicant_id, []).append(s.total)
    for ap, st in out.items():
        st.scorers = len(scorers.get(ap, ()))
        vals = seen.get(ap, [])
        st.spread = max(vals) - min(vals) if len(vals) >= 2 else None
    return out


@dataclass(frozen=True)
class Flag:
    key: str
    label: str
    tone: str  # css class: muted / warn / info / err
    hint: str


def flags_for(stats: ScoreStats | None, status: str, interviewed: bool) -> list[Flag]:
    """Things worth a second look before deciding on someone."""
    st = stats or ScoreStats()
    out: list[Flag] = []
    if st.scorers == 0:
        if interviewed:
            out.append(Flag("unscored", "Not scored", "err", "Interviewed, but nobody has submitted scores yet"))
        elif status not in CLOSED_STATUSES:
            out.append(Flag("unscored", "No scores", "muted", "Nobody has scored this applicant yet"))
    elif st.scorers == 1:
        out.append(Flag("one", "1 scorer", "warn", "Only one person has scored this applicant"))
    if st.spread is not None and st.spread >= SPLIT_GAP:
        out.append(Flag("split", f"Split ±{st.spread:.1f}", "warn",
                        "Scorers disagree: their sheets are far apart"))
    if st.drafts:
        out.append(Flag("draft", "Draft pending" if st.drafts == 1 else f"{st.drafts} drafts", "info",
                        "Someone started a score sheet but hasn't submitted it"))
    return out


def rank(ids: Sequence[int], averages: Mapping[int, float]) -> list[tuple[int | None, int]]:
    """(rank, id) with the highest average first. Ties share a rank (1, 2, 2, 4); unscored applicants keep
    their order at the end with no rank."""
    scored = sorted((i for i in ids if i in averages), key=lambda i: -averages[i])
    out: list[tuple[int | None, int]] = []
    prev, prev_rank = None, 0
    for pos, i in enumerate(scored, start=1):
        # compare rounded so 4.25 and 4.2500001 (float noise) share a rank
        key = round(averages[i], 6)
        r = prev_rank if key == prev else pos
        out.append((r, i))
        prev, prev_rank = key, r
    return out + [(None, i) for i in ids if i not in averages]


# ------------------------------------------------------------------ votes

def parse_vote(choice: str, current: str | None = None) -> tuple[str | None, str | None]:
    """Read a vote button. Returns (new choice or None to clear the vote, error).

    Clicking the vote you already have clears it, so a vote can be taken back."""
    c = (choice or "").strip().lower()
    if c == "clear":
        return None, None
    if c not in VOTE_CHOICES:
        return None, "Pick yes, no or abstain."
    if c == current:
        return None, None
    return c, None


def can_vote(session_open: bool, status: str) -> str | None:
    """None if voting is allowed, else the reason it isn't."""
    if not session_open:
        return "This deliberation is closed, so votes can't change anymore."
    if status in CLOSED_STATUSES:
        return "This applicant is already out of the running."
    return None


def can_see_tally(is_admin: bool, session_open: bool) -> bool:
    return is_admin or not session_open


@dataclass
class Tally:
    yes: int = 0
    no: int = 0
    abstain: int = 0

    @property
    def total(self) -> int:
        return self.yes + self.no + self.abstain

    @property
    def yes_share(self) -> float | None:
        """Share of yes among people who took a side (abstentions don't count either way)."""
        decided = self.yes + self.no
        return self.yes / decided if decided else None

    @property
    def verdict(self) -> str:
        """yes (more yes than no), no, tied, or none (no yes/no votes)."""
        if not self.yes + self.no:
            return "none"
        return "yes" if self.yes > self.no else "no" if self.no > self.yes else "tied"

    def bar(self) -> list[tuple[str, float, float]]:
        """(choice, x, width) segments of a 100-wide stacked bar, for inline SVG."""
        if not self.total:
            return []
        out, x = [], 0.0
        for c in VOTE_CHOICES:
            w = getattr(self, c) * 100 / self.total
            if w:
                out.append((c, round(x, 2), round(w, 2)))
                x += w
        return out


VERDICT_LABELS = {"yes": "Majority yes", "no": "Majority no", "tied": "Tied", "none": "No yes/no votes"}


def tally_votes(votes: Iterable[tuple[int, str]]) -> dict[int, Tally]:
    """(applicant id, choice) pairs → a Tally per applicant. Unknown choices are ignored."""
    out: dict[int, Tally] = {}
    for ap, choice in votes:
        if choice in VOTE_CHOICES:
            t = out.setdefault(ap, Tally())
            setattr(t, choice, getattr(t, choice) + 1)
    return out


def rank_results(tallies: Mapping[int, Tally]) -> list[int]:
    """Applicants by net support (yes - no), then most yes votes, then fewest no."""
    return sorted(tallies, key=lambda a: (-(tallies[a].yes - tallies[a].no), -tallies[a].yes, tallies[a].no, a))


def parse_session_name(name: str, default: str) -> tuple[str | None, str | None]:
    clean = " ".join((name or "").split()) or default
    if len(clean) > MAX_SESSION_NAME:
        return None, f"Keep the name under {MAX_SESSION_NAME} characters."
    return clean, None


# ------------------------------------------------------------------ bulk status

def parse_bulk(ids: Iterable[str], status: str, valid_statuses: Iterable[str],
               known_ids: Iterable[int]) -> tuple[list[int], str | None, str | None]:
    """Validate the bulk status form. Returns (applicant ids, status, error)."""
    known = set(known_ids)
    picked: list[int] = []
    for raw in ids:
        raw = str(raw).strip()
        if raw.isdigit() and int(raw) in known and int(raw) not in picked:
            picked.append(int(raw))
    if status not in set(valid_statuses):
        return picked, None, "Pick a status to set."
    if not picked:
        return [], status, "Select at least one applicant first."
    return picked, status, None


# ------------------------------------------------------------------ funnel and charts

FUNNEL_STAGES = (("applied", "Applied"), ("interviewed", "Interviewed"), ("offered", "Offered"),
                 ("accepted", "Accepted"))
# how far each status proves someone got (an interview is also proven by a past booked slot)
_STATUS_STAGE = {"applied": 0, "interviewing": 0, "cut": 0, "final_round": 1, "offered": 2, "declined": 2,
                 "accepted": 3}


@dataclass
class Stage:
    key: str
    label: str
    count: int
    share: int  # % of everyone who applied
    conversion: int | None  # % of the previous stage that made it here
    x: float = 0.0  # centred bar for the inline SVG funnel, in 0-100 units
    w: float = 0.0


def stage_reached(status: str, interviewed: bool) -> int:
    return max(_STATUS_STAGE.get(status, 0), 1 if interviewed else 0)


def funnel(statuses: Mapping[int, str], interviewed: Iterable[int]) -> list[Stage]:
    """Applied → interviewed → offered → accepted. Each stage counts everyone who got at least that far:
    someone offered was also interviewed, and someone cut after an interview still counts as interviewed."""
    done = set(interviewed)
    reached = [stage_reached(st, ap in done) for ap, st in statuses.items()]
    total = len(reached)
    stages: list[Stage] = []
    for i, (key, label) in enumerate(FUNNEL_STAGES):
        n = sum(1 for r in reached if r >= i)
        prev = stages[-1].count if stages else None
        conv = None if prev is None else (round(n * 100 / prev) if prev else 0)
        share = round(n * 100 / total) if total else 0
        w = max(n * 100 / total, 1.5) if total and n else 0.0
        stages.append(Stage(key, label, n, share, conv, round((100 - w) / 2, 2), round(w, 2)))
    return stages


@dataclass
class Segment:
    status: str
    count: int
    pct: int
    x: float = 0.0
    w: float = 0.0


def status_mix(statuses: Iterable[str], order: Sequence[str]) -> list[Segment]:
    """Count per status (in `order`, skipping empty ones) with whole percentages that add up to 100 and
    the x/width of each segment of a stacked bar."""
    counts: dict[str, int] = {}
    for s in statuses:
        counts[s] = counts.get(s, 0) + 1
    keys = [s for s in order if counts.get(s)] + sorted(s for s in counts if s not in order)
    total = sum(counts.values())
    pcts = weight_shares({i: float(counts[k]) for i, k in enumerate(keys)})
    out, x = [], 0.0
    for i, k in enumerate(keys):
        w = counts[k] * 100 / total
        out.append(Segment(k, counts[k], pcts[i], round(x, 2), round(w, 2)))
        x += w
    return out



def ago(when, now) -> str:
    """'just now', '5 min ago', '3 h ago', 'yesterday', else 'Nov 3'. Both datetimes must be comparable."""
    if when is None:
        return ""
    secs = (now - when).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    if secs < 2 * 86400:
        return "yesterday"
    return f"{when:%b} {when.day}"
