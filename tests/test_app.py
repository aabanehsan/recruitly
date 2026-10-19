import io
import re
from importlib import resources

from PIL import Image

SAMPLE = resources.files("recruitly").joinpath("sample_data")


def jpeg(color=(200, 80, 60), size=(300, 400)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def import_sample(client):
    data = SAMPLE.joinpath("form_responses.csv").read_bytes()
    r = client.post("/import", files={"file": ("responses.csv", data, "text/csv")}, follow_redirects=False)
    assert r.status_code == 303
    token_url = r.headers["location"]
    preview = client.get(token_url)
    assert preview.status_code == 200
    return token_url, preview.text


def test_empty_board(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "No applicants yet" in r.text


def test_import_preview_then_confirm(client):
    token_url, html = import_sample(client)
    assert "Review import" in html
    assert "Computer Science" in html          # "comp sci" cleaned
    assert "duplicate" in html                 # Jordan submitted twice
    assert "email: missing" in html            # Chloe has no email
    # nothing saved yet
    assert "No applicants yet" in client.get("/").text

    done = client.post(token_url + "/confirm")
    assert done.status_code == 200
    assert "Import complete" in done.text
    board = client.get("/").text
    assert "Jordan Lee" in board and "Pri Raman" in board  # preferred name shown
    assert board.count('class="card"') == 10

    # re-importing the same file updates instead of duplicating
    token_url, html = import_sample(client)
    assert re.search(r"<b>10</b><span>updates to existing", html)
    client.post(token_url + "/confirm")
    assert client.get("/").text.count('class="card"') == 10


def test_profile_shows_cleaned_values_and_notes(client):
    token_url, _ = import_sample(client)
    client.post(token_url + "/confirm")
    board = client.get("/?q=oneil").text
    ap_id = re.search(r'href="/applicants/(\d+)"', board).group(1)
    page = client.get(f"/applicants/{ap_id}").text
    assert "Marcus O&#39;Neil" in page or "Marcus O'Neil" in page
    assert "marcus.oneil@utexas.edu" in page
    assert "(214) 555-0178" in page
    assert "mo5521" in page
    assert "Cleaned on import" in page


def test_remap_columns(client):
    token_url, _ = import_sample(client)
    html = client.get(token_url).text
    # Ignore the email column → preview must refuse to import
    n_cols = html.count('name="col_')
    form = {f"col_{i}": "" for i in range(n_cols)}
    r = client.post(token_url + "/mapping", data=form, follow_redirects=True)
    assert "No column is mapped to Email" in r.text


def test_manual_create_edit_status_delete(client):
    r = client.post("/applicants/new", data={"first_name": "sam", "last_name": "rivera", "email": "Sam@UTexas.edu",
                                            "major": "econ", "phone": "5125550100", "gpa": "3.5"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert "Sam Rivera" in r.text and "Economics" in r.text and "(512) 555-0100" in r.text
    ap_id = re.search(r"/applicants/(\d+)/edit", r.text).group(1)

    # duplicate email is rejected
    dup = client.post("/applicants/new", data={"first_name": "X", "email": "sam@utexas.edu"})
    assert dup.status_code == 422 and "already used by" in dup.text

    # validation error on edit
    bad = client.post(f"/applicants/{ap_id}/edit", data={"first_name": "", "email": "nope"})
    assert bad.status_code == 422

    r = client.post(f"/applicants/{ap_id}/status", data={"status": "interviewing"}, follow_redirects=True)
    assert "Interviewing" in r.text
    assert "Interviewing" in client.get("/?status=interviewing").text

    r = client.post(f"/applicants/{ap_id}/delete", follow_redirects=True)
    assert "Deleted Sam Rivera" in r.text
    assert client.get(f"/applicants/{ap_id}").status_code == 404


def test_headshot_upload_crops_square(client, tmp_path):
    r = client.post("/applicants/new", data={"first_name": "Pat", "email": "pat@utexas.edu"}, follow_redirects=True)
    ap_id = re.search(r"/applicants/(\d+)/edit", r.text).group(1)
    r = client.post(f"/applicants/{ap_id}/headshot", files={"file": ("me.jpg", jpeg(), "image/jpeg")},
                    follow_redirects=True)
    assert "Headshot updated" in r.text
    src = re.search(r'src="(/headshots/[0-9a-f]+\.jpg)"', r.text).group(1)
    img = Image.open(io.BytesIO(client.get(src).content))
    assert img.size == (512, 512)

    bad = client.post(f"/applicants/{ap_id}/headshot", files={"file": ("x.jpg", b"not an image", "image/jpeg")},
                      follow_redirects=True)
    assert "not a supported image" in bad.text


def test_bulk_headshots_zip(client):
    token_url, _ = import_sample(client)
    client.post(token_url + "/confirm")
    r = client.post("/headshots-bulk", files={"file": ("h.zip", SAMPLE.joinpath("headshots.zip").read_bytes(),
                                                       "application/zip")})
    assert r.status_code == 200
    assert re.search(r"<b>8</b><span>headshots saved", r.text)  # Marcus's apostrophe included
    assert "Someone Else" in r.text                              # stranger's photo not matched

    r = client.post("/headshots-bulk", files={"file": ("h.zip", b"garbage", "application/zip")})
    assert "a valid .zip" in r.text


def test_export_csv(client):
    token_url, _ = import_sample(client)
    client.post(token_url + "/confirm")
    r = client.get("/export.csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0].startswith("id,first_name,last_name")
    assert len(r.text.strip().splitlines()) == 11


def test_sheet_link_conversion():
    from recruitly.services.importer import sheet_csv_url

    url = "https://docs.google.com/spreadsheets/d/1AbC_dEf-123/edit#gid=456"
    assert sheet_csv_url(url) == "https://docs.google.com/spreadsheets/d/1AbC_dEf-123/export?format=csv&gid=456"
