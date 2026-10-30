"""Rubric admin, score sheets, the anchoring rule on profiles and the board, and demo scores."""

import re

import pytest
from fastapi.testclient import TestClient

from conftest import login, make_user


def add_applicant(client, first="Jo", last="Park"):
    r = client.post("/applicants/new", data={"first_name": first, "last_name": last,
                                             "email": f"{first.lower()}.{last.lower()}@utexas.edu"},
                    follow_redirects=True)
    assert r.status_code == 200, r.text
    return int(re.search(r"/applicants/(\d+)/edit", r.text).group(1))


def add_criterion(client, name, weight="1", description="", expect=303):
    r = client.post("/rubric/criteria", data={"name": name, "weight": weight, "description": description},
                    follow_redirects=False)
    assert r.status_code == expect, r.text
    return r


def db():
    from recruitly.db import session_scope

    return session_scope()


def crit_ids():
    from recruitly.models import Criterion

    with db() as s:
        return [c.id for c in s.query(Criterion).order_by(Criterion.position)]


def round_ids():
    from recruitly.models import Round

    with db() as s:
        return {r.name: r.id for r in s.query(Round)}


def score(client, ap, values, notes="", action="submit", round_name="First round", expect=303):
    data = {"round_id": str(round_ids()[round_name]), "action": action, "notes": notes}
    data |= {f"score_{cid}": str(v) for cid, v in zip(crit_ids(), values) if v is not None}
    r = client.post(f"/applicants/{ap}/score", data=data, follow_redirects=False)
    assert r.status_code == expect, r.text
    return r


@pytest.fixture()
def rubric(client):
    add_criterion(client, "Communication", "2")
    add_criterion(client, "Leadership", "1")
    return crit_ids()


@pytest.fixture()
def member2(app, client):
    make_user("third@example.org", role="member", name="Tia Third")
    with TestClient(app) as c:
        yield login(c, "third@example.org")


# ------------------------------------------------------------------ rubric

def test_fresh_install_has_default_rounds_and_empty_rubric(client, member):
    assert set(round_ids()) == {"First round", "Final round"}
    page = member.get("/rubric").text
    assert "No rubric yet" in page and "Only admins can change the rubric" in page
    assert 'action="/rubric/criteria"' not in page
    assert 'href="/rubric"' in member.get("/").text  # in the nav for everyone


def test_admin_builds_the_rubric(client):
    add_criterion(client, "Communication", "2", "Clear answers")
    add_criterion(client, "Leadership", "1")
    add_criterion(client, "Fit", "x1")
    page = client.get("/rubric").text
    assert "Communication" in page and "Clear answers" in page and "×2" in page and "50%" in page

    r = add_criterion(client, "communication", expect=422)
    assert "already a criterion called communication" in r.text
    r = add_criterion(client, "Drive", weight="20", expect=422)
    assert "Weight must be a number" in r.text and 'value="Drive"' in r.text  # keeps what you typed

    comm, lead, fit = crit_ids()
    r = client.post(f"/rubric/criteria/{lead}/edit", data={"name": "Ownership", "weight": "1.5", "description": ""},
                    follow_redirects=True)
    assert "Saved Ownership" in r.text
    r = client.post(f"/rubric/criteria/{fit}/edit", data={"name": "Ownership", "weight": "1"})
    assert r.status_code == 422

    client.post(f"/rubric/criteria/{fit}/move", data={"direction": "up"})
    assert crit_ids() == [comm, fit, lead]
    client.post(f"/rubric/criteria/{comm}/move", data={"direction": "up"})  # already first: no-op
    assert crit_ids() == [comm, fit, lead]


def test_deleting_a_criterion_drops_its_scores_and_reweights(client, rubric):
    from recruitly.models import Score

    ap = add_applicant(client)
    score(client, ap, [5, 2])  # (5*2 + 2*1) / 3 = 4.0
    assert ">4.0<" in client.get(f"/applicants/{ap}").text
    r = client.post(f"/rubric/criteria/{rubric[1]}/delete", follow_redirects=True)
    assert "Removed Leadership" in r.text
    with db() as s:
        assert s.query(Score).count() == 1
    assert ">5.0<" in client.get(f"/applicants/{ap}").text


def test_rounds(client, rubric):
    r = client.post("/rubric/rounds", data={"name": "Group interview"}, follow_redirects=True)
    assert "Added Group interview" in r.text
    assert client.post("/rubric/rounds", data={"name": "group INTERVIEW"}).status_code == 422
    rid = round_ids()
    r = client.post(f"/rubric/rounds/{rid['Group interview']}/edit", data={"name": "Case round"}, follow_redirects=True)
    assert "Renamed to Case round" in r.text

    ap = add_applicant(client)
    score(client, ap, [3, 3])
    r = client.post(f"/rubric/rounds/{rid['First round']}/delete", follow_redirects=True)
    assert "already has score sheets" in r.text and "First round" in round_ids()
    client.post(f"/rubric/rounds/{rid['Group interview']}/delete")
    client.post(f"/rubric/rounds/{rid['Final round']}/delete")
    assert list(round_ids()) == ["First round"]
    r = client.post(f"/rubric/rounds/{rid['First round']}/delete", follow_redirects=True)
    assert "Keep at least one round" in r.text


