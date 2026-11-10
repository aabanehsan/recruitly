# Recruitly

Applicant tracking for student org recruitment. Point it at your Google Form responses, and it builds a clean profile for every applicant, with their headshot, major, year, GPA, links and short answers, in one place your whole exec team can use.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/board-dark.png">
  <img alt="Applicant board" src="docs/screenshots/board-light.png">
</picture>

Runs anywhere Python 3.10+ runs, or with `docker compose up`. SQLite out of the box, Postgres when you want it. Light and dark mode, and it works on phones.

## Why

Most orgs run recruitment out of a Google Form and a messy spreadsheet. Names come in as `jOHN`, majors as `cs`, `comp sci` and `Computer Science`, phone numbers in five formats, and someone always submits twice. Headshots end up in a Drive folder that nobody can match to the right row. Recruitly fixes all of that on import and gives you a board you can actually run rush from.

## Tour

A recruitment cycle in Recruitly, start to finish. Screenshots follow your system's light or dark setting; every screen has both (see [`docs/screenshots/`](docs/screenshots/)).

**1. Import the form.** Upload the Google Form CSV or paste the Sheets link. Recruitly maps the questions to profile fields, cleans every answer (names, majors, emails, phone numbers, GPAs, grad terms), shows you exactly what it changed, and only saves when you confirm. Save the link and **Sync now** picks up new and edited responses later.

**2. Everyone gets a profile.** Headshot, major, year, GPA, links and short answers on one page, with interviews, scores, votes and email drafts alongside.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/profile-dark.png">
  <img alt="Applicant profile with scores and notes" src="docs/screenshots/profile-light.png">
</picture>

**3. Schedule interviews.** Add back-to-back slots, book applicants from the schedule or their profile, and export `.ics` files for interviewers' calendars. Double booking is blocked.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/schedule-dark.png">
  <img alt="Interview schedule grouped by day" src="docs/screenshots/schedule-light.png">
</picture>

**4. Score against a rubric.** Weighted 1-5 criteria per round, plus notes. Nobody sees anyone else's scores until they've submitted their own, so first impressions don't anchor the room.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/scoring-dark.png">
  <img alt="Score sheet" src="docs/screenshots/scoring-light.png">
</picture>

**5. Decide together.** Rank by score, spot split or missing scores, open a yes/no/abstain vote for the debrief, then move people to *Offered* or *Cut* in bulk. A funnel chart shows how the cycle went.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/decisions-dark.png">
  <img alt="Decisions dashboard with funnel and voting" src="docs/screenshots/decisions-light.png">
</picture>

**6. Write the emails.** Invite, offer and rejection templates with placeholders turn into a ready-to-send draft per applicant: open it in your email app or copy it. Recruitly never sends anything itself.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/emails-dark.png">
  <img alt="Per-applicant email drafts" src="docs/screenshots/emails-light.png">
</picture>

On a phone:

<p>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/phone-board-dark.png">
  <img alt="Board on a phone" src="docs/screenshots/phone-board-light.png" width="260">
</picture>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/phone-profile-dark.png">
  <img alt="Profile on a phone" src="docs/screenshots/phone-profile-light.png" width="260">
</picture>
</p>

## Features (v1.0)

- **Docker and Postgres.** `docker compose up` runs the whole app with your data in `./data`; add one override file to run it on Postgres instead of SQLite. Any Postgres URL works through `RECRUITLY_DB_URL`, the full test suite runs against Postgres in CI, and `/healthz` reports whether the app and its database are up.


- **Live Google Sheets sync.** Save your responses sheet's link once (in **Settings**, or by ticking *Save this link* on the Import page), then hit **Sync now** whenever new responses come in.
  - Sync runs through the same preview as a normal import: new responses are added, people who edited their answers are updated (the preview says exactly which fields changed), and unchanged rows are left alone and hidden from the list. Nothing is saved until you confirm.
  - Blank answers never erase data you already have, and if you fix a column mapping during a sync, the next sync remembers it.
  - Settings and the Import page show when the sheet was last synced and what changed.

- **Email templates.** Starter templates for **interview invites**, **offers** and **rejections** (edit them or add your own on **Emails**), with placeholders like `{first_name}`, `{slot_time}`, `{slot_location}` and `{sender_name}`.
  - **Make drafts** fills in a template for everyone it's meant for: invites go to people booked for an upcoming interview, offers to *Offered*, rejections to *Cut*, or pick any status. Every applicant's profile also links to a draft of each template.
  - Each draft has **Open in email app** (a `mailto:` link with the subject and body filled in) and copy buttons, plus *Copy all addresses* for a BCC. Drafts with a placeholder that can't be filled (say, an invite for someone without a slot) are flagged.
  - Recruitly **never sends email by itself**.

