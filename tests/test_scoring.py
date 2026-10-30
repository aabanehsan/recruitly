"""Rubric parsing, weighted averages and the who-sees-whose-scores rules (pure functions)."""

import pytest

from recruitly.services.scoring import (
    SheetView, fmt_score, move, parse_criterion, parse_round_name, parse_scores, parse_weight, pick_round,
    score_band, sort_by_score, summarize_round, visible_averages, visible_sheets, weight_shares, weighted_score,
)


@pytest.mark.parametrize("text,expected", [
    ("1", 1.0), ("2", 2.0), (" 1.5 ", 1.5), ("x2", 2.0), ("2x", 2.0), ("×3", 3.0), ("150%", 1.5),
    ("1.3", 1.5), ("10", 10.0), ("0.5", 0.5),
    ("0", None), ("-1", None), ("11", None), ("0.2", None), ("abc", None), ("", None), ("nan", None),
])
def test_parse_weight(text, expected):
    assert parse_weight(text) == expected


def test_parse_criterion():
    c, errors = parse_criterion("  Communication   skills ", "  Clear answers ", "2", ["Leadership"])
    assert not errors and (c.name, c.description, c.weight) == ("Communication skills", "Clear answers", 2.0)
    c, _ = parse_criterion("Fit", "", "")
    assert c.weight == 1.0 and c.description is None  # blank weight means 1
    _, errors = parse_criterion("", "", "1")
    assert "name" in errors
    _, errors = parse_criterion("leadership", "", "1", ["Leadership"])
    assert "already" in errors["name"]
    _, errors = parse_criterion("X" * 61, "y" * 301, "lots")
    assert set(errors) == {"name", "description", "weight"}


def test_parse_round_name():
    assert parse_round_name("  Group   interview ", ["First round"]) == ("Group interview", None)
    assert parse_round_name("first ROUND", ["First round"])[1]
    assert parse_round_name("")[1] and parse_round_name("r" * 41)[1]


def test_weight_shares_add_up_to_100():
    shares = weight_shares({1: 1, 2: 1, 3: 1})
    assert sum(shares.values()) == 100 and sorted(shares.values()) == [33, 33, 34]
    assert weight_shares({1: 2, 2: 1.5, 3: 2, 4: 1}) == {1: 31, 2: 23, 3: 31, 4: 15}
    assert weight_shares({}) == {}


def test_move():
    assert move([1, 2, 3], 2, "up") == [2, 1, 3]
    assert move([1, 2, 3], 2, "down") == [1, 3, 2]
    assert move([1, 2, 3], 1, "up") == [1, 2, 3]  # already first
    assert move([1, 2, 3], 3, "down") == [1, 2, 3]
    assert move([1, 2, 3], 9, "up") == [1, 2, 3]
    assert move([1, 2, 3], 2, "sideways") == [1, 2, 3]


def test_parse_scores_draft_and_submit():
    form = {"score_1": "4", "score_2": "", "score_3": "5"}
    scores, notes, errors = parse_scores(form, [1, 2, 3], submit=False, notes="  good energy \r\n ")
    assert scores == {1: 4, 3: 5} and notes == "good energy" and not errors  # drafts can be partial

    _, _, errors = parse_scores(form, [1, 2, 3], submit=True)
    assert set(errors) == {"score_2"}

    _, _, errors = parse_scores({"score_1": "6", "score_2": "x"}, [1, 2], submit=False)
    assert set(errors) == {"score_1", "score_2"}

    # fields for criteria that no longer exist are ignored
    scores, _, errors = parse_scores({"score_1": "3", "score_99": "5"}, [1], submit=True)
    assert scores == {1: 3} and not errors

    _, _, errors = parse_scores({}, [], submit=False, notes="x" * 5001)
    assert "notes" in errors


def test_parse_scores_without_a_rubric_needs_notes_to_submit():
    assert "notes" in parse_scores({}, [], submit=True)[2]
    assert parse_scores({}, [], submit=True, notes="Great")[2] == {}


