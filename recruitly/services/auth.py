"""Accounts, roles, CSRF tokens and invite links.

Everything here is a plain function or small class with no web or database
dependencies, so the rules are easy to unit test.
"""

from __future__ import annotations

import hmac
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class Role(str, Enum):
    ADMIN = "admin"    # everything, including managing members
    MEMBER = "member"  # view applicants (notes and scores arrive in a later release)

    @property
    def label(self) -> str:
        return self.value.title()


MIN_PASSWORD_LEN = 8
INVITE_DAYS = 7
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_hasher = PasswordHasher()


# ------------------------------------------------------------------ passwords

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# ------------------------------------------------------------------ validation

def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_account(name: str, email: str, password: str, confirm: str) -> dict[str, str]:
    """Return {field: error message} for a new account form. Empty means valid."""
    errors: dict[str, str] = {}
    if not (name or "").strip():
        errors["name"] = "Enter your name."
    elif len(name.strip()) > 80:
        errors["name"] = "Keep it under 80 characters."
    if not _EMAIL_RE.match(normalize_email(email)):
        errors["email"] = "Enter a valid email address."
    if len(password or "") < MIN_PASSWORD_LEN:
        errors["password"] = f"Use at least {MIN_PASSWORD_LEN} characters."
    elif not password.strip():
        errors["password"] = "Password can't be only spaces."
    elif password != confirm:
        errors["confirm"] = "Passwords don't match."
    return errors


# ------------------------------------------------------------------ roles

def is_admin(role: str | None) -> bool:
    return role == Role.ADMIN.value


def role_change_error(actor_id: int, target_id: int, target_role: str, new_role: str, admin_count: int) -> str | None:
    """Why a role change isn't allowed, or None if it is."""
    if new_role not in {r.value for r in Role}:
        return "Unknown role."
    if actor_id == target_id and new_role != target_role:
        return "You can't change your own role. Ask another admin."
    if target_role == Role.ADMIN.value and new_role != Role.ADMIN.value and admin_count <= 1:
        return "There has to be at least one admin."
    return None


def removal_error(actor_id: int, target_id: int, target_role: str, admin_count: int) -> str | None:
    """Why a member can't be removed, or None if they can."""
    if actor_id == target_id:
        return "You can't remove yourself."
    if target_role == Role.ADMIN.value and admin_count <= 1:
        return "There has to be at least one admin."
    return None


# ------------------------------------------------------------------ tokens

def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def tokens_match(expected: str | None, given: str | None) -> bool:
    if not expected or not given:
        return False
    return hmac.compare_digest(expected.encode(), given.encode())


def invite_expiry(now: datetime | None = None, days: int = INVITE_DAYS) -> datetime:
    return (now or datetime.now(timezone.utc)) + timedelta(days=days)


def _aware(d: datetime) -> datetime:
    # SQLite hands datetimes back without a timezone; everything we store is UTC.
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def invite_problem(expires_at: datetime, used_at: datetime | None, now: datetime | None = None) -> str | None:
    """Why an invite link can't be used, or None if it's still good."""
    if used_at is not None:
        return "This invite link has already been used. Ask an admin for a new one."
    if _aware(expires_at) <= (now or datetime.now(timezone.utc)):
        return "This invite link has expired. Ask an admin for a new one."
    return None


def safe_next(url: str | None, default: str = "/") -> str:
    """Only allow redirects back into this app (no //evil.com or https://...)."""
    if not url or not url.startswith("/") or url.startswith("//") or "\\" in url:
        return default
    return url


# ------------------------------------------------------------------ login throttling

@dataclass
class LoginThrottle:
    """Lock an email out for a while after too many wrong passwords. In memory, per process."""

    max_failures: int = 5
    lockout_seconds: int = 300
    _failures: dict[str, list[float]] = field(default_factory=dict)

    def _recent(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._failures.get(key, []) if now - t < self.lockout_seconds]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def locked_for(self, key: str, now: float | None = None) -> int:
        """Seconds left on a lockout, or 0 if logins are allowed."""
        now = time.monotonic() if now is None else now
        recent = self._recent(key, now)
        if len(recent) < self.max_failures:
            return 0
        return max(1, int(self.lockout_seconds - (now - recent[-self.max_failures])))

    def fail(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._failures.setdefault(key, []).append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
