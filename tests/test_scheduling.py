"""Pure scheduling rules: parsing the slot form, double booking, display helpers and .ics output."""

from datetime import date, datetime, timedelta, timezone

from recruitly.services.scheduling import (
    Busy, CalEvent, booking_conflicts, build_ics, day_label, first_overlap, fold, group_by_day, ics_escape,
    location_url, overlaps, parse_date, parse_slot_input, parse_time, slot_choice_label, status_after_booking,
    time_range, to_utc,
)

SIX = datetime(2026, 10, 27, 18, 0)


def test_parse_time_accepts_browser_and_human_formats():
    assert parse_time("18:30") == (18, 30)
    assert parse_time("06:05") == (6, 5)
    assert parse_time("6:30 PM") == (18, 30)
    assert parse_time("6pm") == (18, 0)
    assert parse_time("12 am") == (0, 0)
    assert parse_time("12:15 p.m.") == (12, 15)
    for bad in ["", "6", "25:00", "13pm", "6:75", "noon", "0 am"]:
        assert parse_time(bad) is None, bad


def test_parse_date():
    assert parse_date("2026-10-27") == date(2026, 10, 27)
    assert parse_date("10/27/2026") == date(2026, 10, 27)
    assert parse_date("10/27/26") == date(2026, 10, 27)
    assert parse_date("2026-02-30") is None
    assert parse_date("next tuesday") is None


def test_slot_input_makes_back_to_back_slots():
    s, errors = parse_slot_input("2026-10-27", "18:00", "30", "  GSB   2.124 ", "First round", "4")
    assert errors == {}
    assert s.starts == [SIX, SIX.replace(minute=30), SIX.replace(hour=19), SIX.replace(hour=19, minute=30)]
    assert s.minutes == 30 and s.location == "GSB 2.124" and s.label == "First round"


def test_slot_input_blank_optional_fields_and_errors():
    s, errors = parse_slot_input("2026-10-27", "6:30 pm", "45")
    assert errors == {} and s.starts == [SIX.replace(minute=30)] and s.location is None and s.label is None
    s, errors = parse_slot_input("", "lunch", "0", "x" * 301, "y" * 81, "99")
    assert s is None
    assert set(errors) == {"date", "time", "minutes", "location", "label", "repeat"}
    assert parse_slot_input("2026-10-27", "18:00", "abc")[1].keys() == {"minutes"}


def test_overlaps_but_back_to_back_is_fine():
    assert overlaps(SIX, 30, SIX + timedelta(minutes=15), 30)
    assert overlaps(SIX, 60, SIX + timedelta(minutes=15), 15)  # inside
    assert overlaps(SIX, 30, SIX, 30)
    assert not overlaps(SIX, 30, SIX + timedelta(minutes=30), 30)
    assert not overlaps(SIX + timedelta(minutes=30), 30, SIX, 30)


def test_first_overlap_and_ignore_self():
    busy = [Busy(1, SIX, 30), Busy(2, SIX + timedelta(hours=1), 30)]
    assert first_overlap(SIX + timedelta(minutes=10), 30, busy).key == 1
    assert first_overlap(SIX + timedelta(minutes=10), 30, busy, ignore=1) is None
    assert first_overlap(SIX + timedelta(minutes=30), 30, busy) is None


def test_booking_conflicts_per_person():
    people = {7: [Busy(1, SIX, 30)], 8: [Busy(2, SIX + timedelta(hours=2), 30)], 9: []}
    starts = [SIX - timedelta(minutes=30), SIX]  # the second new slot hits person 7
    clashes = booking_conflicts(starts, 30, people)
    assert set(clashes) == {7}
    assert clashes[7][0] == SIX and clashes[7][1].key == 1
    assert booking_conflicts(starts, 30, people, ignore=1) == {}


def test_status_moves_to_interviewing_only_from_applied():
    assert status_after_booking("applied") == "interviewing"
    for s in ["interviewing", "final_round", "offered", "accepted"]:
        assert status_after_booking(s) == s


