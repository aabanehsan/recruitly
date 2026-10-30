"""Interview scheduling pages: slots, booking, double-booking checks, auto status and .ics export."""

import re
from datetime import datetime, timedelta

import pytest

from conftest import make_user

DAY = (datetime.now() + timedelta(days=3)).date()
ISO = DAY.isoformat()


def add_applicant(client, first="Jo", last="Park", email=None):
    email = email or f"{first.lower()}.{last.lower()}@utexas.edu"
    r = client.post("/applicants/new", data={"first_name": first, "last_name": last, "email": email},
                    follow_redirects=True)
    assert r.status_code == 200, r.text
    return int(re.search(r"/applicants/(\d+)/edit", r.text).group(1))


def add_slots(client, time="18:00", minutes="30", repeat="1", interviewers=(), location="GSB 2.124", day=ISO,
              label="", expect=303):
    r = client.post("/schedule/slots", data={"date": day, "time": time, "minutes": minutes, "repeat": repeat,
                                             "location": location, "label": label,
                                             "interviewers": [str(i) for i in interviewers]},
                    follow_redirects=False)
    assert r.status_code == expect, r.text
    return r


def slots():
    from recruitly.db import session_scope
    from recruitly.models import InterviewSlot

    with session_scope() as s:
        return [(x.id, x.starts_at, x.applicant_id, sorted(x.interviewer_ids))
                for x in s.query(InterviewSlot).order_by(InterviewSlot.starts_at)]


def status_of(ap_id):
    from recruitly.db import session_scope
    from recruitly.models import Applicant

    with session_scope() as s:
        return s.get(Applicant, ap_id).status


@pytest.fixture()
def admin_id(client):
    from recruitly.db import session_scope
    from recruitly.models import User

    with session_scope() as s:
        return s.query(User).filter_by(email="admin@example.org").one().id


def test_add_back_to_back_slots_and_view_by_day(client, admin_id):
    r = add_slots(client, repeat="3", interviewers=[admin_id], label="First round")
    assert "Added+3+slots" in r.headers["location"]
    page = client.get("/schedule").text
    assert f"{DAY:%A}, {DAY:%b} {DAY.day}" in page
    assert "6:00 – 6:30 PM" in page and "6:30 – 7:00 PM" in page and "7:00 – 7:30 PM" in page
    assert "First round" in page and "GSB 2.124" in page and "Ada Admin" in page
    assert "3 upcoming slots · 0 booked · 3 open" in page
    assert [s[3] for s in slots()] == [[admin_id]] * 3
    # a second day shows up as its own group
    add_slots(client, day=(DAY + timedelta(days=1)).isoformat())
    page = client.get("/schedule").text
    assert page.count('class="dayh"') == 2


def test_bad_slot_form_shows_errors(client):
    r = add_slots(client, time="whenever", minutes="0", expect=422)
    assert "Enter a start time" in r.text and "Length must be" in r.text
    assert slots() == []


def test_interviewers_cannot_be_double_booked(client, admin_id):
    other = make_user("bo@example.org", name="Bo Interviewer")
    add_slots(client, time="18:00", minutes="60", interviewers=[admin_id])
    r = add_slots(client, time="18:30", interviewers=[admin_id, other], expect=422)
    assert "Ada Admin is already interviewing then" in r.text and "Bo Interviewer is already" not in r.text
    assert len(slots()) == 1
    add_slots(client, time="18:30", interviewers=[other])  # a different interviewer, same time: fine
    add_slots(client, time="19:00", interviewers=[admin_id])  # right after: fine
    assert len(slots()) == 3


def test_booking_moves_status_to_interviewing(client):
    ap = add_applicant(client)
    add_slots(client, repeat="2")
    first, second = slots()
    r = client.post(f"/schedule/slots/{first[0]}/book", data={"applicant_id": ap, "next": "/schedule"},
                    follow_redirects=True)
    assert "Booked Jo Park" in r.text and "Status moved to Interviewing" in r.text
    assert status_of(ap) == "interviewing"
    assert "1 booked · 1 open" in r.text
    # board and profile show the interview
    assert f"Interview {DAY:%a} {DAY:%b} {DAY.day}, 6:00 PM" in client.get("/").text
    prof = client.get(f"/applicants/{ap}").text
    assert "6:00 – 6:30 PM" in prof and "GSB 2.124" in prof and "Book an open slot" in prof
    # a second, non-overlapping interview is allowed and doesn't touch the status again
    client.post(f"/applicants/{ap}/status", data={"status": "final_round"})
    r = client.post(f"/applicants/{ap}/book", data={"slot_id": second[0]}, follow_redirects=True)
    assert "Booked Jo Park" in r.text and "Status moved" not in r.text
    assert status_of(ap) == "final_round"


