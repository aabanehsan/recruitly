from datetime import datetime

import pytest

from recruitly.services.cleaning import (
    CleanResult, clean_classification, clean_email, clean_gpa, clean_grad_term, clean_linkedin, clean_majors,
    clean_phone, clean_row, drive_file_id, map_headers, smart_title,
)

TODAY = datetime(2026, 10, 1)


def r():
    return CleanResult()


def test_header_mapping_from_real_form_questions():
    m = map_headers([
        "Timestamp", "Email Address", "Full Name", "What is your major?", "Second major (if any)",
        "What year are you?", "Expected graduation date", "GPA (optional)", "Upload a headshot",
        "Why do you want to join?", "Anything else?",
    ])
    assert m["Timestamp"] == "submitted_at"
    assert m["Email Address"] == "email"
    assert m["Full Name"] == "full_name"
    assert m["What is your major?"] == "major"
    assert m["Second major (if any)"] == "second_major"
    assert m["What year are you?"] == "classification"
    assert m["Expected graduation date"] == "grad_term"
    assert m["GPA (optional)"] == "gpa"
    assert m["Upload a headshot"] == "headshot"
    assert m["Why do you want to join?"] == "why_join"
    assert m["Anything else?"] is None


def test_each_field_claimed_once():
    m = map_headers(["Email", "Email (again)"])
    assert list(m.values()).count("email") == 1


@pytest.mark.parametrize("raw,out", [
    ("jOHN", "jOHN"), ("john", "John"), ("MCDONALD", "McDonald"), ("o'neil", "O'Neil"),
    ("mary-jane", "Mary-Jane"), ("ana de la cruz", "Ana de la Cruz"),
])
def test_names(raw, out):
    assert (smart_title(raw) if raw.islower() or raw.isupper() else raw) == out


@pytest.mark.parametrize("raw,out", [
    ("  Jordan.Lee@UTEXAS.EDU ", "jordan.lee@utexas.edu"),
    ("x@utexas.com", "x@utexas.edu"), ("y@gmial.com", "y@gmail.com"), ("mailto:z@utexas.edu", "z@utexas.edu"),
])
def test_email_ok(raw, out):
    assert clean_email(raw, r(), None) == out


def test_email_invalid_and_domain_warning():
    res = r()
    assert clean_email("not-an-email", res, None) is None
    assert res.issues[0].level == "error"
    res = r()
    assert clean_email("a@gmail.com", res, "utexas.edu") == "a@gmail.com"
    assert res.issues[0].level == "warning"


@pytest.mark.parametrize("raw,out", [
    ("512.555.0143", "(512) 555-0143"), ("+1 (737) 555-0110", "(737) 555-0110"), ("5125550143", "(512) 555-0143"),
])
def test_phone(raw, out):
    assert clean_phone(raw, r()) == out


def test_phone_bad_kept_with_warning():
    res = r()
    assert clean_phone("123", res) == "123"
    assert res.issues[0].level == "warning"


@pytest.mark.parametrize("raw,second,out", [
    ("comp sci", "", ("Computer Science", None)),
    ("CS and Math", "", ("Computer Science", "Mathematics")),
    ("Electrical and Computer Engineering", "", ("Electrical and Computer Engineering", None)),
    ("Finance", "MIS", ("Finance", "Management Information Systems")),
    ("Kinesology", "", ("Kinesiology", None)),
    ("B.S. Computer Science (Turing Scholars)", "", ("Computer Science", None)),
    ("Finance / Accounting", "", ("Finance", "Accounting")),
])
def test_majors(raw, second, out):
    assert clean_majors(raw, second, r()) == out


def test_unknown_major_kept_with_warning():
    res = r()
    assert clean_majors("underwater basket weaving", "", res)[0] == "Underwater Basket Weaving"
    assert any(i.level == "warning" for i in res.issues)


@pytest.mark.parametrize("raw,out", [
    ("1st year", "Freshman"), ("sophmore", "Sophomore"), ("JUNIOR", "Junior"), ("4th year", "Senior"),
    ("transfer student", "Transfer"),
])
def test_classification(raw, out):
    assert clean_classification(raw, r()) == out


@pytest.mark.parametrize("raw,out", [
    ("spring 2028", "May 2028"), ("Fall 2027", "Dec 2027"), ("May 2028", "May 2028"), ("5/2027", "May 2027"),
    ("'29", "May 2029"), ("2028", "May 2028"), ("December 2026", "Dec 2026"), ("summer 2027", "Aug 2027"),
])
def test_grad_term(raw, out):
    assert clean_grad_term(raw, r(), TODAY) == out


@pytest.mark.parametrize("raw,out", [
    ("3.71", 3.71), ("3.9/4.0", 3.9), ("4.3/5", 3.44), ("N/A", None), ("first semester", None), ("", None),
    ("3.6 final", 3.6),
])
def test_gpa(raw, out):
    assert clean_gpa(raw, r()) == out


def test_gpa_out_of_range():
    res = r()
    assert clean_gpa("4.6", res) is None
    assert res.issues[0].level == "warning"


@pytest.mark.parametrize("raw,out", [
    ("linkedin.com/in/jordan-lee", "https://www.linkedin.com/in/jordan-lee"),
    ("https://www.linkedin.com/in/priya/", "https://www.linkedin.com/in/priya"),
    ("jordan-lee", "https://www.linkedin.com/in/jordan-lee"),
])
def test_linkedin(raw, out):
    assert clean_linkedin(raw, r()) == out


def test_drive_ids():
    assert drive_file_id("https://drive.google.com/open?id=1AbCdEfGhIjKl") == "1AbCdEfGhIjKl"
    assert drive_file_id("https://drive.google.com/file/d/1AbCdEfGhIjKl/view") == "1AbCdEfGhIjKl"


def test_full_row_split_name_and_required_fields():
    res = clean_row({"full_name": "  jordan   lee ", "email": "J@UTEXAS.EDU"}, today=TODAY)
    assert res.ok
    assert res.values["first_name"] == "Jordan" and res.values["last_name"] == "Lee"
    bad = clean_row({"first_name": "", "email": ""})
    assert not bad.ok
    assert {i.field for i in bad.issues if i.level == "error"} == {"first_name", "email"}


def test_long_text_keeps_paragraphs():
    res = clean_row({"first_name": "A", "email": "a@b.co", "why_join": "Line one.\r\n\r\n\r\n\r\nLine   two."})
    assert res.values["why_join"] == "Line one.\n\nLine two."
