"""Command line entry point.

    recruitly                 start the web app on http://127.0.0.1:8000
    recruitly demo            load sample applicants (messy form data + headshots), then start
    recruitly import FILE     import a Google Form CSV from the terminal
    recruitly reset-password EMAIL   set a new password for an account (e.g. a locked-out admin)
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


def create_demo_accounts() -> list[tuple[str, str, str, str]]:
    """Create the demo admin and member (if missing) and return their credentials.

    Never adds accounts with well-known passwords to a data folder that already has real users."""
    from sqlalchemy import select

    from .db import init_db, session_scope
    from .demo import DEMO_ACCOUNTS
    from .models import User
    from .services.auth import hash_password

    init_db()
    demo_emails = {a[1] for a in DEMO_ACCOUNTS}
    with session_scope() as s:
        if any(e not in demo_emails for e in s.scalars(select(User.email))):
            print("  Demo accounts skipped: this data folder already has real accounts.")
            return []
        for name, email, password, role in DEMO_ACCOUNTS:
            if not s.scalars(select(User).where(User.email == email)).first():
                s.add(User(name=name, email=email, password_hash=hash_password(password), role=role))
        s.commit()
    return DEMO_ACCOUNTS


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


def load_demo_schedule() -> None:
    """Add a couple of days of interview slots (starting tomorrow) and book some demo applicants."""
    from datetime import timedelta

    from sqlalchemy import select

    from .db import init_db, session_scope
    from .demo import DEMO_BOOKINGS, DEMO_SLOTS
    from .models import Applicant, InterviewSlot, User
    from .services.scheduling import local_now, parse_slot_input, status_after_booking

    init_db()
    with session_scope() as s:
        if s.scalars(select(InterviewSlot.id).limit(1)).first() is not None:
            return
        users = {u.email: u for u in s.scalars(select(User))}
        today = local_now(settings.timezone).date()
        groups = []
        for days, time, minutes, count, location, label, emails in DEMO_SLOTS:
            day = (today + timedelta(days=days)).isoformat()
            parsed, _ = parse_slot_input(day, time, str(minutes), location, label, str(count))
            group = [InterviewSlot(starts_at=t, minutes=minutes, location=parsed.location, label=parsed.label,
                                   interviewers=[users[e] for e in emails if e in users]) for t in parsed.starts]
            s.add_all(group)
            groups.append(group)
        booked = 0
        for email, g, i in DEMO_BOOKINGS:
            ap = s.scalars(select(Applicant).where(Applicant.email == email)).first()
            if ap is not None:
                groups[g][i].applicant = ap
                ap.status = status_after_booking(ap.status)
                booked += 1
        s.commit()
        total = sum(len(g) for g in groups)
        print(f"  Added demo schedule: {total} interview slots over the next 2 days, {booked} applicants booked.")


def print_demo_accounts(accounts) -> None:
    if not accounts:
        return
    print("\n  Demo logins (also shown on the login page):")
    for name, email, password, role in accounts:
        print(f"    {role:<7} {email:<28} password: {password}")


def reset_password(email: str) -> int:
    import getpass

    from sqlalchemy import select

    from .db import init_db, session_scope
    from .models import User
    from .services.auth import hash_password, normalize_email, validate_account

    init_db()
    with session_scope() as s:
        user = s.scalars(select(User).where(User.email == normalize_email(email))).first()
        if user is None:
            print(f"error: no account with email {email}", file=sys.stderr)
            return 2
        pw = getpass.getpass("  New password: ")
        confirm = getpass.getpass("  Confirm: ")
        errors = validate_account(user.name, user.email, pw, confirm)
        if errors:
            print(f"error: {' '.join(errors.values())}", file=sys.stderr)
            return 2
        user.password_hash = hash_password(pw)  # also signs them out everywhere
        s.commit()
    print(f"  Password changed for {user.name} ({user.role}).")
    return 0


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
    # server options work before or after the command: `recruitly demo --port 8123` or `recruitly --port 8123 demo`
    server = argparse.ArgumentParser(add_help=False)
    server.add_argument("--host", default=argparse.SUPPRESS)
    server.add_argument("--port", type=int, default=argparse.SUPPRESS)
    server.add_argument("--no-browser", action="store_true", default=argparse.SUPPRESS, help="don't open a browser tab")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("serve", parents=[server], help="start the web app (default)")
    sub.add_parser("demo", parents=[server], help="load sample data, then start the web app")
    imp = sub.add_parser("import", help="import a Google Form responses CSV")
    imp.add_argument("file")
    imp.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    rp = sub.add_parser("reset-password", help="set a new password for an account")
    rp.add_argument("email")
    args = p.parse_args(argv)

    if args.cmd == "import":
        return import_file(args.file, args.yes)
    if args.cmd == "reset-password":
        return reset_password(args.email)
    if args.cmd == "demo":
        load_demo()
        accounts = create_demo_accounts()
        if accounts:
            load_demo_schedule()
        print_demo_accounts(accounts)
        settings.demo = bool(accounts)
    serve(args.host, args.port, not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