def test_applicants_cannot_be_double_booked(client, admin_id):
    other = make_user("bo@example.org", name="Bo Interviewer")
    ap, ap2 = add_applicant(client), add_applicant(client, "Sam", "Diaz")
    add_slots(client, interviewers=[admin_id])
    add_slots(client, time="18:15", interviewers=[other])
    a, b = slots()
    client.post(f"/schedule/slots/{a[0]}/book", data={"applicant_id": ap})
    r = client.post(f"/applicants/{ap}/book", data={"slot_id": b[0]}, follow_redirects=True)
    assert "Jo Park is already booked then" in r.text
    # the slot itself holds one applicant
    r = client.post(f"/schedule/slots/{a[0]}/book", data={"applicant_id": ap2}, follow_redirects=True)
    assert "That slot already has Jo Park" in r.text
    assert [s[2] for s in slots()] == [ap, None]


def test_cut_applicants_cannot_be_booked(client):
    ap = add_applicant(client)
    client.post(f"/applicants/{ap}/status", data={"status": "cut"})
    add_slots(client)
    sid = slots()[0][0]
    r = client.post(f"/schedule/slots/{sid}/book", data={"applicant_id": ap}, follow_redirects=True)
    assert "marked Cut" in r.text and slots()[0][2] is None
    r = client.post(f"/schedule/slots/{sid}/book", data={"applicant_id": ""}, follow_redirects=True)
    assert "Pick an applicant" in r.text


def test_edit_slot_keeps_bookings_consistent(client, admin_id):
    other = make_user("bo@example.org", name="Bo Interviewer")
    ap = add_applicant(client)
    add_slots(client, time="18:00", interviewers=[admin_id])
    add_slots(client, time="19:00", interviewers=[other])
    a, b = slots()
    client.post(f"/schedule/slots/{a[0]}/book", data={"applicant_id": ap})
    client.post(f"/schedule/slots/{b[0]}/book", data={"applicant_id": add_applicant(client, "Sam", "Diaz")})
    form = client.get(f"/schedule/slots/{a[0]}/edit").text
    assert 'value="18:00"' in form and "Jo Park" in form

    base = {"date": ISO, "minutes": "30", "location": "Zoom", "label": ""}
    # moving Bo onto slot A at 19:00 clashes with Bo's own slot
    r = client.post(f"/schedule/slots/{a[0]}/edit", data=base | {"time": "19:00", "interviewers": [str(other)]})
    assert r.status_code == 422 and "Bo Interviewer is already interviewing then" in r.text
    # a slot doesn't clash with itself
    r = client.post(f"/schedule/slots/{a[0]}/edit",
                    data=base | {"time": "18:10", "location": "https://utexas.zoom.us/j/42",
                                 "interviewers": [str(admin_id), str(other)]}, follow_redirects=True)
    assert r.status_code == 200 and "Slot saved" in r.text and "Join video call" in r.text
    assert slots()[0][1].minute == 10 and slots()[0][3] == sorted([admin_id, other])
    assert 'href="https://utexas.zoom.us/j/42"' in r.text


def test_edit_cannot_move_booked_applicant_onto_their_other_slot(client):
    ap = add_applicant(client)
    add_slots(client, time="18:00")
    add_slots(client, time="20:00")
    a, b = slots()
    client.post(f"/schedule/slots/{a[0]}/book", data={"applicant_id": ap})
    client.post(f"/schedule/slots/{b[0]}/book", data={"applicant_id": ap})
    r = client.post(f"/schedule/slots/{b[0]}/edit", data={"date": ISO, "time": "18:15", "minutes": "30"})
    assert r.status_code == 422 and "Jo Park is booked in another slot then" in r.text


