"""Settings page, saved Google Sheet and one-click re-sync through the import preview."""

import csv
import io
import re
from importlib import resources

import pytest

SAMPLE = resources.files("recruitly").joinpath("sample_data")
SHEET = "https://docs.google.com/spreadsheets/d/1AbcDEFghiJKLmnopQRStuvWXyz0123456789/edit#gid=0"


def db():
    from recruitly.db import session_scope

    return session_scope()


def setting(key):
    from recruitly.sync import get_setting

    with db() as s:
        return get_setting(s, key)


def sheet_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Timestamp", "Email Address", "First Name", "Last Name", "What is your major?", "Phone number",
                "Fun fact"])
    w.writerows(rows)
    return buf.getvalue().encode()


@pytest.fixture()
def sheet(monkeypatch):
    """What the 'Google Sheet' returns; tests change sheet['data'] between syncs."""
    from recruitly import app as app_module, sync

    state = {"data": sheet_csv([
        ["9/2/2026 10:00:00", "ana@utexas.edu", "ana", "alvarez", "Finance", "512-555-0101", "Juggles"],
        ["9/3/2026 10:00:00", "ben@utexas.edu", "Ben", "Brooks", "MIS", "512-555-0102", "Skydives"],
    ]), "calls": 0}

    def fake(url):
        state["calls"] += 1
        return state["data"]

    monkeypatch.setattr(sync, "fetch_sheet", fake)
    monkeypatch.setattr(app_module, "fetch_sheet", fake)
    return state


def save_link(client, url=SHEET):
    return client.post("/settings/sheet", data={"sheet_url": url}, follow_redirects=True)


def sync_now(client, **kw):
    return client.post("/sync", data=kw, follow_redirects=False)


def board_count(client):
    return client.get("/").text.count('class="card"')


def test_settings_saves_and_validates_the_link(client):
    page = client.get("/settings").text
    assert "Google Sheets sync" in page and "Sync now" not in page
    bad = save_link(client, "https://example.com/sheet")
    assert "Not saved" in bad.text and "isn&#39;t a Google Sheets link" in bad.text
    assert setting("sheet_url") is None
    ok = save_link(client)
    assert "Sheets link saved" in ok.text and "Not synced yet" in ok.text and "Sync now" in ok.text
    assert setting("sheet_url") == SHEET
    cleared = save_link(client, "")
    assert "Sheets link removed" in cleared.text and setting("sheet_url") is None


def test_sync_without_a_link(client):
    r = sync_now(client)
    assert r.headers["location"].startswith("/settings?error=")


def test_first_sync_previews_then_records_last_synced(client, sheet):
    save_link(client)
    r = sync_now(client)
    assert r.status_code == 303 and r.headers["location"].startswith("/import/")
    preview = client.get(r.headers["location"]).text
    assert "Review sync" in preview and "your saved Google Sheet" in preview and "Sync 2 applicants" in preview
    assert board_count(client) == 0  # nothing saved before confirming
    assert setting("last_synced_at") is None

    done = client.post(r.headers["location"] + "/confirm")
    assert "Sync complete" in done.text
    assert board_count(client) == 2
    assert setting("last_sync_result") == "2 new, 0 updated, 0 unchanged"
    page = client.get("/settings").text
    assert "Synced just now" in page and "2 new, 0 updated, 0 unchanged" in page
    assert "synced just now" in client.get("/import").text


def test_resync_adds_new_updates_changed_and_hides_unchanged(client, sheet):
    save_link(client)
    client.post(sync_now(client).headers["location"] + "/confirm")
    sheet["data"] = sheet_csv([
        ["9/2/2026 10:00:00", "ana@utexas.edu", "ana", "alvarez", "Finance", "512-555-0101", "Juggles"],
        ["11/3/2026 9:00:00", "ben@utexas.edu", "Ben", "Brooks", "Finance", "512.555.0199", ""],  # edited
        ["11/4/2026 9:00:00", "cal@utexas.edu", "Cal", "Chen", "Accounting", "", ""],  # new
    ])
    r = sync_now(client)
    preview = client.get(r.headers["location"]).text
    assert re.search(r"<b>1</b><span>new profiles", preview)
    assert re.search(r"<b>1</b><span>updates to existing", preview)
    assert re.search(r"<b>1</b><span>unchanged", preview)
    assert "changed: Phone, Major" in preview
    assert "<td>2</td>" not in preview and "Hidden: 1 response with no changes." in preview  # Ana's row
    client.post(r.headers["location"] + "/confirm")

    from recruitly.models import Applicant

    with db() as s:
        ben = s.query(Applicant).filter_by(email="ben@utexas.edu").one()
        assert ben.major == "Finance" and ben.phone == "(512) 555-0199"
        assert ben.fun_fact == "Skydives"  # a blank answer in the sheet doesn't erase it
    assert board_count(client) == 3
    assert setting("last_sync_result") == "1 new, 1 updated, 1 unchanged"


