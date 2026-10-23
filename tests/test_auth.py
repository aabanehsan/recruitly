"""Pure account rules in recruitly.services.auth."""

from datetime import datetime, timedelta, timezone

import pytest

from recruitly.services.auth import (
    LoginThrottle, hash_password, invite_expiry, invite_problem, normalize_email, removal_error, role_change_error,
    safe_next, tokens_match, validate_account, verify_password,
)

NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


def test_password_hash_roundtrip():
    h = hash_password("hunter2hunter2")
    assert h.startswith("$argon2") and "hunter2" not in h
    assert verify_password(h, "hunter2hunter2")
    assert not verify_password(h, "hunter2hunter3")
    assert not verify_password("not-a-hash", "anything")
    assert hash_password("same-password") != hash_password("same-password")  # salted


def test_validate_account():
    assert validate_account("Ada", "Ada@Example.org", "longenough", "longenough") == {}
    errs = validate_account("  ", "nope", "short", "short")
    assert set(errs) == {"name", "email", "password"}
    assert validate_account("Ada", "a@b.co", "longenough", "different")["confirm"]
    assert validate_account("Ada", "a@b.co", "          ", "          ")["password"]
    assert normalize_email("  Ada@Example.ORG ") == "ada@example.org"


def test_role_change_rules():
    assert role_change_error(1, 2, "member", "admin", admin_count=1) is None
    assert role_change_error(1, 2, "admin", "member", admin_count=2) is None
    assert "own role" in role_change_error(1, 1, "admin", "member", admin_count=3)
    assert "at least one admin" in role_change_error(1, 2, "admin", "member", admin_count=1)
    assert role_change_error(1, 2, "member", "owner", admin_count=1) == "Unknown role."
    assert role_change_error(1, 1, "admin", "admin", admin_count=1) is None  # no-op is fine


def test_removal_rules():
    assert removal_error(1, 2, "member", admin_count=1) is None
    assert "yourself" in removal_error(1, 1, "admin", admin_count=5)
    assert "at least one admin" in removal_error(1, 2, "admin", admin_count=1)
    assert removal_error(1, 2, "admin", admin_count=2) is None


def test_invites_expire_and_are_single_use():
    exp = invite_expiry(NOW)
    assert exp - NOW == timedelta(days=7)
    assert invite_problem(exp, None, NOW) is None
    assert "expired" in invite_problem(exp, None, NOW + timedelta(days=8))
    assert "already been used" in invite_problem(exp, NOW, NOW)
    naive = exp.replace(tzinfo=None)  # how SQLite returns it
    assert invite_problem(naive, None, NOW) is None


@pytest.mark.parametrize("url,out", [
    ("/applicants/3", "/applicants/3"), ("/?q=lee&status=applied", "/?q=lee&status=applied"),
    ("", "/"), (None, "/"), ("//evil.com", "/"), ("https://evil.com", "/"), ("/\\evil.com", "/"), ("evil", "/"),
])
def test_safe_next(url, out):
    assert safe_next(url) == out


def test_tokens_match():
    assert tokens_match("abc", "abc")
    assert not tokens_match("abc", "abd")
    assert not tokens_match(None, None) and not tokens_match("", "") and not tokens_match("abc", None)


def test_login_throttle():
    t = LoginThrottle(max_failures=3, lockout_seconds=60)
    for i in range(2):
        t.fail("a@b.co", now=100 + i)
    assert t.locked_for("a@b.co", now=103) == 0
    t.fail("a@b.co", now=103)
    assert 55 <= t.locked_for("a@b.co", now=104) <= 60
    assert t.locked_for("other@b.co", now=104) == 0
    assert t.locked_for("a@b.co", now=170) == 0  # window passed
    t.fail("a@b.co", now=200); t.fail("a@b.co", now=201); t.fail("a@b.co", now=202)
    t.reset("a@b.co")
    assert t.locked_for("a@b.co", now=203) == 0
