"""Pages for first-run setup, login, invites, member management and your own account."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_session
from .models import Invite, User
from .services.auth import (
    LoginThrottle, Role, hash_password, invite_expiry, invite_problem, needs_rehash, new_token, normalize_email,
    removal_error, role_change_error, safe_next, validate_account, verify_password, MIN_PASSWORD_LEN,
)
from .schedule import forget_interviewer
from .web import current_user, log_in, redirect, require_admin, session_version, templates

throttle = LoginThrottle()
# Verifying against a throwaway hash for unknown emails keeps response times the same,
# so the login form doesn't reveal which emails have accounts.
_DUMMY_HASH = hash_password(new_token())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _has_users(session: Session) -> bool:
    return session.scalars(select(User.id).limit(1)).first() is not None


def _admin_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(User).where(User.role == Role.ADMIN.value)) or 0


def register_account_routes(app: FastAPI) -> None:
    # ------------------------------------------------------------ first run

    @app.get("/setup", response_class=HTMLResponse)
    def setup_page(request: Request, session: Session = Depends(get_session)):
        if _has_users(session):
            return redirect("/login")
        return templates.TemplateResponse(request, "setup.html", {"values": {}, "errors": {}, "min_len": MIN_PASSWORD_LEN})

    @app.post("/setup", response_class=HTMLResponse)
    def setup_submit(request: Request, name: str = Form(""), email: str = Form(""), password: str = Form(""),
                     confirm: str = Form(""), session: Session = Depends(get_session)):
        if _has_users(session):
            return redirect("/login")
        errors = validate_account(name, email, password, confirm)
        values = {"name": name, "email": email}
        if errors:
            return templates.TemplateResponse(request, "setup.html", {"values": values, "errors": errors,
                                                                      "min_len": MIN_PASSWORD_LEN}, status_code=422)
        user = User(name=name.strip(), email=normalize_email(email), password_hash=hash_password(password),
                    role=Role.ADMIN.value, last_login_at=_now())
        session.add(user)
        session.commit()
        log_in(request, user)
        return redirect("/", msg=f"Welcome, {user.name}. You're the admin. Invite your team from Members.")

    # ------------------------------------------------------------ login / logout

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = "", msg: str = "", session: Session = Depends(get_session)):
        if not _has_users(session):
            return redirect("/setup")
        return templates.TemplateResponse(request, "login.html", {"next": safe_next(next, ""), "email": "",
                                                                  "error": "", "msg": msg})

    @app.post("/login", response_class=HTMLResponse)
    def login_submit(request: Request, email: str = Form(""), password: str = Form(""), next: str = Form(""),
                     session: Session = Depends(get_session)):
        key = normalize_email(email)
        ctx = {"next": safe_next(next, ""), "email": email, "msg": ""}
        wait = throttle.locked_for(key)
        if wait:
            minutes = max(1, round(wait / 60))
            ctx["error"] = f"Too many wrong passwords. Try again in about {minutes} minute{'s' if minutes != 1 else ''}."
            return templates.TemplateResponse(request, "login.html", ctx, status_code=429)
        user = session.scalars(select(User).where(User.email == key)).first()
        ok = verify_password(user.password_hash if user else _DUMMY_HASH, password)
        if not user or not ok:
            throttle.fail(key)
            ctx["error"] = "Wrong email or password."
            return templates.TemplateResponse(request, "login.html", ctx, status_code=401)
        throttle.reset(key)
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = _now()
        session.commit()
        log_in(request, user)
        return redirect(safe_next(next))

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return redirect("/login", msg="You're logged out.")

    # ------------------------------------------------------------ invites / signup

    def _invite_or_error(session: Session, token: str) -> tuple[Invite | None, str | None]:
        inv = session.get(Invite, token)
        if inv is None:
            return None, "This invite link isn't valid. Check that you copied all of it, or ask an admin for a new one."
        return inv, invite_problem(inv.expires_at, inv.used_at)

    @app.get("/signup/{token}", response_class=HTMLResponse)
    def signup_page(request: Request, token: str, session: Session = Depends(get_session)):
        inv, problem = _invite_or_error(session, token)
        if problem:
            return templates.TemplateResponse(request, "signup.html", {"problem": problem}, status_code=410)
        return templates.TemplateResponse(request, "signup.html", {
            "problem": None, "inv": inv, "values": {"email": inv.email or ""}, "errors": {}, "min_len": MIN_PASSWORD_LEN,
        })

    @app.post("/signup/{token}", response_class=HTMLResponse)
    def signup_submit(request: Request, token: str, name: str = Form(""), email: str = Form(""),
                      password: str = Form(""), confirm: str = Form(""), session: Session = Depends(get_session)):
        inv, problem = _invite_or_error(session, token)
        if problem:
            return templates.TemplateResponse(request, "signup.html", {"problem": problem}, status_code=410)
        if inv.email:
            email = inv.email  # invites made for a specific person can't be used with another address
        errors = validate_account(name, email, password, confirm)
        if not errors.get("email") and session.scalars(select(User).where(User.email == normalize_email(email))).first():
            errors["email"] = "There's already an account with this email. Log in instead."
        if errors:
            return templates.TemplateResponse(request, "signup.html", {
                "problem": None, "inv": inv, "values": {"name": name, "email": email}, "errors": errors,
                "min_len": MIN_PASSWORD_LEN,
            }, status_code=422)
        user = User(name=name.strip(), email=normalize_email(email), password_hash=hash_password(password),
                    role=inv.role, last_login_at=_now())
        session.add(user)
        session.flush()
        inv.used_at, inv.used_by_id = _now(), user.id
        session.commit()
        log_in(request, user)
        return redirect("/", msg=f"Welcome to the team, {user.name}.")

    # ------------------------------------------------------------ members (admin)

    @app.get("/members", response_class=HTMLResponse)
    def members_page(request: Request, msg: str = "", error: str = "", new: str = "",
                     admin: User = Depends(require_admin), session: Session = Depends(get_session)):
        users = session.scalars(select(User).order_by(User.role, User.name)).all()
        now = _now()
        invites = [i for i in session.scalars(select(Invite).where(Invite.used_at.is_(None))
                                              .order_by(Invite.created_at.desc()))
                   if not invite_problem(i.expires_at, i.used_at, now)]
        base = str(request.base_url).rstrip("/")
        return templates.TemplateResponse(request, "members.html", {
            "users": users, "invites": invites, "base": base, "msg": msg, "error": error,
            "new_invite": session.get(Invite, new) if new else None,
        })

    @app.post("/members/invite")
    def create_invite(email: str = Form(""), role: str = Form(Role.MEMBER.value),
                      admin: User = Depends(require_admin), session: Session = Depends(get_session)):
        email = normalize_email(email) or None
        if role not in {r.value for r in Role}:
            return redirect("/members", error="Pick a role for the invite.")
        if email and session.scalars(select(User).where(User.email == email)).first():
            return redirect("/members", error=f"{email} already has an account.")
        inv = Invite(token=new_token(24), email=email, role=role, created_by_id=admin.id, expires_at=invite_expiry())
        session.add(inv)
        session.commit()
        return redirect("/members", new=inv.token)

    @app.post("/members/invites/{token}/revoke")
    def revoke_invite(token: str, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
        inv = session.get(Invite, token)
        if inv is not None and inv.used_at is None:
            session.delete(inv)
            session.commit()
        return redirect("/members", msg="Invite link revoked.")

    def _member(session: Session, user_id: int) -> User:
        user = session.get(User, user_id)
        if user is None:
            raise HTTPException(404, "Member not found")
        return user

    @app.post("/members/{user_id}/role")
    def change_role(user_id: int, role: str = Form(...), admin: User = Depends(require_admin),
                    session: Session = Depends(get_session)):
        user = _member(session, user_id)
        err = role_change_error(admin.id, user.id, user.role, role, _admin_count(session))
        if err:
            return redirect("/members", error=err)
        user.role = role
        session.commit()
        return redirect("/members", msg=f"{user.name} is now {'an admin' if role == 'admin' else 'a member'}.")

    @app.post("/members/{user_id}/remove")
    def remove_member(user_id: int, admin: User = Depends(require_admin), session: Session = Depends(get_session)):
        user = _member(session, user_id)
        err = removal_error(admin.id, user.id, user.role, _admin_count(session))
        if err:
            return redirect("/members", error=err)
        name = user.name
        forget_interviewer(session, user.id)
        session.delete(user)
        session.commit()
        return redirect("/members", msg=f"Removed {name}. They can't log in anymore.")

    # ------------------------------------------------------------ your account

    @app.get("/account", response_class=HTMLResponse)
    def account_page(request: Request, msg: str = "", user: User = Depends(current_user)):
        return templates.TemplateResponse(request, "account.html", {"errors": {}, "msg": msg, "min_len": MIN_PASSWORD_LEN})

    @app.post("/account/password", response_class=HTMLResponse)
    def change_password(request: Request, current: str = Form(""), password: str = Form(""), confirm: str = Form(""),
                        user: User = Depends(current_user), session: Session = Depends(get_session)):
        errors = {}
        if not verify_password(user.password_hash, current):
            errors["current"] = "That's not your current password."
        else:
            errors = {k: v for k, v in validate_account(user.name, user.email, password, confirm).items()
                      if k in ("password", "confirm")}
        if errors:
            return templates.TemplateResponse(request, "account.html", {"errors": errors, "msg": "",
                                                                        "min_len": MIN_PASSWORD_LEN}, status_code=422)
        user.password_hash = hash_password(password)
        session.commit()
        request.session["sv"] = session_version(user)  # stay logged in here, sign out everywhere else
        return redirect("/account", msg="Password changed. Other devices have been signed out.")
