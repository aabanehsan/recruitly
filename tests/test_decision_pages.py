"""Decisions page, deliberation sessions and votes, results visibility, bulk status, and demo votes."""

import re

from conftest import make_user
from test_scoring_pages import add_applicant, add_criterion, member2, score  # noqa: F401 - fixture


def db():
    from recruitly.db import session_scope

    return session_scope()


def open_session(client, name="Debrief", expect=303):
    r = client.post("/decisions/sessions", data={"name": name}, follow_redirects=False)
    assert r.status_code == expect, r.text
    from recruitly.models import Deliberation

    with db() as s:
        d = s.query(Deliberation).order_by(Deliberation.id.desc()).first()
        return d.id if d else None


def vote(c, d, ap, choice, next_url="/decisions"):
    return c.post(f"/decisions/sessions/{d}/vote", data={"applicant_id": str(ap), "choice": choice, "next": next_url},
                  follow_redirects=False)


def votes():
    from recruitly.models import Vote

    with db() as s:
        return sorted((v.applicant_id, v.user_id, v.choice) for v in s.query(Vote))


def status_of(ap):
    from recruitly.models import Applicant

    with db() as s:
        return s.get(Applicant, ap).status


def test_decisions_page_ranks_by_score_with_flags(client, member):
    a = add_applicant(client, "Ana", "Alvarez")
    b = add_applicant(client, "Ben", "Brooks")
    c = add_applicant(client, "Cal", "Chen")
    add_criterion(client, "Communication")
    score(client, a, [3])
    score(client, b, [5])
    score(member, b, [2])
    page = client.get("/decisions").text
    assert page.index("Ben Brooks") < page.index("Ana Alvarez") < page.index("Cal Chen")
    assert "Split ±3.0" in page and "1 scorer" in page and "No scores" in page
    assert "Funnel" in page and "Status mix" in page and '<svg class="fbar"' in page
    assert 'action="/decisions/bulk-status"' in page and 'name="applicant_id" value="%d"' % c in page
    by_name = client.get("/decisions?sort=name").text
    assert by_name.index("Ana Alvarez") < by_name.index("Ben Brooks")
    only_applied = client.get("/decisions?status=applied").text
    assert "Ben Brooks" in only_applied
    assert "Ben Brooks" not in client.get("/decisions?status=offered").text

    # members get the anchoring rule: no averages (or split flags) for people they haven't scored
    mpage = member.get("/decisions").text
    assert "you only see averages for applicants you&#39;ve scored" in mpage or "you've scored" in mpage
    assert "bulk-status" not in mpage
    row_a = re.search(r'id="ap-%d".*?</tr>' % a, mpage, re.S).group(0)
    assert 'class="avg' not in row_a and "1 scorer" in row_a
    row_b = re.search(r'id="ap-%d".*?</tr>' % b, mpage, re.S).group(0)
    assert 'class="avg' in row_b and "Split" in row_b  # Max scored Ben, so the round is unlocked


def test_open_vote_close_and_results(client, member, member2):  # noqa: F811
    ap = add_applicant(client)
    cut = add_applicant(client, "Cy", "Cut")
    client.post(f"/applicants/{cut}/status", data={"status": "cut"})
    assert "No vote is open" in member.get("/decisions").text
    assert vote(member, 1, ap, "yes").status_code == 404  # no session yet

    d = open_session(client, "  First-round   debrief ")
    assert open_session(client, "Another") == d  # only one open at a time
    page = member.get("/decisions").text
    assert "First-round debrief" in page and "Voting open" in page and "Yes</button>" in page
    assert "Out of the running" in page

    r = vote(member, d, ap, "yes", f"/decisions?sort=name#ap-{ap}")
    assert r.status_code == 303 and r.headers["location"] == f"/decisions?sort=name#ap-{ap}"
    vote(member2, d, ap, "no")
    vote(client, d, ap, "abstain")
    vote(member2, d, ap, "yes")  # changed their mind
    assert [v[2] for v in votes()] == ["abstain", "yes", "yes"]
    r = vote(member, d, cut, "yes")
    assert "error=" in r.headers["location"] and len(votes()) == 3
    assert "error=" in vote(member, d, ap, "maybe").headers["location"]
    vote(member, d, ap, "yes")  # clicking your vote again clears it
    vote(member, d, ap, "yes")
    assert len(votes()) == 3

    # while open: members see only their own vote, admins see the live tally
    mres = member.get(f"/decisions/sessions/{d}").text
    assert "Results stay hidden" in mres and "2 yes" not in mres and ">Yes<" in mres
    assert "yes · " not in member.get("/decisions").text.replace("<b class=\"yes\">", "")
    ares = client.get(f"/decisions/sessions/{d}").text
    assert "Live tally" in ares and re.search(r'<b class="yes">2</b> yes', ares)
    assert re.search(r'<b class="yes">2</b> yes', client.get("/decisions").text)
    assert "Counts unlock" in member.get(f"/applicants/{ap}").text

    r = client.post(f"/decisions/sessions/{d}/close", follow_redirects=True)
    assert "is closed" in r.text and "Majority yes" in r.text
    mres = member.get(f"/decisions/sessions/{d}").text
    assert re.search(r'<b class="yes">2</b> yes · <b class="no">0</b> no · <b>1</b> abstain', mres)
    assert "Majority yes" in mres and "You voted yes" in mres and "bulk-status" not in mres
    assert "error=" in vote(member, d, ap, "no").headers["location"]  # locked
    assert "First-round debrief" in member.get(f"/applicants/{ap}").text  # past result on the profile
    page = member.get("/decisions").text
    assert "Past sessions" in page and "3 votes" in page
    assert open_session(client, "Final") != d  # a new session can open now