def test_members_cant_change_the_rubric(client, member, rubric):
    assert member.post("/rubric/criteria", data={"name": "Sneaky", "weight": "5"}).status_code == 403
    assert member.post(f"/rubric/criteria/{rubric[0]}/delete").status_code == 403
    assert len(crit_ids()) == 2


# ------------------------------------------------------------------ score sheets

def test_score_sheet_draft_then_submit(client, member, rubric):
    ap = add_applicant(client)
    page = member.get(f"/applicants/{ap}/score").text
    assert "Score Jo Park" in page and "Communication" in page and "Submit scores" in page

    r = score(member, ap, [4, None], notes="Good energy", action="draft")
    assert "Draft+saved" in r.headers["location"]
    page = member.get(f"/applicants/{ap}/score").text
    assert "Draft" in page and "Good energy" in page and 'value="4" checked' in page

    # submitting needs every criterion
    r = score(member, ap, [4, None], notes="Good energy", action="submit", expect=422)
    assert "Score this before submitting" in r.text and "Good energy" in r.text

    r = score(member, ap, [4, 5], notes="Good energy", action="submit")
    assert r.headers["location"] == f"/applicants/{ap}?msg=" + "Scores+submitted+%284.3%29.+You+can+now+see+everyone%27s+First+round+scores."
    prof = member.get(f"/applicants/{ap}").text
    assert "Max Member (you)" in prof and ">4.3<" in prof and "Edit my scores" in prof

    # a submitted sheet can be changed, but not emptied back into a draft
    r = score(member, ap, [2, 5])
    assert "Scores+updated" in r.headers["location"]
    assert score(member, ap, [2, None], action="draft", expect=422).status_code == 422

    from recruitly.models import ScoreSheet
    with db() as s:
        [sheet] = s.query(ScoreSheet).all()
        assert sheet.submitted and sheet.score_map == {rubric[0]: 2, rubric[1]: 5}


def test_bad_scores_and_unknown_round(client, rubric):
    ap = add_applicant(client)
    r = client.post(f"/applicants/{ap}/score", data={"round_id": "999", "action": "submit"})
    assert r.status_code == 400
    r = client.post(f"/applicants/{ap}/score", data={"round_id": str(round_ids()["First round"]), "action": "submit",
                                                   f"score_{rubric[0]}": "9", f"score_{rubric[1]}": "3"})
    assert r.status_code == 422 and "Pick a score from 1 to 5" in r.text
    assert client.get("/applicants/999/score").status_code == 404


def test_one_sheet_per_member_per_round(client, rubric):
    from recruitly.models import ScoreSheet

    ap = add_applicant(client)
    score(client, ap, [3, 3])
    score(client, ap, [4, 4])
    score(client, ap, [5, 5], round_name="Final round")
    with db() as s:
        assert s.query(ScoreSheet).count() == 2
    page = client.get(f"/applicants/{ap}/score?round={round_ids()['Final round']}").text
    assert 'value="5" checked' in page and "Save changes" in page
    r = client.post(f"/applicants/{ap}/score/delete", data={"round_id": str(round_ids()["Final round"])},
                    follow_redirects=True)
    assert "Final round sheet was deleted" in r.text
    with db() as s:
        assert s.query(ScoreSheet).count() == 1


def test_score_page_opens_on_the_round_of_the_latest_interview(client, rubric):
    from datetime import datetime, timedelta

    ap = add_applicant(client)
    day = (datetime.now() + timedelta(days=3)).date().isoformat()
    client.post("/schedule/slots", data={"date": day, "time": "18:00", "minutes": "30", "repeat": "1",
                                         "location": "GSB", "label": "Final round"})
    from recruitly.models import InterviewSlot
    with db() as s:
        slot = s.query(InterviewSlot).one().id
    client.post(f"/schedule/slots/{slot}/book", data={"applicant_id": str(ap)})
    page = client.get(f"/applicants/{ap}/score").text
    assert f'name="round_id" value="{round_ids()["Final round"]}"' in page


def test_notes_are_escaped(client, rubric):
    ap = add_applicant(client)
    score(client, ap, [3, 3], notes="<script>alert(1)</script>")
    page = client.get(f"/applicants/{ap}").text
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page


# ------------------------------------------------------------------ anchoring

