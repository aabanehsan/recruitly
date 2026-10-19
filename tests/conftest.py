import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A fresh app with its own temporary database and headshot folder."""
    from fastapi.testclient import TestClient

    from recruitly.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "fetch_headshots", False)
    monkeypatch.delenv("RECRUITLY_DB_URL", raising=False)
    from recruitly.app import create_app

    with TestClient(create_app()) as c:
        yield c
