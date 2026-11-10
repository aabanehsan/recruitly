"""Database URLs (SQLite and Postgres), length limits that Postgres enforces, and the health check."""

import pytest

from recruitly.services.database import DatabaseURLError, engine_options, normalize_db_url, redact_db_url


@pytest.mark.parametrize("given, expected", [
    ("postgres://u:p@db:5432/recruitly", "postgresql+psycopg://u:p@db:5432/recruitly"),
    ("postgresql://u:p@db/recruitly", "postgresql+psycopg://u:p@db/recruitly"),
    ("  postgresql+psycopg://u@localhost/r  ", "postgresql+psycopg://u@localhost/r"),
    ("POSTGRES://u@h/r", "postgresql+psycopg://u@h/r"),
    ("postgresql+psycopg2://u@h/r", "postgresql+psycopg2://u@h/r"),
    ("sqlite:///data/recruitly.db", "sqlite:///data/recruitly.db"),
    ("sqlite://", "sqlite://"),
])
def test_normalize_db_url(given, expected):
    assert normalize_db_url(given) == expected


@pytest.mark.parametrize("bad", ["", "   ", "mysql://u@h/r", "just-a-path.db", "mongodb://h/r"])
def test_unsupported_urls_are_explained(bad):
    with pytest.raises(DatabaseURLError):
        normalize_db_url(bad)


def test_engine_options():
    lite = engine_options("sqlite:///x.db")
    assert lite.kind == "sqlite" and lite.connect_args == {"check_same_thread": False} and not lite.pool_pre_ping
    pg = engine_options("postgres://u:p@db/recruitly")
    assert pg.kind == "postgresql" and pg.url.startswith("postgresql+psycopg://")
    assert "timezone=UTC" in pg.connect_args["options"] and pg.pool_pre_ping


@pytest.mark.parametrize("given, expected", [
    ("postgresql://recruitly:s3cret@db:5432/recruitly", "postgresql://recruitly:***@db:5432/recruitly"),
    ("postgresql://p%40ss:x:y@db/r", "postgresql://p%40ss:***@db/r"),
    ("postgresql://recruitly@db/recruitly", "postgresql://recruitly@db/recruitly"),
    ("sqlite:///data/recruitly.db", "sqlite:///data/recruitly.db"),
])
def test_redact_db_url(given, expected):
    assert redact_db_url(given) == expected


def test_long_text_is_trimmed_to_fit_its_column(client):
    """SQLite would store anything; Postgres rejects values longer than the column. Either way the save works."""
    from recruitly.db import session_scope
    from recruitly.models import Applicant

    with session_scope() as s:
        ap = Applicant(first_name="Jo", last_name="Park", email="jo@utexas.edu", hometown="Austin " * 40,
                       classification="x" * 100)
        s.add(ap)
        s.commit()
        ap_id = ap.id
    with session_scope() as s:
        ap = s.get(Applicant, ap_id)
        assert len(ap.hometown) == 120 and ap.hometown.startswith("Austin Austin")
        assert len(ap.classification) == 30
        ap.hometown = "Round Rock, TX " * 20  # updates are trimmed too
        s.commit()
    with session_scope() as s:
        assert len(s.get(Applicant, ap_id).hometown) == 120


def test_form_with_overlong_answers_still_saves(client):
    r = client.post("/applicants/new", data={"first_name": "Jo", "last_name": "Park", "email": "jo@utexas.edu",
                                             "hometown": "Houston " * 30, "minor": "Business " * 30},
                    follow_redirects=True)
    assert r.status_code == 200 and "Jo Park" in r.text


def test_healthz_is_public_and_says_nothing_private(anon):
    r = anon.get("/healthz")
    assert r.status_code == 200
    from recruitly import __version__
    assert r.json() == {"status": "ok", "version": __version__}


def test_healthz_reports_database_trouble(anon, monkeypatch):
    import recruitly.app

    def broken():
        raise RuntimeError("database is down")

    monkeypatch.setattr(recruitly.app, "session_scope", broken)
    r = anon.get("/healthz")
    assert r.status_code == 503 and r.json()["status"] == "error"