def test_members_cant_see_others_scores_until_they_submit(client, member, member2, rubric):
    ap = add_applicant(client)
    score(member, ap, [5, 5], notes="Max thinks she is great")

    prof = member2.get(f"/applicants/{ap}").text
    assert "1 person has scored this round" in prof and "Submit your own scores to see theirs" in prof
    assert "Max thinks she is great" not in prof and "Max Member" not in prof and ">5.0<" not in prof
    assert "average of" not in prof

    # a draft isn't enough
    score(member2, ap, [1, None], notes="Tia draft", action="draft")
    prof = member2.get(f"/applicants/{ap}").text
    assert "Max thinks she is great" not in prof and "Tia draft" in prof
    assert "Tia draft" not in member.get(f"/applicants/{ap}").text  # drafts stay private

    score(member2, ap, [1, 1], notes="Tia disagrees")
    prof = member2.get(f"/applicants/{ap}").text
    assert "Max thinks she is great" in prof and "Max Member" in prof and ">5.0<" in prof and ">3.0<" in prof
    assert "average of 2 sheets" in prof

    # unlocking is per round
    score(member, ap, [4, 4], round_name="Final round", notes="Final round notes")
    prof = member2.get(f"/applicants/{ap}").text
    assert "Final round notes" not in prof


def test_admin_sees_scores_folded_until_they_score(client, member, rubric):
    ap = add_applicant(client)
    score(member, ap, [4, 4], notes="Member notes")
    prof = client.get(f"/applicants/{ap}").text
    assert '<details class="peek">' in prof and "Show 1 score" in prof and "Member notes" in prof
    assert "score them first so you aren't anchored" in prof
    score(client, ap, [2, 2])
    prof = client.get(f"/applicants/{ap}").text
    assert '<details class="peek">' not in prof and "Member notes" in prof


def test_board_average_and_sort_respect_the_rule(client, member, member2, rubric):
    a = add_applicant(client, "Ana", "Alpha")
    b = add_applicant(client, "Ben", "Beta")
    add_applicant(client, "Cy", "Gamma")
    score(member, a, [3, 3])
    score(member, b, [5, 5])

    board = client.get("/?sort=score").text  # admin sees every average
    names = re.findall(r'<div class="name">([^<]+)</div>', board)
    assert names == ["Ben Beta", "Ana Alpha", "Cy Gamma"]
    assert 'title="Average score">5.0<' in board and 'title="Average score">3.0<' in board

    board = member2.get("/?sort=score").text  # hasn't scored anyone: no averages, plain name order
    assert 'title="Average score"' not in board
    assert re.findall(r'<div class="name">([^<]+)</div>', board) == ["Ana Alpha", "Ben Beta", "Cy Gamma"]

    score(member2, a, [1, 1])
    board = member2.get("/?sort=score").text
    assert 'title="Average score">2.0<' in board and 'title="Average score">5.0<' not in board
    assert board.count("You scored") == 1
    assert 'value="score" selected' in board


# ------------------------------------------------------------------ cleanup

def test_removed_members_sheets_are_kept_as_former_member(client, member, rubric):
    from recruitly.models import User

    ap = add_applicant(client)
    score(member, ap, [4, 4], notes="Kept after leaving")
    score(client, ap, [3, 3])
    with db() as s:
        mid = s.query(User).filter_by(email="member@example.org").one().id
    client.post(f"/members/{mid}/remove")
    prof = client.get(f"/applicants/{ap}").text
    assert "Former member" in prof and "Kept after leaving" in prof and "average of 2 sheets" in prof


def test_deleting_an_applicant_deletes_their_sheets(client, rubric):
    from recruitly.models import Score, ScoreSheet

    ap = add_applicant(client)
    score(client, ap, [4, 4])
    client.post(f"/applicants/{ap}/delete")
    with db() as s:
        assert s.query(ScoreSheet).count() == 0 and s.query(Score).count() == 0


def test_notes_only_without_a_rubric(client):
    ap = add_applicant(client)
    page = client.get(f"/applicants/{ap}/score").text
    assert "this sheet is just notes" in page
    r = client.post(f"/applicants/{ap}/score", data={"round_id": str(round_ids()["First round"]),
                                                   "action": "submit", "notes": ""})
    assert r.status_code == 422
    score(client, ap, [], notes="Just notes")
    assert "Just notes" in client.get(f"/applicants/{ap}").text


def test_demo_scores(app, capsys):
    from recruitly.cli import create_demo_accounts, load_demo, load_demo_schedule, load_demo_scores
    from recruitly.demo import DEMO_RUBRIC, DEMO_SHEETS
    from recruitly.models import Criterion, ScoreSheet

    load_demo()
    create_demo_accounts()
    load_demo_schedule()
    load_demo_scores()
    load_demo_scores()  # idempotent
    with db() as s:
        assert s.query(Criterion).count() == len(DEMO_RUBRIC)
        sheets = s.query(ScoreSheet).all()
        assert len(sheets) == len(DEMO_SHEETS)
        assert sum(1 for x in sheets if not x.submitted) == sum(1 for x in DEMO_SHEETS if not x[5])
    assert "Added demo rubric" in capsys.readouterr().out