def test_weighted_score():
    w = {1: 2, 2: 1, 3: 1}
    assert weighted_score({1: 5, 2: 3, 3: 1}, w) == pytest.approx((10 + 3 + 1) / 4)
    assert weighted_score({1: 4}, w) == 4  # only what's scored counts
    assert weighted_score({}, w) is None
    assert weighted_score({1: 5, 9: 1}, {1: 1}) == 5  # deleted criteria don't count
    assert fmt_score(4.25) == "4.2" and fmt_score(None) == "—"
    assert [score_band(v) for v in (None, 2.9, 3, 4.1)] == ["none", "low", "mid", "high"]


ALICE, BOB, CARA = 1, 2, 3  # members; CARA is an admin in these tests


def sheets():
    return [
        SheetView(10, 100, 1, ALICE, True, 4.0),   # Alice scored applicant 100, round 1
        SheetView(11, 100, 1, BOB, True, 2.0),     # Bob too
        SheetView(12, 100, 2, BOB, True, 5.0),     # Bob scored round 2 as well
        SheetView(13, 100, 2, ALICE, False, 3.0),  # Alice only has a draft for round 2
        SheetView(14, 200, 1, BOB, True, 3.0),     # only Bob scored applicant 200
        SheetView(15, 300, 1, None, True, 1.0),    # a former member's sheet still counts
    ]


def ids(views):
    return sorted(v.sheet_id for v in views)


def test_members_only_see_others_after_submitting_that_round():
    # Alice: her own sheets, Bob's round 1 sheet (she submitted round 1), but not Bob's round 2
    assert ids(visible_sheets(sheets(), ALICE, False)) == [10, 11, 13]
    # Bob submitted everything he's in, but never sees Alice's round 2 draft
    assert ids(visible_sheets(sheets(), BOB, False)) == [10, 11, 12, 14]
    # someone who scored nothing sees nothing
    assert visible_sheets(sheets(), 99, False) == []


def test_admins_see_every_submitted_sheet_but_never_drafts():
    assert ids(visible_sheets(sheets(), CARA, True)) == [10, 11, 12, 14, 15]


def test_visible_averages():
    assert visible_averages(sheets(), ALICE, False) == {100: 3.0}  # (4 + 2) / 2; 200 and 300 hidden
    assert visible_averages(sheets(), BOB, False) == {100: pytest.approx(11 / 3), 200: 3.0}
    assert visible_averages(sheets(), CARA, True) == {100: pytest.approx(11 / 3), 200: 3.0, 300: 1.0}
    assert visible_averages(sheets(), 99, False) == {}


def test_sort_by_score_puts_unscored_last():
    assert sort_by_score([5, 6, 7, 8], {6: 3.5, 8: 4.5}) == [8, 6, 5, 7]


def test_pick_round():
    rounds = [(1, "First round"), (2, "Final round")]
    assert pick_round(rounds, [], None) == 1
    assert pick_round(rounds, ["First round", "final ROUND"], None) == 2  # latest interview label
    assert pick_round(rounds, ["Coffee chat"], None) == 1
    assert pick_round(rounds, ["Final round"], 1) == 1  # asked for explicitly
    assert pick_round(rounds, [], 42) == 1  # unknown id
    assert pick_round([], [], None) is None


def test_summarize_round():
    rows = [(SheetView(1, 100, 1, ALICE, True, 4.0), {7: 4, 8: 4}),
            (SheetView(2, 100, 1, BOB, True, 2.5), {7: 2}),
            (SheetView(3, 100, 1, CARA, False, 5.0), {7: 5, 8: 5})]  # draft: not counted
    s = summarize_round(1, rows, [7, 8], unlocked=True)
    assert s.submitted == 2 and s.average == pytest.approx(3.25)
    assert [(c.criterion_id, c.average, c.count) for c in s.per_criterion] == [(7, 3.0, 2), (8, 4.0, 1)]
    hidden = summarize_round(1, rows, [7, 8], unlocked=False)
    assert hidden.submitted == 2 and hidden.average is None and hidden.per_criterion == []