def test_unbook_and_delete(client):
    ap = add_applicant(client)
    add_slots(client, repeat="2")
    a, b = slots()
    client.post(f"/schedule/slots/{a[0]}/book", data={"applicant_id": ap})
    r = client.post(f"/schedule/slots/{a[0]}/unbook", data={"next": f"/applicants/{ap}"}, follow_redirects=True)
    assert "Unbooked Jo Park" in r.text and "Not scheduled yet" in r.text
    assert status_of(ap) == "interviewing"  # unbooking doesn't undo progress
    client.post(f"/schedule/slots/{b[0]}/book", data={"applicant_id": ap})
    r = client.post(f"/schedule/slots/{b[0]}/delete", data={"next": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"].startswith("/schedule?msg=Slot+deleted")
    assert [s[0] for s in slots()] == [a[0]]


def test_deleting_people_frees_their_slots(client):
    uid = make_user("bo@example.org", name="Bo Interviewer")
    ap = add_applicant(client)
    add_slots(client, interviewers=[uid])
    sid = slots()[0][0]
    client.post(f"/schedule/slots/{sid}/book", data={"applicant_id": ap})
    client.post(f"/applicants/{ap}/delete")
    client.post(f"/members/{uid}/remove")
    assert slots() == [(sid, slots()[0][1], None, [])]
    assert "No interviewers yet" in client.get("/schedule").text


def test_past_slots_are_hidden_until_asked(client):
    from recruitly.db import session_scope
    from recruitly.models import InterviewSlot

    with session_scope() as s:
        s.add(InterviewSlot(starts_at=datetime(2025, 9, 1, 18, 0), minutes=30, location="Old room"))
        s.commit()
    add_slots(client)
    page = client.get("/schedule").text
    assert "Old room" not in page and "Show past" in page
    assert "Old room" in client.get("/schedule?past=1").text
    assert "Old room" not in client.get("/schedule.ics").text
    assert "Old room" in client.get("/schedule.ics?past=1").text


def test_ics_export(client, member):
    from recruitly.db import session_scope
    from recruitly.models import User

    with session_scope() as s:
        member_id = s.query(User).filter_by(email="member@example.org").one().id
    ap = add_applicant(client)
    add_slots(client, time="18:00", interviewers=[member_id], label="First round")
    add_slots(client, time="19:00")
    client.post(f"/schedule/slots/{slots()[0][0]}/book", data={"applicant_id": ap})

    r = client.get("/schedule.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert 'filename="interviews.ics"' in r.headers["content-disposition"]
    body = r.text
    assert body.count("BEGIN:VEVENT") == 2
    assert "SUMMARY:Interview: Jo Park (First round)" in body and "SUMMARY:Open interview slot" in body
    assert "Interviewers: Max Member" in body and "/applicants/" in body and "LOCATION:GSB 2.124" in body
    assert re.search(r"DTSTART:\d{8}T\d{6}Z", body)

    mine = member.get("/schedule.ics?mine=1")
    assert mine.status_code == 200 and mine.text.count("BEGIN:VEVENT") == 1 and "Jo Park" in mine.text
    assert 'filename="my-interviews.ics"' in mine.headers["content-disposition"]


def test_members_see_the_schedule_read_only(client, member):
    from recruitly.db import session_scope
    from recruitly.models import User

    with session_scope() as s:
        member_id = s.query(User).filter_by(email="member@example.org").one().id
    ap = add_applicant(client)
    add_slots(client, interviewers=[member_id])
    add_slots(client, time="20:00")
    client.post(f"/schedule/slots/{slots()[0][0]}/book", data={"applicant_id": ap})
    page = member.get("/schedule").text
    assert "Jo Park" in page and "Max Member" in page and 'href="/schedule"' in page
    assert "Add interview slots" not in page and "/book" not in page and "/edit" not in page
    assert "My interviews (.ics)" in page
    mine = member.get("/schedule?view=mine").text
    assert "Jo Park" in mine and "8:00" not in mine
    prof = member.get(f"/applicants/{ap}").text
    assert "6:00 – 6:30 PM" in prof and "Book an open slot" not in prof and "Unbook" not in prof


def test_demo_schedule(app, capsys):
    from recruitly.cli import create_demo_accounts, load_demo, load_demo_schedule
    from recruitly.db import session_scope
    from recruitly.demo import DEMO_ADVANCED, DEMO_BOOKINGS, DEMO_SLOTS
    from recruitly.models import Applicant, InterviewSlot

    load_demo()
    create_demo_accounts()
    load_demo_schedule()
    load_demo_schedule()  # idempotent
    with session_scope() as s:
        all_slots = s.query(InterviewSlot).all()
        assert len(all_slots) == sum(g[3] for g in DEMO_SLOTS)
        booked = [x for x in all_slots if x.applicant_id]
        assert len(booked) == len(DEMO_BOOKINGS)
        assert all(x.interviewers for x in all_slots)
        assert {x.applicant.status for x in booked if x.applicant.email not in DEMO_ADVANCED} == {"interviewing"}
        assert {x.applicant.status for x in booked if x.applicant.email in DEMO_ADVANCED} == {"final_round"}
        assert s.query(Applicant).filter_by(status="applied").count() > 0
    assert "Added demo schedule" in capsys.readouterr().out
