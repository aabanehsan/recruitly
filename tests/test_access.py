"""Logins, roles, invites and CSRF on every route."""

import re
from datetime import datetime, timedelta, timezone

from fastapi.routing import APIRoute

from conftest import PASSWORD, csrf_of, login, make_user

# Every route must be listed here, so a new page can't ship without an access decision.
PUBLIC = {
    ("GET", "/login"), ("POST", "/login"), ("GET", "/setup"), ("POST", "/setup"),
    ("GET", "/signup/{token}"), ("POST", "/signup/{token}"), ("POST", "/logout"),
}
ANY_MEMBER = {
    ("GET", "/"), ("GET", "/applicants/{applicant_id}"), ("GET", "/headshots/{name}"),
    ("GET", "/account"), ("POST", "/account/password"),
    ("GET", "/schedule"), ("GET", "/schedule.ics"),
}
ADMIN_ONLY = {
    ("GET", "/applicants/new"), ("POST", "/applicants/new"),
    ("GET", "/applicants/{applicant_id}/edit"), ("POST", "/applicants/{applicant_id}/edit"),
    ("POST", "/applicants/{applicant_id}/status"), ("POST", "/applicants/{applicant_id}/headshot"),
    ("POST", "/applicants/{applicant_id}/headshot/delete"), ("POST", "/applicants/{applicant_id}/delete"),
    ("GET", "/import"), ("POST", "/import"), ("GET", "/import/{token}"), ("POST", "/import/{token}/mapping"),
    ("POST", "/import/{token}/confirm"), ("GET", "/headshots-bulk"), ("POST", "/headshots-bulk"),
    ("GET", "/export.csv"),
    ("GET", "/members"), ("POST", "/members/invite"), ("POST", "/members/invites/{token}/revoke"),
    ("POST", "/members/{user_id}/role"), ("POST", "/members/{user_id}/remove"),
    ("POST", "/schedule/slots"), ("GET", "/schedule/slots/{slot_id}/edit"), ("POST", "/schedule/slots/{slot_id}/edit"),
    ("POST", "/schedule/slots/{slot_id}/delete"), ("POST", "/schedule/slots/{slot_id}/book"),
    ("POST", "/schedule/slots/{slot_id}/unbook"), ("POST", "/applicants/{applicant_id}/book"),
}


