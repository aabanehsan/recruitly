"""Headshot handling: download from Google Drive, match files in a zip, crop and resize."""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import settings
from .cleaning import drive_file_id

MAX_BYTES = 15 * 1024 * 1024
SIZE = 512
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp"}


class HeadshotError(ValueError):
    pass


def process_image(data: bytes) -> bytes:
    """Validate an upload, fix rotation, crop to a square around the face area, resize, return JPEG."""
    if len(data) > MAX_BYTES:
        raise HeadshotError("image is larger than 15 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise HeadshotError("file is not a supported image (use JPG, PNG or WEBP)") from e
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    # Portrait photos: faces sit in the upper part, so bias the crop upward.
    top = int((h - side) * 0.2) if h > w else (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((SIZE, SIZE), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue()


def save_headshot(data: bytes, old_path: str | None = None) -> str:
    """Process and store an image. Returns the filename (relative to the headshot dir)."""
    jpeg = process_image(data)
    settings.ensure_dirs()
    name = f"{uuid.uuid4().hex}.jpg"
    (settings.headshot_dir / name).write_bytes(jpeg)
    if old_path:
        delete_headshot(old_path)
    return name


def delete_headshot(name: str) -> None:
    p = settings.headshot_dir / Path(name).name
    if p.exists():
        p.unlink()


def download_url(url: str, client: httpx.Client | None = None) -> bytes | None:
    """Try to download an image from a Drive share link or a direct image URL.

    Google Form uploads are private to the form owner by default, so this only
    works if the upload folder is shared as "anyone with the link". When it
    fails, use the zip upload instead.
    """
    fid = drive_file_id(url)
    target = f"https://drive.google.com/uc?export=download&id={fid}" if fid else url
    own = client is None
    client = client or httpx.Client(timeout=10, follow_redirects=True)
    try:
        r = client.get(target)
        ctype = r.headers.get("content-type", "")
        if r.status_code == 200 and ctype.startswith("image/") and len(r.content) <= MAX_BYTES:
            return r.content
        return None
    except httpx.HTTPError:
        return None
    finally:
        if own:
            client.close()


# ---------------------------------------------------------------- zip matching


@dataclass
class ZipMatch:
    applicant_id: int
    filename: str
    data: bytes


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _score(fname: str, ap) -> int:
    toks = _tokens(Path(fname).stem)
    flat = re.sub(r"[^a-z0-9]", "", fname.lower())
    score = 0
    if ap.email and ap.email.split("@")[0].lower() in toks:
        score += 3
    if ap.eid and ap.eid.lower() in toks:
        score += 3
    norm = lambda x: re.sub(r"[^a-z0-9]", "", (x or "").lower())  # noqa: E731
    last = norm(ap.last_name)
    firsts = {norm((ap.first_name or "").split(" ")[0]), norm(ap.preferred_name)} - {""}
    last_hit = bool(last) and (last in toks or (len(last) > 3 and last in flat))
    first_hit = any(f in toks for f in firsts)
    if last_hit and first_hit:
        score += 2
    elif last_hit and len(last) > 4:
        score += 1
    return score


def match_zip(zip_bytes: bytes, applicants: Iterable) -> tuple[list[ZipMatch], list[str]]:
    """Match image files in a zip (e.g. the Drive folder a Google Form saves uploads to)
    to applicants by email, EID or name. Returns (matches, unmatched filenames).

    Google Forms names uploads "<original name> - <respondent name>.jpg", which is
    why name matching works without any extra setup.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise HeadshotError("that file isn't a valid .zip") from e
    applicants = list(applicants)
    matches: list[ZipMatch] = []
    unmatched: list[str] = []
    used: set[int] = set()
    for info in zf.infolist():
        name = info.filename
        if info.is_dir() or "__MACOSX" in name or Path(name).name.startswith("."):
            continue
        if Path(name).suffix.lower() not in IMAGE_EXTS:
            continue
        if info.file_size > MAX_BYTES:
            unmatched.append(f"{name} (too large)")
            continue
        scored = sorted(((_score(Path(name).name, a), a.id) for a in applicants), reverse=True)
        best = scored[0] if scored else (0, None)
        runner_up = scored[1][0] if len(scored) > 1 else 0
        if best[0] >= 2 and best[0] > runner_up and best[1] not in used:
            matches.append(ZipMatch(best[1], name, zf.read(info)))
            used.add(best[1])
        else:
            unmatched.append(Path(name).name)
    return matches, unmatched