def test_sync_with_nothing_new_just_updates_the_time(client, sheet):
    save_link(client)
    client.post(sync_now(client).headers["location"] + "/confirm")
    from recruitly.sync import LAST_SYNCED, set_setting

    with db() as s:
        set_setting(s, LAST_SYNCED, "2026-01-01T00:00:00+00:00")
        s.commit()
    r = sync_now(client, next="/import")
    assert r.headers["location"].startswith("/import?msg=Already+up+to+date")
    assert setting("last_synced_at") != "2026-01-01T00:00:00+00:00"
    assert "2 checked" in client.get(r.headers["location"]).text


def test_sync_errors_are_shown(client, monkeypatch):
    from recruitly import sync
    from recruitly.services.importer import ImportError_

    def broken(url):
        raise ImportError_("Google wouldn't share that sheet")

    monkeypatch.setattr(sync, "fetch_sheet", broken)
    save_link(client)
    r = client.post("/sync", follow_redirects=True)
    assert "Sync failed: Google wouldn&#39;t share that sheet" in r.text


def test_fixed_column_mapping_is_remembered_for_the_next_sync(client, sheet):
    save_link(client)
    sheet["data"] = sheet_csv([["9/2/2026 10:00:00", "ana@utexas.edu", "Ana", "Alvarez", "Finance", "", "Juggles"]])
    token_url = sync_now(client).headers["location"]
    # the admin decides the fun-fact column shouldn't be saved
    cols = {f"col_{i}": f for i, f in enumerate(["submitted_at", "email", "first_name", "last_name", "major",
                                                  "phone", ""])}
    client.post(token_url + "/mapping", data=cols)
    assert "Review sync" in client.get(token_url).text  # still a sync after remapping
    client.post(token_url + "/confirm")
    assert setting("last_synced_at") is not None

    sheet["data"] = sheet_csv([["9/9/2026 10:00:00", "ana@utexas.edu", "Ana", "Alvarez", "Finance", "", "New fact"]])
    r = sync_now(client)
    assert r.headers["location"].startswith("/import?") or r.headers["location"].startswith("/settings?msg=")
    from recruitly.models import Applicant

    with db() as s:
        assert s.query(Applicant).one().fun_fact is None


def test_changing_the_link_resets_sync_state(client, sheet):
    save_link(client)
    client.post(sync_now(client).headers["location"] + "/confirm")
    assert setting("last_synced_at") and setting("sheet_mapping")
    save_link(client, SHEET.replace("1Abc", "9Xyz"))
    assert setting("last_synced_at") is None and setting("sheet_mapping") is None
    save_link(client, SHEET.replace("1Abc", "9Xyz"))  # saving the same link again keeps it
    assert setting("sheet_url") == SHEET.replace("1Abc", "9Xyz")


def test_import_page_can_save_the_link_for_sync(client, sheet):
    page = client.get("/import").text
    assert 'name="save_link"' in page and "Saved Google Sheet" not in page
    r = client.post("/import", data={"sheet_url": SHEET, "save_link": "1"}, follow_redirects=False)
    assert "Review sync" in client.get(r.headers["location"]).text
    client.post(r.headers["location"] + "/confirm")
    assert setting("sheet_url") == SHEET and setting("last_synced_at")
    page = client.get("/import").text
    assert "Saved Google Sheet" in page and 'action="/sync"' in page
    # a one-off sheet import without the box stays a plain import
    r = client.post("/import", data={"sheet_url": SHEET.replace("1Abc", "2Abc")}, follow_redirects=False)
    assert "Review import" in client.get(r.headers["location"]).text
    assert setting("sheet_url") == SHEET


def test_members_cant_see_or_use_settings(member):
    assert member.get("/settings").status_code == 403
    assert member.post("/sync").status_code == 403
    assert 'href="/settings"' not in member.get("/").text


def test_demo_sync_end_to_end(app, capsys, monkeypatch):
    from fastapi.testclient import TestClient

    from conftest import login
    from recruitly.cli import create_demo_accounts, load_demo, load_demo_sync
    from recruitly.config import settings
    from recruitly.demo import DEMO_SHEET_URL

    monkeypatch.setattr(settings, "demo", True)
    load_demo()
    create_demo_accounts()
    load_demo_sync()
    load_demo_sync()  # idempotent
    assert setting("sheet_url") == DEMO_SHEET_URL
    assert "Saved a demo Google Sheets link" in capsys.readouterr().out

    with TestClient(app) as c:
        login(c, "admin@demo.recruitly.dev", "demo-admin-2026")
        page = c.get("/settings").text
        assert "Synced yesterday" in page, re.findall(r"<b>Synced[^<]*|Not synced yet", page)
        assert "13 new" in page and "this link isn't a real sheet" in page
        r = c.post("/sync", follow_redirects=False)
        preview = c.get(r.headers["location"]).text
        assert re.search(r"<b>2</b><span>new profiles", preview)
        assert re.search(r"<b>2</b><span>updates to existing", preview)
        assert "Liam Ortiz" in preview and "Maya Johnson" in preview
        assert "changed: GPA, Involvement" in preview and "changed: Availability" in preview
        c.post(r.headers["location"] + "/confirm")
        assert c.get("/").text.count('class="card"') == 15
        assert "Synced just now" in c.get("/settings").text
