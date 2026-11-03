"""Pure decision rules: ranking, flags, votes, bulk status parsing and the funnel."""

from datetime import datetime, timedelta, timezone

from recruitly.services.decisions import (
    Tally, ago, can_see_tally, can_vote, flags_for, funnel, parse_bulk, parse_session_name, parse_vote, rank,
    rank_results, score_stats, stage_reached, status_mix, tally_votes,
)
from recruitly.services.scoring import SheetView


def sv(sheet, ap, user, total, submitted=True, rnd=1):
    return SheetView(sheet, ap, rnd, user, submitted, total)


def test_rank_shares_ties_and_puts_unscored_last():
    out = rank([1, 2, 3, 4, 5], {1: 3.0, 2: 4.5, 3: 4.5, 5: 2.0})
    assert out == [(1, 2), (1, 3), (3, 1), (4, 5), (None, 4)]
    assert rank([], {}) == []
    # float noise doesn't break a tie
    assert [r for r, _ in rank([1, 2], {1: 4.25, 2: 4.2500000001})] == [1, 1]


def test_score_stats_counts_scorers_and_respects_anchoring():
    sheets = [
        sv(1, 10, 1, 5.0), sv(2, 10, 2, 2.0),  # split, both submitted
        sv(3, 10, 3, None, submitted=False),  # a draft
        sv(4, 11, None, 4.0), sv(5, 11, None, 3.0),  # two removed members still count as two scorers
    ]
    admin = score_stats(sheets, 99, True)
    assert admin[10].scorers == 2 and admin[10].drafts == 1 and admin[10].spread == 3.0
    assert admin[11].scorers == 2
    # a member who hasn't scored applicant 10 sees the count but no spread
    other = score_stats(sheets, 99, False)
    assert other[10].scorers == 2 and other[10].spread is None
    # once they've submitted in that round, they see it
    mine = score_stats(sheets + [sv(6, 10, 99, 4.0)], 99, False)
    assert mine[10].spread == 3.0 and mine[10].scorers == 3


def test_flags():
    from recruitly.services.decisions import ScoreStats

    keys = lambda fl: [f.key for f in fl]  # noqa: E731
    assert keys(flags_for(None, "applied", False)) == ["unscored"]
    assert flags_for(None, "interviewing", True)[0].tone == "err"  # interviewed but nobody scored
    assert keys(flags_for(None, "cut", False)) == []  # nothing to chase for someone already cut
    assert keys(flags_for(ScoreStats(1, 0, None), "interviewing", True)) == ["one"]
    assert keys(flags_for(ScoreStats(3, 2, 1.5), "interviewing", True)) == ["split", "draft"]
    assert keys(flags_for(ScoreStats(3, 0, 1.4), "interviewing", True)) == []
    assert flags_for(ScoreStats(2, 2, None), "x", True)[0].label == "2 drafts"


def test_parse_vote():
    assert parse_vote("yes") == ("yes", None)
    assert parse_vote(" NO ") == ("no", None)
    assert parse_vote("abstain", "yes") == ("abstain", None)
    assert parse_vote("yes", "yes") == (None, None)  # clicking your vote again takes it back
    assert parse_vote("clear", "no") == (None, None)
    assert parse_vote("maybe")[1]


def test_who_can_vote_and_see():
    assert can_vote(True, "interviewing") is None
    assert "closed" in can_vote(False, "interviewing")
    assert "out of the running" in can_vote(True, "cut")
    assert can_vote(True, "declined")
    assert can_see_tally(True, True) and can_see_tally(False, False)
    assert not can_see_tally(False, True)


def test_tally_and_results_order():
    t = tally_votes([(1, "yes"), (1, "yes"), (1, "no"), (2, "no"), (2, "abstain"), (3, "yes"), (3, "no"),
                     (4, "abstain"), (5, "bogus")])
    assert (t[1].yes, t[1].no, t[1].abstain, t[1].total) == (2, 1, 0, 3)
    assert 5 not in t
    assert t[1].verdict == "yes" and t[2].verdict == "no" and t[3].verdict == "tied" and t[4].verdict == "none"
    assert t[1].yes_share == 2 / 3 and t[4].yes_share is None
    assert rank_results(t) == [1, 3, 4, 2]
    bar = t[1].bar()
    assert [c for c, _, _ in bar] == ["yes", "no"] and abs(sum(w for _, _, w in bar) - 100) < 0.1
    assert bar[1][1] == bar[0][2]  # "no" starts where "yes" ends
    assert Tally().bar() == []


def test_session_name():
    assert parse_session_name("  First   round debrief ", "x") == ("First round debrief", None)
    assert parse_session_name("", "Deliberation Nov 3") == ("Deliberation Nov 3", None)
    assert parse_session_name("x" * 61, "d")[1]


def test_parse_bulk():
    statuses = ["applied", "offered", "cut"]
    assert parse_bulk(["3", "1", "3", "x", "99"], "offered", statuses, [1, 2, 3]) == ([3, 1], "offered", None)
    assert parse_bulk(["1"], "promoted", statuses, [1])[2] == "Pick a status to set."
    assert parse_bulk([], "cut", statuses, [1])[2] == "Select at least one applicant first."


def test_funnel_counts_how_far_people_got():
    statuses = {1: "applied", 2: "interviewing", 3: "interviewing", 4: "cut", 5: "final_round", 6: "offered",
                7: "accepted", 8: "declined"}
    st = funnel(statuses, interviewed={3, 4})
    assert [s.count for s in st] == [8, 6, 3, 1]  # 3, 4 (cut after interview), 5, 6, 7, 8
    assert [s.conversion for s in st] == [None, 75, 50, 33]
    assert st[0].share == 100 and st[0].w == 100 and st[0].x == 0
    assert st[3].w == 12.5 and st[3].x == 43.75  # centred
    assert stage_reached("interviewing", False) == 0 and stage_reached("cut", True) == 1
    empty = funnel({}, set())
    assert [s.count for s in empty] == [0, 0, 0, 0] and empty[1].conversion == 0 and empty[0].w == 0


def test_status_mix():
    mix = status_mix(["cut", "applied", "applied", "offered"], ["applied", "interviewing", "offered", "cut"])
    assert [(m.status, m.count, m.pct) for m in mix] == [("applied", 2, 50), ("offered", 1, 25), ("cut", 1, 25)]
    assert mix[1].x == 50 and mix[2].x == 75
    thirds = status_mix(["a", "b", "c"], ["a", "b", "c"])
    assert sum(m.pct for m in thirds) == 100
    assert status_mix([], ["a"]) == []


def test_ago():
    now = datetime(2026, 11, 3, 18, tzinfo=timezone.utc)
    assert ago(now - timedelta(seconds=20), now) == "just now"
    assert ago(now - timedelta(minutes=5), now) == "5 min ago"
    assert ago(now - timedelta(hours=3), now) == "3 h ago"
    assert ago(now - timedelta(hours=30), now) == "yesterday"
    assert ago(now - timedelta(days=4), now) == "Oct 30"
    assert ago(None, now) == ""
