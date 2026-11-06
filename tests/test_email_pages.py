"""Email templates and per-applicant drafts."""

import html
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from test_schedule_pages import add_applicant, add_slots

DAY = (datetime.now() + timedelta(days=3)).date()


def db():
    from recruitly.db import session_scope

    return session_scope()


def template_ids():
    from recruitly.models import EmailTemplate

    with db() as s:
        return {t.name: t.id for t in s.query(EmailTemplate)}


def set_status(client, ap, status):
    client.post(f"/applicants/{ap}/status", data={"status": status})


def mailtos(page):
    return [html.unescape(u) for u in re.findall(r'href="(mailto:[^"]+)"', page)]


def test_starter_templates_are_seeded_once(client):
    ids = template_ids()
    assert set(ids) == {"Interview invite", "Offer", "Rejection"}
    page = client.get("/emails").text
    assert "Interview invite" in page and "{slot_time}" in page and "Make drafts" in page
    client.post(f"/emails/{ids['Offer']}/delete")
    from recruitly.app import create_app

    create_app()  # restarting doesn't bring a deleted template back
    assert "Offer" not in template_ids()


def test_create_edit_and_validate_templates(client):
    r = client.post("/emails/new", data={"name": "", "audience": "all", "subject": "Hi {frist_name}", "body": ""})
    assert r.status_code == 422 and "Unknown placeholder {frist_name}" in r.text and "Give the template a name" in r.text
    r = client.post("/emails/new", data={"name": "Final round", "audience": "final_round",
                                         "subject": "Final round: {slot_date}", "body": "Hi {first_name}"},
                    follow_redirects=True)
    assert "Template “Final round” added" in r.text and "Status: Final Round" in r.text
    tid = template_ids()["Final round"]
    form = client.get(f"/emails/{tid}/edit").text
    assert 'value="Final round: {slot_date}"' in form and "option value=\"final_round\" selected" in form
    client.post(f"/emails/{tid}/edit", data={"name": "Final", "audience": "bogus", "subject": "s", "body": "b"})
    assert "Final" not in template_ids()  # bad audience → not saved
    r = client.post(f"/emails/{tid}/edit", data={"name": "Final", "audience": "all", "subject": "s",
                                                 "body": "line 1\r\nline 2"}, follow_redirects=True)
    assert "Template “Final” saved" in r.text
    from recruitly.models import EmailTemplate

    with db() as s:
        assert s.get(EmailTemplate, tid).body == "line 1\nline 2"
    assert client.get("/emails/999/edit").status_code == 404


def test_invite_drafts_for_booked_applicants(client):
    jo = add_applicant(client, "Jo", "Park")
    add_applicant(client, "Al", "Unbooked")
    add_slots(client, time="18:00", location="GSB 2.124", day=DAY.isoformat())
    from recruitly.models import InterviewSlot

    with db() as s:
        slot = s.query(InterviewSlot).one().id
    client.post(f"/schedule/slots/{slot}/book", data={"applicant_id": str(jo)})

    tid = template_ids()["Interview invite"]
    page = client.get(f"/emails/{tid}/drafts").text
    assert "1 draft for booked for an upcoming interview" in page
    assert "Al Unbooked" not in page and "Jo Park" in page
    when = f"{DAY:%A}, {DAY:%b} {DAY.day} at 6:00 PM"
    assert f"Recruitly interview: {when}" in page  # default org name
    assert "Where: GSB 2.124" in page and "How long: 30 minutes" in page and "Ada Admin" in page
    assert "Fill in by hand" not in page
    [link] = mailtos(page)
    assert link.startswith("mailto:jo.park@utexas.edu?")
    q = parse_qs(urlsplit(link).query)
    assert q["subject"] == [f"Recruitly interview: {when}"] and q["body"][0].startswith("Hi Jo,\r\n\r\nThanks")
    assert 'data-copy="body-%d"' % jo in page and "Copy all 1 addresses" in page


def test_drafts_by_status_and_missing_placeholders(client):
    a = add_applicant(client, "Ana", "Alvarez")
    b = add_applicant(client, "Ben", "Brooks")
    add_applicant(client, "Cal", "Chen")
    set_status(client, a, "cut")
    set_status(client, b, "cut")
    ids = template_ids()
    page = client.get(f"/emails/{ids['Rejection']}/drafts").text
    assert "2 drafts for status: cut" in page and "Cal Chen" not in page
    assert len(mailtos(page)) == 2 and "ana.alvarez@utexas.edu, ben.brooks@utexas.edu" in page
    # someone else can be picked; an invite for someone without a slot flags the placeholders
    page = client.get(f"/emails/{ids['Interview invite']}/drafts?audience=applied").text
    assert "Cal Chen" in page and "Fill in by hand" in page and "no upcoming interview booked" in page
    page = client.get(f"/emails/{ids['Offer']}/drafts").text
    assert "No applicants match" in page
    page = client.get(f"/emails/{ids['Interview invite']}/drafts").text
    assert "No one is booked for an upcoming interview" in page
    # unknown audience falls back to the template's own
    assert "2 drafts" in client.get(f"/emails/{ids['Rejection']}/drafts?audience=nope").text


def test_single_applicant_draft_from_profile(client):
    ap = add_applicant(client, "Jo", "Park")
    client.post(f"/applicants/{ap}/edit", data={"first_name": "Joanna", "last_name": "Park", "preferred_name": "Jo",
                                                "email": "jo.park@utexas.edu"})
    tid = template_ids()["Offer"]
    profile = client.get(f"/applicants/{ap}").text
    assert "Email drafts" in profile and f'href="/emails/{tid}/drafts?applicant={ap}"' in profile
    page = client.get(f"/emails/{tid}/drafts?applicant={ap}").text
    assert "Draft for" in page and "Hi Jo," in page and "Welcome to Recruitly!" in page
    assert client.get(f"/emails/{tid}/drafts?applicant=999").status_code == 404


def test_members_cant_use_email_templates(client, member):
    ap = add_applicant(client)
    tid = template_ids()["Offer"]
    assert member.get("/emails").status_code == 403
    assert member.get(f"/emails/{tid}/drafts").status_code == 403
    assert "Email drafts" not in member.get(f"/applicants/{ap}").text
    assert 'href="/emails"' not in member.get("/").text


def test_demo_has_invite_and_rejection_drafts(app):
    from fastapi.testclient import TestClient

    from conftest import login
    from recruitly.cli import create_demo_accounts, load_demo, load_demo_schedule, load_demo_votes

    load_demo()
    create_demo_accounts()
    load_demo_schedule()
    load_demo_votes()
    with TestClient(app) as c:
        login(c, "admin@demo.recruitly.dev", "demo-admin-2026")
        ids = template_ids()
        invites = c.get(f"/emails/{ids['Interview invite']}/drafts").text
        assert len(mailtos(invites)) >= 6 and "Fill in by hand" not in invites
        assert "Alex Admin" in invites
        rejections = c.get(f"/emails/{ids['Rejection']}/drafts").text
        assert len(mailtos(rejections)) == 4
