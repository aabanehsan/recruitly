"""Shared web plumbing: templates, the logged-in user, CSRF checks and redirects."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import __version__
from .config import settings
from .db import get_session
from .demo import DEMO_ACCOUNTS
from .models import Status, User
from .services.auth import Role, new_token, tokens_match

HERE = Path(__file__).parent
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def csrf_token(request: Request) -> str:
    """The session's CSRF token, created on first use."""
    tok = request.session.get("csrf")
    if not tok:
        tok = request.session["csrf"] = new_token()
    return tok


def _template_context(request: Request) -> dict:
    return {
        "me": getattr(request.state, "user", None),
        "csrf_field": Markup(f'<input type="hidden" name="{CSRF_FIELD}" value="{csrf_token(request)}">'),
    }


templates = Jinja2Templates(directory=HERE / "templates", context_processors=[_template_context])
templates.env.globals.update(settings=settings, Status=Status, Role=Role, version=__version__,
                             demo_accounts=DEMO_ACCOUNTS)
templates.env.filters["combine"] = lambda a, b: {**a, **b}
templates.env.filters["shortdate"] = lambda d: f"{d:%b} {d.day}" if d else ""
templates.env.filters["longdate"] = lambda d: (f"{d:%b} {d.day}, {d.year} {d.hour % 12 or 12}:{d:%M} "
                                               f"{'AM' if d.hour < 12 else 'PM'}") if d else ""


def redirect(url: str, **params: str) -> RedirectResponse:
    q = {k: v for k, v in params.items() if v}
    return RedirectResponse(url + (("?" + urlencode(q)) if q else ""), status_code=303)


# ------------------------------------------------------------------ sessions

def session_version(user: User) -> str:
    """Changes whenever the user's password changes, which signs out their other sessions."""
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:16]


def log_in(request: Request, user: User) -> None:
    request.session.clear()  # fresh session (and CSRF token) on every login
    request.session.update({"uid": user.id, "sv": session_version(user), "csrf": new_token()})


class LoginRequired(Exception):
    """Raised by current_user; the app turns it into a redirect to /login (or /setup)."""

    def __init__(self, url: str):
        self.url = url


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    uid = request.session.get("uid")
    user = session.get(User, uid) if isinstance(uid, int) else None
    if user is None or request.session.get("sv") != session_version(user):
        if uid is not None:
            request.session.pop("uid", None)
            request.session.pop("sv", None)
        if session.scalars(select(User.id).limit(1)).first() is None:
            raise LoginRequired("/setup")
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise LoginRequired("/login" if request.method != "GET" or target == "/"
                            else "/login?" + urlencode({"next": target}))
    request.state.user = user
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Only admins can do that. Ask an admin on your team if you need access.")
    return user


async def csrf_protect(request: Request) -> None:
    """App-wide dependency: every POST must carry the session's CSRF token."""
    if request.method not in UNSAFE_METHODS:
        return
    given = request.headers.get(CSRF_HEADER)
    if not given:
        ctype = request.headers.get("content-type", "")
        if ctype.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            given = str((await request.form()).get(CSRF_FIELD) or "")
    if not tokens_match(request.session.get("csrf"), given):
        raise HTTPException(403, "This form expired or came from somewhere else. Go back, reload the page and try again.")