- **Decisions dashboard and voting.** The **Decisions** page ranks every applicant by average score, with their status, how many people scored them, and flags worth a second look: *Not scored* (interviewed but nobody submitted), *1 scorer*, *Split* (scorers more than 1.5 points apart) and *Draft pending*.
  - **Deliberations:** an admin opens a voting session (say, "First-round debrief"), everyone votes **yes / no / abstain** per applicant from the Decisions page or the profile, and the admin closes it. Click your vote again to take it back. Cut and declined applicants can't be voted on.
  - **No voting with the room:** while a session is open, members only see their own votes and how many people have voted. Admins see the live tally. When the session closes, everyone sees the counts on its **results page**, ranked by net support with *Majority yes / no / Tied*. Votes are only ever shown as counts, never per person.
  - **Bulk status changes:** admins tick several applicants (on Decisions or a results page) and set them all to *Offered*, *Cut* or any other status at once.
  - **Charts:** a recruitment funnel (applied → interviewed → offered → accepted, with the conversion at each step) and a status mix bar, drawn as inline SVG with no JavaScript library.
  - The anchoring rule from scoring still holds: members only see averages and *Split* flags for applicants they've scored.

- **Scoring rubric and notes.** Admins set up the rubric on the **Rubric** page: criteria like Communication or Fit, each scored 1 to 5, with a weight (a 2 counts twice as much as a 1) and an optional "what to look for" line. Rounds (First round, Final round, or your own) get separate score sheets.
  - Everyone on the team fills in a **score sheet** per applicant per round: a 1-5 score for each criterion plus written notes. Save a draft and finish it later, or submit it. Submitted sheets can still be edited.
  - **No anchoring:** you can't see anyone else's scores or notes for an applicant in a round until you've submitted your own. Drafts are only ever visible to the person writing them. Admins can look before scoring (they run deliberations), but other people's scores stay folded away until they choose to open them.
  - Profiles show each member's scores and notes, the weighted score of every sheet, per-criterion averages for the round, and the applicant's overall average.
  - The board shows each applicant's average and can **sort by score**. Members only see averages for applicants they've scored, so the board can't anchor them either.
  - The score sheet opens on the round that matches the applicant's latest interview slot label.
  - Removing a member keeps their sheets (shown as "Former member"); editing the rubric re-weights every average.

- **Interview scheduling.** Admins add interview slots (date, time, length, room or Zoom link, interviewers), several back-to-back slots at once.
  - Book applicants from the **Schedule** page or from their profile. An applicant can't be in two overlapping slots, a slot holds one applicant, and interviewers can't be double booked.
  - Booking someone who's still *Applied* moves them to **Interviewing** automatically.
  - The schedule is grouped by day, with filters for *I'm interviewing* and *Open*. The board and profiles show each applicant's next interview.
  - **Export to your calendar** as an `.ics` file, either every slot or just the ones you're interviewing in. It works with Google Calendar, Apple Calendar and Outlook.
  - Members see the full schedule read-only. Only admins create, book or change slots.

- **Accounts and roles.** Everyone logs in with their own email and password. **Admins** can do everything and manage the team; **members** can view the board and every profile, but can't change anything.
  - The first account, created on a one-time setup page, becomes the admin.
  - Admins invite people with **one-time signup links** (optionally locked to one email, expire after 7 days), change roles, and remove access, all from the **Members** page. Recruitly never sends email, so you paste the link into GroupMe or Slack.
  - Passwords are hashed with Argon2, sessions are signed cookies, every form has a CSRF token, and repeated wrong passwords lock the login for a few minutes.
  - Headshots are only served to logged-in members.
- **Google Form import** from a CSV export or a shared Google Sheets link
- **Automatic column mapping.** Form questions like "What is your major?" or "Expected graduation date" are matched to profile fields, and you can fix any mapping before importing.
- **Validation and cleanup**, with every change listed so you can check it:
  - names capitalized properly (`mcdonald` → `McDonald`, `O'NEIL` → `O'Neil`), and "Full name" split into first and last
  - emails lowercased, with common typos fixed (`@utexas.com` → `@utexas.edu`, `@gmial.com` → `@gmail.com`)
  - majors matched to the official list (`comp sci` → Computer Science, `MIS` → Management Information Systems, `Kinesology` → Kinesiology), and double majors split
  - phone numbers, graduation terms (`spring 2028`, `5/2027`, `'29`), GPAs (`3.9/4.0`, `4.3/5`), class standing, LinkedIn and Instagram all put into one format
  - bad data flagged instead of silently saved (an invalid email skips the row, and an out-of-range GPA is left blank with a warning)
