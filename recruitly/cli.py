"""Command line entry point.

    recruitly                 start the web app on http://127.0.0.1:8000
    recruitly demo            load sample applicants (messy form data + headshots), then start
    recruitly import FILE     import a Google Form CSV from the terminal
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from importlib import resources
from threading import Timer

from . import __version__
from .config import settings


def serve(host: str, port: int, open_browser: bool) -> None:
    import uvicorn

    url = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}"
    print(f"\n  Recruitly v{__version__} running at {url}  (Ctrl+C to stop)\n  Data folder: {settings.data_dir}\n")
    if open_browser:
        Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run("recruitly.app:create_app", factory=True, host=host, port=port, log_level="warning")


def load_demo() -> None:
    from sqlalchemy import select

    from .db import init_db, session_scope
    from .models import Applicant
    from .services.headshots import match_zip, save_headshot
    from .services.importer import apply_preview, build_preview, read_csv

    init_db()
    sample = resources.files("recruitly").joinpath("sample_data")
    with session_scope() as s:
        if s.scalars(select(Applicant)).first():
            print("  Demo skipped: there are already applicants in the database.")
            return
        headers, rows = read_csv(sample.joinpath("form_responses.csv").read_bytes())
        pv = build_preview(s, headers, rows, "sample form_responses.csv")
        summary = apply_preview(s, pv, fetch_headshots=False)
        matches, _ = match_zip(sample.joinpath("headshots.zip").read_bytes(), s.scalars(select(Applicant)).all())
        for m in matches:
            ap = s.get(Applicant, m.applicant_id)
            ap.headshot_path = save_headshot(m.data)
        s.commit()
        print(f"  Loaded demo: {summary.created} applicants, {len(matches)} headshots, "
              f"{summary.skipped} rows skipped (bad data on purpose).")


def import_file(path: str, yes: bool) -> int:
    from .db import init_db, session_scope
    from .services.importer import ImportError_, apply_preview, build_preview, read_csv

    init_db()
    with open(path, "rb") as fh:
        data = fh.read()
    with session_scope() as s:
        try:
            headers, rows = read_csv(data)
            pv = build_preview(s, headers, rows, path, email_domain=settings.email_domain)
        except ImportError_ as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        for p in pv.problems:
            print(f"error: {p}", file=sys.stderr)
        if pv.problems:
            return 2
        c = pv.counts
        print(f"  {len(pv.rows)} rows: {c['create']} new, {c['update']} updates, {c['skip']} skipped, "
              f"{c['duplicate']} duplicates, {c['fixed']} values cleaned, {c['warning']} warnings")
        for r in pv.rows:
            if r.action in ("skip", "duplicate"):
                print(f"    row {r.row_num}: {r.action} ({r.reason})")
        if not yes and input("  Import? [y/N] ").strip().lower() != "y":
            print("  Cancelled.")
            return 1
        summary = apply_preview(s, pv, fetch_headshots=settings.fetch_headshots)
        print(f"  Done: {summary.created} created, {summary.updated} updated, {summary.headshots_saved} headshots.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="recruitly", description="Applicant tracking for student org recruitment.")
    p.add_argument("--version", action="version", version=f"recruitly {__version__}")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="start the web app (default)")
    sub.add_parser("demo", help="load sample data, then start the web app")
    imp = sub.add_parser("import", help="import a Google Form responses CSV")
    imp.add_argument("file")
    imp.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    args = p.parse_args(argv)

    if args.cmd == "import":
        return import_file(args.file, args.yes)
    if args.cmd == "demo":
        load_demo()
    serve(args.host, args.port, not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