def routes(app):
    return {(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in r.methods}


def fill(path, ids):
    return re.sub(r"\{(\w+)\}", lambda m: str(ids[m.group(1)]), path)


def add_applicant(client):
    r = client.post("/applicants/new", data={"first_name": "Jo", "last_name": "Park", "email": "jo@utexas.edu"},
                    follow_redirects=True)
    return int(re.search(r"/applicants/(\d+)/edit", r.text).group(1))


def is_login_redirect(r):
    return r.status_code == 303 and r.headers["location"].startswith("/login")


def test_every_route_has_an_access_rule(app):
    assert routes(app) == PUBLIC | ANY_MEMBER | ADMIN_ONLY


def test_anonymous_is_sent_to_login_everywhere(app, client, anon):
    ids = {"applicant_id": add_applicant(client), "token": "x", "user_id": 1, "name": "x.jpg", "slot_id": 1}
    anon.headers["X-CSRF-Token"] = csrf_of(anon)
    for method, path in sorted(ANY_MEMBER | ADMIN_ONLY):
        r = anon.request(method, fill(path, ids), follow_redirects=False)
        assert is_login_redirect(r), (method, path, r.status_code)
    # deep links remember where you were going
    r = anon.get(f"/applicants/{ids['applicant_id']}", follow_redirects=False)
    assert r.headers["location"] == f"/login?next=%2Fapplicants%2F{ids['applicant_id']}"


def test_members_can_view_but_not_change(app, client, member):
    ids = {"applicant_id": add_applicant(client), "token": "x", "user_id": 1, "name": "x.jpg", "slot_id": 1}
    for method, path in sorted(ADMIN_ONLY):
        r = member.request(method, fill(path, ids), follow_redirects=False)
        assert r.status_code == 403, (method, path, r.status_code)
    assert "Only admins" in member.get("/members").text
    for method, path in sorted(ANY_MEMBER):
        r = member.request(method, fill(path, ids), follow_redirects=False)
        assert r.status_code != 403 and not is_login_redirect(r), (method, path, r.status_code)

    board = member.get("/").text
    assert "Jo Park" in board and "Import responses" not in board and 'href="/members"' not in board
    page = member.get(f"/applicants/{ids['applicant_id']}").text
    assert "Jo Park" in page
    assert "/edit" not in page and "Delete applicant" not in page and 'name="status"' not in page


def test_admin_reaches_every_admin_route(app, client):
    ids = {"applicant_id": add_applicant(client), "token": "x", "user_id": 999, "name": "x.jpg", "slot_id": 999}
    for method, path in sorted(ADMIN_ONLY):
        r = client.request(method, fill(path, ids), follow_redirects=False)
        assert r.status_code != 403 and not is_login_redirect(r), (method, path, r.status_code)
    board = client.get("/").text
    assert "Import responses" in board and 'href="/members"' in board and "Ada Admin" in board


def test_post_without_csrf_token_is_rejected(client):
    ap_id = add_applicant(client)
    good = client.headers.pop("X-CSRF-Token")
    r = client.post(f"/applicants/{ap_id}/status", data={"status": "cut"})
    assert r.status_code == 403 and "form expired" in r.text
    r = client.post(f"/applicants/{ap_id}/status", data={"status": "cut", "csrf_token": "forged"})
    assert r.status_code == 403
    r = client.post(f"/applicants/{ap_id}/status", files={"x": ("a", b"b")}, data={"status": "cut"})
    assert r.status_code == 403
    # the hidden form field works as well as the header
    r = client.post(f"/applicants/{ap_id}/status", data={"status": "cut", "csrf_token": good}, follow_redirects=True)
    assert r.status_code == 200 and "Status set to Cut" in r.text


def test_every_post_form_has_a_csrf_field(client):
    ap_id = add_applicant(client)
    for url in ["/", f"/applicants/{ap_id}", f"/applicants/{ap_id}/edit", "/applicants/new", "/import",
                "/headshots-bulk", "/members", "/account", "/schedule"]:
        html = client.get(url).text
        forms = re.findall(r"<form\b[^>]*method=\"post\"[^>]*>(.*?)</form>", html, flags=re.S)
        assert forms, url  # at least the logout form
        for body in forms:
            assert 'name="csrf_token"' in body, url


def test_first_run_setup_creates_the_admin(anon):
    assert anon.get("/", follow_redirects=False).headers["location"] == "/setup"
    assert anon.get("/login", follow_redirects=False).headers["location"] == "/setup"
    token = csrf_of(anon, "/setup")
    bad = anon.post("/setup", data={"name": "Ada", "email": "ada@x.org", "password": "longenough",
                                    "confirm": "nope", "csrf_token": token})
    assert bad.status_code == 422 and "don&#39;t match" in bad.text
    r = anon.post("/setup", data={"name": "Ada Lovelace", "email": "Ada@X.org", "password": "longenough",
                                  "confirm": "longenough", "csrf_token": token}, follow_redirects=True)
    assert r.status_code == 200 and "You&#39;re the admin" in r.text and "Ada Lovelace" in r.text
    # setup only works once
    assert anon.get("/setup", follow_redirects=False).headers["location"] == "/login"
    r = anon.post("/setup", data={"name": "Eve", "email": "eve@x.org", "password": "longenough",
                                  "confirm": "longenough", "csrf_token": csrf_of(anon, "/account")},
                  follow_redirects=False)
    assert r.headers["location"] == "/login"
    from recruitly.db import session_scope
    from recruitly.models import User
    with session_scope() as s:
        users = s.query(User).all()
        assert [(u.email, u.role) for u in users] == [("ada@x.org", "admin")]


def test_login_logout_and_next(app, client, anon):
    ap_id = add_applicant(client)
    token = csrf_of(anon)
    wrong = anon.post("/login", data={"email": "admin@example.org", "password": "nope", "csrf_token": token})
    unknown = anon.post("/login", data={"email": "who@example.org", "password": "nope", "csrf_token": token})
    assert wrong.status_code == unknown.status_code == 401
    assert "Wrong email or password" in wrong.text and "Wrong email or password" in unknown.text

    r = anon.post("/login", data={"email": " ADMIN@example.org", "password": PASSWORD, "csrf_token": token,
                                  "next": f"/applicants/{ap_id}"}, follow_redirects=False)
    assert r.headers["location"] == f"/applicants/{ap_id}"
    assert anon.get("/").status_code == 200

    token = csrf_of(anon, "/account")
    r = anon.post("/logout", data={"csrf_token": token}, follow_redirects=True)
    assert "logged out" in r.text
    assert is_login_redirect(anon.get("/", follow_redirects=False))

    r = anon.post("/login", data={"email": "admin@example.org", "password": PASSWORD, "csrf_token": csrf_of(anon),
                                  "next": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/"


def test_login_is_throttled_after_repeated_failures(client, anon):
    token = csrf_of(anon)
    for _ in range(5):
        anon.post("/login", data={"email": "admin@example.org", "password": "guess", "csrf_token": token})
    r = anon.post("/login", data={"email": "admin@example.org", "password": PASSWORD, "csrf_token": token})
    assert r.status_code == 429 and "Too many wrong passwords" in r.text


def test_session_cookie_is_signed_and_httponly(client, anon):
    r = anon.post("/login", data={"email": "admin@example.org", "password": PASSWORD, "csrf_token": csrf_of(anon)},
                  follow_redirects=False)
    set_cookie = r.headers["set-cookie"].lower()
    assert "recruitly_session=" in set_cookie and "httponly" in set_cookie and "samesite=lax" in set_cookie
    value = client.cookies["recruitly_session"]
    client.cookies.set("recruitly_session", value[:-4] + "AAAA")  # tampered signature
    assert is_login_redirect(client.get("/", follow_redirects=False))


def test_invite_signup_flow(app, client, anon):
    r = client.post("/members/invite", data={"email": "New.Person@Example.org", "role": "member"}, follow_redirects=True)
    assert "Invite link ready" in r.text
    link = re.search(r'value="http://testserver(/signup/[\w-]+)"', r.text).group(1)

    page = anon.get(link)
    assert page.status_code == 200 and "new.person@example.org" in page.text and "a member" in page.text
    token = csrf_of(anon, link)
    bad = anon.post(link, data={"name": "New Person", "email": "x@y.org", "password": "short", "confirm": "short",
                                "csrf_token": token})
    assert bad.status_code == 422 and "at least 8" in bad.text
    # the invite's email wins even if someone edits the form
    r = anon.post(link, data={"name": "New Person", "email": "attacker@evil.org", "password": "longenough1",
                              "confirm": "longenough1", "csrf_token": token}, follow_redirects=True)
    assert "Welcome to the team, New Person" in r.text
    assert "Import responses" not in r.text  # signed up as a member

    members = client.get("/members").text
    assert "new.person@example.org" in members and "attacker@evil.org" not in members
    assert link not in members  # used invites disappear from the list

    # one time only
    assert anon.get(link).status_code == 410
    assert "already been used" in anon.get(link).text


def test_invite_for_anyone_admin_role_revoke_and_expiry(app, client, anon):
    r = client.post("/members/invite", data={"email": "", "role": "admin"}, follow_redirects=True)
    link = re.search(r'value="http://testserver(/signup/[\w-]+)"', r.text).group(1)
    r = anon.post(link, data={"name": "Second Admin", "email": "two@example.org", "password": "longenough1",
                              "confirm": "longenough1", "csrf_token": csrf_of(anon, link)}, follow_redirects=True)
    assert "Import responses" in r.text

    assert "already has an account" in client.post("/members/invite", data={"email": "two@example.org"},
                                                   follow_redirects=True).text
    r = client.post("/members/invite", data={"email": "later@example.org"}, follow_redirects=True)
    token = re.search(r"/signup/([\w-]+)", r.text).group(1)
    client.post(f"/members/invites/{token}/revoke")
    assert anon.get(f"/signup/{token}").status_code == 410

    r = client.post("/members/invite", data={"email": "slow@example.org"}, follow_redirects=True)
    token = re.search(r"/signup/([\w-]+)", r.text).group(1)
    from recruitly.db import session_scope
    from recruitly.models import Invite
    with session_scope() as s:
        s.get(Invite, token).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    r = anon.get(f"/signup/{token}")
    assert r.status_code == 410 and "expired" in r.text
    assert anon.get("/signup/not-a-real-token").status_code == 410


def test_roles_and_removal(app, client, member):
    from recruitly.db import session_scope
    from recruitly.models import User
    with session_scope() as s:
        admin_id = s.query(User).filter_by(email="admin@example.org").one().id
        member_id = s.query(User).filter_by(email="member@example.org").one().id

    r = client.post(f"/members/{admin_id}/role", data={"role": "member"}, follow_redirects=True)
    assert "can&#39;t change your own role" in r.text
    r = client.post(f"/members/{admin_id}/remove", follow_redirects=True)
    assert "can&#39;t remove yourself" in r.text

    r = client.post(f"/members/{member_id}/role", data={"role": "admin"}, follow_redirects=True)
    assert "Max Member is now an admin" in r.text
    assert member.get("/members").status_code == 200  # takes effect immediately
    client.post(f"/members/{member_id}/role", data={"role": "member"})
    assert member.get("/members").status_code == 403

    r = client.post(f"/members/{member_id}/remove", follow_redirects=True)
    assert "Removed Max Member" in r.text
    assert is_login_redirect(member.get("/", follow_redirects=False))  # their session stops working


def test_password_change_signs_out_other_sessions(app, client):
    from fastapi.testclient import TestClient

    with TestClient(app) as laptop:
        login(laptop, "admin@example.org")
        bad = client.post("/account/password", data={"current": "wrong", "password": "brand-new-pw",
                                                     "confirm": "brand-new-pw"})
        assert bad.status_code == 422 and "not your current password" in bad.text
        r = client.post("/account/password", data={"current": PASSWORD, "password": "brand-new-pw",
                                                   "confirm": "brand-new-pw"}, follow_redirects=True)
        assert "Password changed" in r.text
        assert client.get("/").status_code == 200                       # this browser stays in
        assert is_login_redirect(laptop.get("/", follow_redirects=False))  # the other one is out
        login(laptop, "admin@example.org", "brand-new-pw")


def test_headshots_need_login_and_cant_escape_the_folder(app, client, anon, tmp_path):
    from test_app import jpeg

    ap_id = add_applicant(client)
    r = client.post(f"/applicants/{ap_id}/headshot", files={"file": ("me.jpg", jpeg(), "image/jpeg")},
                    follow_redirects=True)
    src = re.search(r'src="(/headshots/[0-9a-f]+\.jpg)"', r.text).group(1)
    assert client.get(src).headers["content-type"] == "image/jpeg"
    assert is_login_redirect(anon.get(src, follow_redirects=False))
    assert (tmp_path / "secret_key").exists()
    for evil in ["/headshots/..%2Fsecret_key", "/headshots/..%2Frecruitly.db", "/headshots/secret_key"]:
        assert client.get(evil).status_code == 404


def test_demo_accounts(app, capsys):
    from recruitly.cli import create_demo_accounts
    from recruitly.demo import DEMO_ACCOUNTS

    assert create_demo_accounts() == DEMO_ACCOUNTS
    assert create_demo_accounts() == DEMO_ACCOUNTS  # idempotent
    make_user("real@org.edu", role="admin")
    assert create_demo_accounts() == []
    assert "already has real accounts" in capsys.readouterr().out


def test_demo_login_page_shows_credentials(app, anon, monkeypatch):
    from recruitly.cli import create_demo_accounts
    from recruitly.config import settings

    create_demo_accounts()
    assert "demo-admin-2026" not in anon.get("/login").text
    monkeypatch.setattr(settings, "demo", True)
    page = anon.get("/login").text
    assert "admin@demo.recruitly.dev" in page and "demo-member-2026" in page
    login(anon, "member@demo.recruitly.dev", "demo-member-2026")
    assert anon.get("/members").status_code == 403


def test_cli_server_flags_work_after_the_command(monkeypatch):
    from recruitly import cli

    seen = {}
    monkeypatch.setattr(cli, "serve", lambda host, port, open_browser: seen.update(host=host, port=port, ob=open_browser))
    cli.main(["serve", "--no-browser", "--port", "8123"])
    assert seen == {"host": "127.0.0.1", "port": 8123, "ob": False}
    cli.main(["--port", "9000", "serve"])
    assert seen == {"host": "127.0.0.1", "port": 9000, "ob": True}