- **Preview before saving.** See exactly what will be created, updated or skipped.
- **Duplicate handling.** If someone submits twice, only their newest response is kept. Re-importing updates existing profiles instead of duplicating them.
- **Headshots**, downloaded from Drive links when shared, or matched in bulk from the Drive folder zip (Google names uploads `IMG_1234 - Jordan Lee.jpg`, so Recruitly matches by name, email or EID). Images are rotated correctly, cropped to a square and resized.
- **Applicant board** with search, filters by status, major and year, sorting, and status tracking (Applied → Interviewing → Final Round → Offered → Accepted)
- Manual add and edit, using the same cleanup rules as imports
- CSV export
- Works on phones

## Quick start

You need Python 3.10 or newer.

```bash
git clone https://github.com/aabanehsan/recruitly
cd recruitly
python3 run.py demo
```

That one command sets up everything the first time, loads 15 sample form responses (fictional people, deliberately messy data), creates four demo logins, adds interview slots (yesterday's first round plus two days starting tomorrow), a four-criterion rubric with score sheets from yesterday's interviews, a closed screening vote (which cut four applicants), an open first-round debrief and a saved Google Sheets link, and opens the app at http://localhost:8000:

| Role | Email | Password |
|---|---|---|
| Admin | `admin@demo.recruitly.dev` | `demo-admin-2026` |
| Member | `member@demo.recruitly.dev` | `demo-member-2026` |
| Member | `riley@demo.recruitly.dev` | `demo-riley-2026` |
| Member | `sam@demo.recruitly.dev` | `demo-sam-2026` |

They're printed in the terminal and shown on the login page too. Log in as the member to see the read-only view and the anchoring rule: Morgan can see everyone's scores for Danny and Grace (Morgan scored them) but not for Mateo, and Aisha still has an unfinished draft. On **Decisions**, Riley and Sam have already voted in the open debrief: the admin sees their tally, Morgan only sees a vote count until the admin closes it.

As the admin, open **Settings → Sync now** to see a sync: the demo's sheet link isn't real, so it reads a bundled copy of the sheet with two new applicants and two people who edited their answers. **Emails → Interview invite → Make drafts** shows ready-to-send invites for everyone booked tomorrow.

Use `python3 run.py` without `demo` to start fresh: the first page asks you to create the admin account, then you invite the rest of your exec team from **Members**.

Prefer Docker? You don't need Python at all:

```bash
git clone https://github.com/aabanehsan/recruitly
cd recruitly
RECRUITLY_MODE=demo docker compose up --build    # or just `docker compose up --build` to start fresh
```

See [Docker](#docker) below for Postgres and running it for your team.

Prefer to manage the environment yourself?

```bash
pip install -e .
recruitly demo          # or just: recruitly
```

## Importing your form

1. Open your Google Form's **Responses** tab and click **View in Sheets**.
2. Either download the sheet as **.csv** and upload it on the Import page, or share it as "Anyone with the link" and paste the link.
3. Review the preview, fix any column mappings, and click **Import**.
4. For headshots: if Drive blocked the downloads (it usually does for private form uploads), download the form's upload folder from Drive as a zip and drop it on the **Headshots** page.

To keep pulling in new responses, tick **Save this link for one-click sync** when you paste the link (or save it in **Settings**). From then on **Sync now** on the Import or Settings page fetches the sheet again and previews only what's new or changed.

You can also import from the terminal:

```bash
recruitly import responses.csv
```

## Accounts

- **First run:** open the app and create the admin account. That page disappears once an account exists.
- **Inviting:** Members → *Create invite link*, then send the link. Each link works once. If you fill in an email, only that address can sign up with it.
- **Roles:** admins can import, edit, change statuses (one at a time or in bulk), upload headshots, schedule interviews, run deliberations, export and manage members. Members can view applicants and the interview schedule, download calendar files, fill in their own score sheets and vote in open deliberations. There's always at least one admin, and you can't demote or remove yourself.
- **Forgot a password?** Anyone can change their own on the account page. If someone is locked out, run `recruitly reset-password their@email.edu` on the machine running Recruitly. Changing a password signs that person out everywhere else.

## Interviews

1. On **Schedule**, fill in *Add interview slots*: pick the date, start time, length and how many back-to-back slots you want, a room or a Zoom/Meet link, and who's interviewing.
2. Book applicants with the dropdown on each open slot, or from an applicant's profile (*Book an open slot*).
3. Interviewers click **My interviews (.ics)** and open the file to add their slots to their calendar. If the schedule changes, download it again to pick up the new times.

Times are in the org's time zone (`RECRUITLY_TIMEZONE`, Central time by default). Past slots are hidden unless you click *Show past*.

## Scoring

1. An admin opens **Rubric**, adds the criteria and weights, and renames or adds rounds to match how you interview. Naming rounds like your slot labels (e.g. "First round") lets the score page pick the right round automatically.
2. After an interview, open the applicant and click **Score** next to the round. Pick 1-5 for each criterion, write notes, and **Submit scores** (or **Save draft** to finish later).
3. Once you've submitted, everyone else's scores and notes for that round appear on the profile. Sort the board by **Score** to see who's on top.

Changing a weight re-calculates every average. Removing a criterion deletes its scores, and a round with score sheets can be renamed but not deleted.

## Deliberations

1. On **Decisions**, an admin types a name (e.g. "First-round debrief") and clicks **Open voting**. Only one session can be open at a time.
2. Everyone votes yes, no or abstain on each applicant, from the table or the applicant's profile. Votes can change until the session closes.
3. The admin clicks **Close and show results**. The results page ranks applicants by yes minus no votes; tick the ones you've decided on and use **Set status** to move them to *Offered* or *Cut* in one go.

Past sessions stay listed on the Decisions page and on each applicant's profile. Deleting a session deletes its votes.

## Emails

1. Open **Emails**. The invite, offer and rejection templates are ready to go; click **Edit** to change the wording. The placeholder list on the right shows everything you can use, and a typo like `{frist_name}` is caught when you save.
2. Click **Make drafts**. Pick who the drafts are for if it's not the template's usual group.
3. For each person, click **Open in email app** to get a filled-in email in Gmail, Outlook or Apple Mail, or copy the subject and body. Very long emails are better copied, since some email apps cut off long links.

`{slot_time}`, `{slot_date}`, `{slot_length}` and `{slot_location}` come from the applicant's next booked interview. `{first_name}` uses their preferred name when they gave one.

## Docker

`docker-compose.yml` builds the image and runs Recruitly on http://localhost:8000:

```bash
docker compose up --build -d     # start in the background
docker compose logs -f           # see what it's doing
docker compose down              # stop (your data stays)
```

- **Your data** (database, headshots, the login signing key) lives in `./data` next to the compose file, the same folder `python3 run.py` uses, so you can switch between the two. Back it up by copying that folder.
- **Demo data:** `RECRUITLY_MODE=demo docker compose up --build`. The demo logins are printed in the logs and shown on the login page.
- **Settings** go in a `.env` file next to `docker-compose.yml` (e.g. `RECRUITLY_ORG_NAME="Your Org"`, `RECRUITLY_PORT=8080`). Every variable in [Configuration](#configuration) works.
- **Commands** run inside the container: `docker compose exec recruitly recruitly reset-password you@utexas.edu`.
- **Upgrading:** `git pull && docker compose up --build -d`.
- The port is only published on `127.0.0.1`. To let your team in, put a reverse proxy with HTTPS (Caddy, nginx, Cloudflare Tunnel) in front of it and set `RECRUITLY_SECURE_COOKIES=1`.
- The container runs as an unprivileged user and has a health check on `/healthz`.

### Postgres

SQLite is plenty for one org's recruitment. If you'd rather use Postgres (or your host only offers that), add the override file, which starts a `postgres:16` container next to Recruitly:

```bash
echo "RECRUITLY_DB_PASSWORD=pick-a-long-password" >> .env
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up --build -d
```

Postgres keeps its data in the `recruitly-postgres` Docker volume; headshots stay in `./data`.

Without Docker, install the driver and point `RECRUITLY_DB_URL` at any Postgres database:

```bash
pip install -e ".[postgres]"
RECRUITLY_DB_URL=postgresql://user:password@localhost:5432/recruitly recruitly
```

`postgres://` URLs (as Render, Railway, Heroku and Supabase give them) work as-is. Tables are created on first start. Recruitly doesn't copy an existing SQLite database into Postgres, so pick one before your cycle starts (or re-import the form, which is quick).

## Configuration

Set these as environment variables:

| Variable | Default | What it does |
|---|---|---|
| `RECRUITLY_ORG_NAME` | `Recruitly` | Name shown in the header |
| `RECRUITLY_CYCLE` | `Fall Rush` | Recruitment cycle label |
| `RECRUITLY_EMAIL_DOMAIN` | none | Warn when an email isn't on this domain, e.g. `utexas.edu` |
| `RECRUITLY_TIMEZONE` | `America/Chicago` | Time zone interview slots are in, used for calendar export |
| `RECRUITLY_DATA_DIR` | `./data` | Where the database and headshots live |
| `RECRUITLY_DB_URL` | SQLite in the data dir | Database URL: `sqlite:///path.db` or `postgresql://user:password@host:5432/db` |
| `RECRUITLY_FETCH_HEADSHOTS` | `1` | Set to `0` to skip downloading headshots from Drive links |
| `RECRUITLY_SECRET_KEY` | generated | Key that signs login cookies. By default one is generated into `data/secret_key` on first run |
| `RECRUITLY_SECURE_COOKIES` | `0` | Set to `1` when serving over HTTPS so the login cookie is only sent securely |
| `RECRUITLY_MODE` | `serve` | Docker Compose only: set to `demo` to load the demo data |
| `RECRUITLY_PORT` | `8000` | Docker Compose only: the port on your machine |
| `RECRUITLY_DB_PASSWORD` | `recruitly` | Docker Compose with Postgres only: the database password |

## How it's built

- **FastAPI** + **Jinja** templates, server-rendered with plain CSS and no frontend framework
- **SQLAlchemy 2.0** with SQLite by default, or PostgreSQL through **psycopg 3**
- **Docker** image and Compose files; CI runs the tests on Python 3.10-3.13, again against Postgres, and boots the Compose setup
- **Pillow** for headshot processing
- **argon2-cffi** for password hashing and Starlette's signed session cookies for logins
- Cleaning, account, scheduling, scoring, decision, sync and email rules live in `recruitly/services/` as pure functions, so every rule is unit tested. A test checks that every route has an access rule, so a new page can't ship unprotected.

```
recruitly/
  app.py              applicant, import and headshot routes
  accounts.py         setup, login, invites, members, your account
  schedule.py         interview slots, booking, .ics export
  scoring.py          rubric, rounds and score sheet pages
  decisions.py        decisions dashboard, deliberations, votes, bulk status
  sync.py             settings page, saved Google Sheet and one-click sync
  emails.py           email templates and per-applicant drafts
  web.py              templates, current user, admin check, CSRF
  models.py           Applicant, ImportPreview, User, Invite, InterviewSlot, Round, Criterion, ScoreSheet, Score,
                      Deliberation, Vote, AppSetting, EmailTemplate
  services/
    auth.py           password hashing, roles, invite and login rules
    scheduling.py     slot parsing, double-booking checks, .ics building
    scoring.py        rubric parsing, weighted averages, who-sees-whose-scores rules
    decisions.py      ranking, flags, vote tallies and visibility, funnel and chart maths
    sync.py           what changed between syncs, remembered column mappings, "synced 2 hours ago"
    database.py       database URLs (SQLite, Postgres) and connection settings
    emails.py         placeholders, template checks, drafts and mailto: links
    cleaning.py       header mapping + field validation/cleanup
    importer.py       two-step import: preview, then apply
    headshots.py      Drive download, zip matching, crop/resize
  templates/          Jinja pages
  sample_data/        demo form export, a later copy for the sync demo, placeholder headshots
tests/                pytest suite
run.py                one-command setup + start
Dockerfile, docker-compose.yml, docker-compose.postgres.yml
docs/screenshots/     light and dark screenshots of every main screen
```

Run the tests with `pip install -e ".[dev]" && pytest`. To run them against Postgres too: `pip install -e ".[dev,postgres]"` and set `RECRUITLY_TEST_DB_URL=postgresql://user:password@localhost/recruitly_test` (an empty database; every test starts from fresh tables).

## Roadmap

Recruitly 1.0 finishes the original roadmap: import, accounts, scheduling, scoring, decisions, sync and emails, packaged for Docker and Postgres. See [ROADMAP.md](ROADMAP.md) for how it was built, one release at a time. Ideas and bug reports are welcome as GitHub issues.

## Privacy note

Applicant data stays wherever you run Recruitly. Every page needs a login, and only admins can change or export data. Score sheets are only shown to the team, under the anchoring rule above. The default only listens on localhost; if you put it on a server for your team, run it behind HTTPS and set `RECRUITLY_SECURE_COOKIES=1`.

## License

MIT
