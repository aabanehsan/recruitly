import re

import pytest

PASSWORD = "correct-horse-1"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """A fresh app with its own temporary database, headshot folder and secret key."""
    from recruitly import accounts
    from recruitly.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "fetch_headshots", False)
    monkeypatch.setattr(settings, "demo", False)
    monkeypatch.delenv("RECRUITLY_DB_URL", raising=False)
    monkeypatch.delenv("RECRUITLY_SECRET_KEY", raising=False)
    accounts.throttle._failures.clear()
    from recruitly.app import create_app

    return create_app()


def make_user(email, role="member", name=None, password=PASSWORD):
    from recruitly.db import session_scope
    from recruitly.models import User
    from recruitly.services.auth import hash_password

    with session_scope() as s:
        u = User(email=email, name=name or email.split("@")[0].title(), role=role, password_hash=hash_password(password))
        s.add(u)
        s.commit()
        return u.id


def csrf_of(client, url="/login"):
    html = client.get(url).text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def login(client, email, password=PASSWORD):
    token = csrf_of(client)
    r = client.post("/login", data={"email": email, "password": password, "csrf_token": token}, follow_redirects=False)
    assert r.status_code == 303, r.text
    # every later POST in a test sends the (new, post-login) token as a header
    client.headers["X-CSRF-Token"] = csrf_of(client, "/account")
    return client


@pytest.fixture()
def anon(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client(app):
    """Logged in as an admin."""
    from fastapi.testclient import TestClient

    make_user("admin@example.org", role="admin", name="Ada Admin")
    with TestClient(app) as c:
        yield login(c, "admin@example.org")


@pytest.fixture()
def member(app, client):
    """A second browser, logged in as a member (the admin from `client` exists too)."""
    from fastapi.testclient import TestClient

    make_user("member@example.org", role="member", name="Max Member")
    with TestClient(app) as c:
        yield login(c, "member@example.org")