def test_bulk_status(client):
    a, b, c = add_applicant(client, "A", "One"), add_applicant(client, "B", "Two"), add_applicant(client, "C", "Three")
    r = client.post("/decisions/bulk-status", data={"applicant_id": [str(a), str(c)], "status": "offered",
                                                    "next": "/decisions?status=applied"}, follow_redirects=False)
    assert r.headers["location"].startswith("/decisions?status=applied&msg=Set+2+applicants+to+Offered")
    assert [status_of(x) for x in (a, b, c)] == ["offered", "applied", "offered"]
    r = client.post("/decisions/bulk-status", data={"status": "cut"}, follow_redirects=True)
    assert "Select at least one applicant" in r.text
    r = client.post("/decisions/bulk-status", data={"applicant_id": str(b), "status": "promoted"},
                    follow_redirects=True)
    assert "Pick a status" in r.text and status_of(b) == "applied"
    client.post("/decisions/bulk-status", data={"applicant_id": str(b), "status": "cut", "next": "https://evil.com"})
    assert status_of(b) == "cut"
    page = client.get("/decisions").text
    assert re.search(r"Offered</li>|Offered<b>2</b>", page)


def test_funnel_on_the_page(client):
    from recruitly.models import Applicant

    ids = [add_applicant(client, n, "X") for n in ("Al", "Bo", "Cy", "Di")]
    with db() as s:
        for i, st in zip(ids, ["applied", "final_round", "offered", "accepted"]):
            s.get(Applicant, i).status = st
        s.commit()
    page = client.get("/decisions").text
    assert re.search(r"Interviewed</b><span><b>3</b>", page) and "75% of applied" in page
    assert "67% of interviewed" in page and "50% of offered" in page


def test_deleting_things_cleans_up_votes(client, member):
    from recruitly.models import Deliberation

    ap = add_applicant(client)
    other = add_applicant(client, "Bo", "Bell")
    d = open_session(client)
    vote(member, d, ap, "yes")
    vote(member, d, other, "no")
    client.post(f"/applicants/{ap}/delete")
    assert [v[0] for v in votes()] == [other]
    member_id = votes()[0][1]
    client.post(f"/members/{member_id}/remove")
    assert votes() == [(other, None, "no")]  # removed member's vote still counts
    client.post(f"/decisions/sessions/{d}/close")
    assert "1 vote from 1 person" in client.get(f"/decisions/sessions/{d}").text
    client.post(f"/decisions/sessions/{d}/delete")
    assert votes() == []
    with db() as s:
        assert s.query(Deliberation).count() == 0


def test_member_cannot_run_sessions(client, member):
    d = open_session(client)
    assert member.post("/decisions/sessions", data={"name": "x"}).status_code == 403
    assert member.post(f"/decisions/sessions/{d}/close").status_code == 403
    assert member.post(f"/decisions/sessions/{d}/delete").status_code == 403
    assert member.post("/decisions/bulk-status", data={"status": "cut"}).status_code == 403
    assert client.get("/decisions/sessions/999").status_code == 404


def test_demo_votes(app, capsys):
    from recruitly.cli import create_demo_accounts, load_demo, load_demo_schedule, load_demo_scores, load_demo_votes
    from recruitly.demo import DEMO_DELIBERATIONS
    from recruitly.models import Applicant, Deliberation, Vote

    load_demo()
    create_demo_accounts()
    load_demo_schedule()
    load_demo_scores()
    load_demo_votes()
    load_demo_votes()  # idempotent
    expected = sum(len(by) for _, _, _, ballots, _ in DEMO_DELIBERATIONS for by in ballots.values())
    with db() as s:
        assert s.query(Deliberation).count() == 2
        assert s.query(Deliberation).filter(Deliberation.closed_at.is_(None)).count() == 1
        assert s.query(Vote).count() == expected  # every demo applicant and voter was found
        assert s.query(Applicant).filter(Applicant.status == "cut").count() == 4
    assert "Added demo deliberations" in capsys.readouterr().out
