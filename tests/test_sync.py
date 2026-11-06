"""Pure helpers behind Sheets re-sync and email drafts."""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlsplit

from recruitly.services.emails import (
    DEFAULT_TEMPLATES, PLACEHOLDERS, draft_values, mailto_link, make_draft, placeholders_in, render, validate_template,
)
from recruitly.services.sync import changed_fields, describe_changes, merge_mapping, sync_summary, time_ago

NOW = datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ sync

def test_changed_fields_ignores_blanks_and_number_formatting():
    old = {"phone": "512-555-0143", "gpa": 3.7, "major": "Finance", "hometown": "Austin, TX", "minor": None}
    assert changed_fields(old, {"phone": "512-555-0143", "gpa": 3.70, "major": "Finance"}) == []
    # a blank answer never erases saved data
    assert changed_fields(old, {"hometown": "", "minor": None}) == []
    assert changed_fields(old, {"gpa": 3.72, "major": "MIS", "minor": "Business Foundations"}) == \
        ["major", "minor", "gpa"]  # in display order
    assert changed_fields({"gpa": None}, {"gpa": 3.5}) == ["gpa"]
    assert changed_fields({"why_join": "Text "}, {"why_join": "Text"}) == []


def test_describe_changes_uses_labels_and_truncates():
    assert describe_changes(["gpa", "why_join"]) == "GPA, Why join"
    assert describe_changes(["phone", "major", "minor", "gpa", "hometown", "linkedin"]) == \
        "Phone, Major, Minor, GPA +2 more"


def test_merge_mapping_keeps_admin_fixes_and_guesses_new_columns():
    auto = {"Email": "email", "Name": "full_name", "Pronouns": None, "New question": "fun_fact"}
    saved = {"Email": "email", "Name": "full_name", "Pronouns": "preferred_name", "Old column": "gpa"}
    merged = merge_mapping(list(auto), saved, auto)
    assert merged == {"Email": "email", "Name": "full_name", "Pronouns": "preferred_name", "New question": "fun_fact"}
    # an ignored column stays ignored
    assert merge_mapping(["Email"], {"Email": None}, {"Email": "email"}) == {"Email": None}
    assert merge_mapping(["Email"], None, {"Email": "email"}) == {"Email": "email"}


def test_time_ago():
    assert time_ago(None) == "never"
    assert time_ago(NOW - timedelta(seconds=20), NOW) == "just now"
    assert time_ago(NOW - timedelta(minutes=1), NOW) == "1 minute ago"
    assert time_ago(NOW - timedelta(minutes=45), NOW) == "45 minutes ago"
    assert time_ago(NOW - timedelta(hours=3, minutes=5), NOW) == "3 hours ago"
    assert time_ago(NOW - timedelta(hours=26), NOW) == "yesterday"
    assert time_ago(NOW - timedelta(days=5), NOW) == "5 days ago"
    assert time_ago(datetime(2026, 9, 2, 12, 0), NOW) == "Sep 2, 2026"  # naive = UTC


def test_sync_summary():
    assert sync_summary(2, 1, 12) == "2 new, 1 updated, 12 unchanged"


# ------------------------------------------------------------------ emails

def test_placeholders_in_and_literal_braces():
    assert placeholders_in("Hi {first_name}, {slot_time} {first_name} {{not_one}}") == ["first_name", "slot_time"]
    assert placeholders_in("") == []


def test_validate_template():
    assert validate_template("Invite", "Interview {slot_time}", "Hi {first_name}") == {}
    errs = validate_template("", "", "")
    assert set(errs) == {"name", "subject", "body"}
    errs = validate_template("Invite", "Hi {frist_name}", "Bye {nope} {email}")
    assert "{frist_name}" in errs["subject"] and "{nope}" in errs["body"] and "email" not in errs["body"]
    assert "subject" in validate_template("x", "line one\nline two", "body")
    assert "body" in validate_template("x", "s", "b" * 10_001)


def test_default_templates_only_use_known_placeholders():
    for name, _, subject, body in DEFAULT_TEMPLATES:
        assert validate_template(name, subject, body) == {}, name


def test_render_fills_values_and_flags_missing():
    text, missing = render("Hi {first_name}! See you {slot_time}. {{literal}}", {"first_name": "Pri", "slot_time": None})
    assert text == "Hi Pri! See you {slot_time}. {literal}"
    assert missing == ["slot_time"]


def test_draft_values_prefers_preferred_name_and_formats_slot():
    v = draft_values(first_name="Priya", last_name="Raman", preferred_name="Pri", email="p@utexas.edu",
                     slot_start=datetime(2026, 11, 12, 18, 0), slot_minutes=30, slot_location="GSB 2.124",
                     org_name="TBA", cycle_name="Fall Rush", sender_name="Alex")
    assert v["first_name"] == "Pri" and v["full_name"] == "Pri Raman"
    assert v["slot_time"] == "Thursday, Nov 12 at 6:00 PM"
    assert v["slot_date"] == "Thursday, Nov 12" and v["slot_length"] == "30 minutes"
    assert v["slot_location"] == "GSB 2.124"
    assert set(v) == set(PLACEHOLDERS)
    bare = draft_values(first_name="Jo", last_name="Park", preferred_name=None, email="jo@x.org")
    assert bare["first_name"] == "Jo" and bare["slot_time"] is None


def test_mailto_link_encodes_everything():
    url = mailto_link("jo+rush@utexas.edu", "Interview: Thu & Fri?", "Hi Jo,\n\n100% yes = great #1")
    assert url.startswith("mailto:jo+rush@utexas.edu?subject=")
    q = parse_qs(urlsplit(url).query)
    assert q["subject"] == ["Interview: Thu & Fri?"]
    assert q["body"] == ["Hi Jo,\r\n\r\n100% yes = great #1"]
    assert " " not in url and "\n" not in url
    assert unquote(url).count("&") == 2  # the separator plus the one in the subject


def test_make_draft():
    values = draft_values(first_name="Jo", last_name="Park", preferred_name=None, email="jo@x.org", org_name="TBA")
    d = make_draft(7, "Jo Park", "Welcome to {org_name}", "Hi {first_name}, your slot: {slot_time} {slot_time}",
                   values)
    assert (d.applicant_id, d.to, d.subject) == (7, "jo@x.org", "Welcome to TBA")
    assert d.missing == ["slot_time"]
    assert d.mailto.startswith("mailto:jo@x.org?") and not d.mailto_too_long
    long = make_draft(7, "Jo", "s", "word " * 500, values)
    assert long.mailto_too_long