def test_group_by_day_sorts():
    times = [SIX + timedelta(days=1), SIX + timedelta(hours=1), SIX]
    days = group_by_day(times, lambda t: t)
    assert [d for d, _ in days] == [date(2026, 10, 27), date(2026, 10, 28)]
    assert days[0][1] == [SIX, SIX + timedelta(hours=1)]


def test_display_helpers():
    assert time_range(SIX, 30) == "6:00 – 6:30 PM"
    assert time_range(datetime(2026, 10, 27, 11, 30), 45) == "11:30 AM – 12:15 PM"
    assert day_label(date(2026, 10, 27)) == "Tuesday, Oct 27"
    assert day_label(date(2026, 10, 27), today=date(2026, 10, 27)) == "Today · Tuesday, Oct 27"
    assert day_label(date(2026, 10, 28), today=date(2026, 10, 27)) == "Tomorrow · Wednesday, Oct 28"
    assert day_label(date(2027, 1, 5), today=date(2026, 10, 27)) == "Tuesday, Jan 5, 2027"
    assert slot_choice_label(SIX, 30, "GSB 2.124") == "Tue Oct 27 · 6:00 – 6:30 PM · GSB 2.124"
    assert slot_choice_label(SIX, 30, "https://utexas.zoom.us/j/123") == "Tue Oct 27 · 6:00 – 6:30 PM · Zoom"


def test_location_url_only_links_http():
    assert location_url("https://utexas.zoom.us/j/123?pwd=x") == "https://utexas.zoom.us/j/123?pwd=x"
    assert location_url("utexas.zoom.us/j/123") == "https://utexas.zoom.us/j/123"
    assert location_url("meet.google.com/abc-defg-hij") == "https://meet.google.com/abc-defg-hij"
    assert location_url("GSB 2.124") is None
    assert location_url("javascript:alert(1)") is None
    assert location_url(None) is None


def test_to_utc_follows_daylight_saving():
    assert to_utc(datetime(2026, 10, 27, 18, 0), "America/Chicago") == datetime(2026, 10, 27, 23, 0, tzinfo=timezone.utc)
    assert to_utc(datetime(2026, 11, 10, 18, 0), "America/Chicago") == datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
    assert to_utc(SIX, "Not/AZone") == SIX.replace(tzinfo=timezone.utc)  # bad setting falls back to UTC


def test_ics_escape_and_fold():
    assert ics_escape("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
    long = "DESCRIPTION:" + "é" * 80
    folded = fold(long)
    parts = folded.split("\r\n")
    assert len(parts) > 1 and all(len(p.encode()) <= 75 for p in parts)
    assert parts[1].startswith(" ")
    assert "".join(p[1:] if i else p for i, p in enumerate(parts)) == long


def test_build_ics():
    start = datetime(2026, 10, 27, 23, 0, tzinfo=timezone.utc)
    ev = CalEvent(uid="slot-1@x", start=start, minutes=30, summary="Interview: Jordan Lee, CS",
                  location="GSB 2.124", description="Interviewers: Alex\nProfile: http://x/applicants/1",
                  url="https://zoom.us/j/1")
    out = build_ics([ev, CalEvent(uid="slot-2@x", start=start, minutes=15, summary="Open interview slot")], "Org interviews",
                    now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert out.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n") and out.endswith("END:VCALENDAR\r\n")
    assert out.count("BEGIN:VEVENT") == 2 and out.count("END:VEVENT") == 2
    assert "DTSTART:20261027T230000Z" in out and "DTEND:20261027T233000Z" in out
    assert "DTSTAMP:20261001T000000Z" in out
    assert "SUMMARY:Interview: Jordan Lee\\, CS" in out
    assert "DESCRIPTION:Interviewers: Alex\\nProfile: http://x/applicants/1" in out
    assert "URL:https://zoom.us/j/1" in out and "LOCATION:GSB 2.124" in out
    assert all(len(line.encode()) <= 75 for line in out.split("\r\n"))
    assert "\n" not in out.replace("\r\n", "")
