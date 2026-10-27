# Roadmap

Recruitly ships in small, working releases. Each milestone below is one release: it must keep every existing feature working, add tests for what it adds, update the README, and pass CI. Check a milestone off (`[x]`) in the same commit that finishes it.

## Done

- [x] **v0.1: Profiles and Google Form import.** Applicant board with search and filters, profile pages with headshots, manual add/edit, import from a CSV or a shared Google Sheet with automatic column mapping, validation and cleanup, a preview before anything is saved, duplicate handling, bulk headshot matching from a Drive zip, CSV export, one-command start (`python3 run.py`).

- [x] **v0.2: Accounts and roles.** Login with email + password (hash with `argon2-cffi` or `passlib[bcrypt]`), signed session cookies. Roles: `admin` (everything, manages members), `member` (view applicants, later: leave notes and scores). First account created on first run becomes admin (setup page). Admin page to invite members via a one-time signup link. Protect every route; add CSRF tokens to all POST forms. Tests for access control on each route.

- [x] **v0.3: Interview scheduling.** Admins create interview slots (date, time, length, location or Zoom link, interviewers). Assign applicants to slots from the profile page or a schedule view; prevent double booking of applicants and interviewers. Schedule page grouped by day. Export a slot list as `.ics` so interviewers can add it to their calendars. Status moves to "Interviewing" automatically when someone is scheduled.

## Next

- [ ] **v0.4: Notes and scoring rubric.** Admins define a rubric (criteria with 1-5 scales and weights). Members leave a score sheet and written notes per applicant per round. A profile shows each member's scores, the weighted average, and notes. Members can't see others' scores until they submit their own, to avoid anchoring. Board can sort by average score.

- [ ] **v0.5: Decisions dashboard and voting.** A decision view that ranks applicants by score, with columns for status, number of scorers and flags. Members vote yes/no/abstain per applicant during a deliberation session that the admin opens and closes. Results page with vote counts. Bulk status changes (select several → set Offered / Cut). Simple charts of the funnel (applied → interviewed → offered → accepted), rendered with inline SVG, no JS framework.

- [ ] **v0.6: Live Google Sheets sync and email templates.** Save the Sheets link in settings and re-sync with one click: new responses are added and changed ones updated, using the existing preview flow. Show "last synced" time. Email templates for interview invites, offers and rejections with placeholders ({first_name}, {slot_time}); generate per-applicant drafts the admin can copy or open as `mailto:` links. No email is sent automatically.

- [ ] **v0.7: Docker, polish and release.** `Dockerfile` and `docker-compose.yml` so `docker compose up` runs everything with the data folder as a volume. Postgres support via `RECRUITLY_DB_URL` (tested in CI with a Postgres service). Dark mode screenshot set in `docs/`. Final README pass with a feature tour, and tag `v1.0.0`.

## Guidelines for every milestone

- Keep it server-rendered with Jinja templates and plain CSS in `static/app.css`. No frontend framework.
- Keep cleaning logic as pure, tested functions in `recruitly/services/`.
- New tables are added through SQLAlchemy models; `init_db()` must still create everything from scratch. If a milestone changes an existing table, add a small migration step in `db.py` that alters SQLite in place so existing data folders keep working.
- `python -m pytest` must pass, and `python -m recruitly demo` must still load and render.
