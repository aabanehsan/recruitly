# Recruitly

Applicant tracking for student org recruitment. Point it at your Google Form responses, and it builds a clean profile for every applicant, with their headshot, major, year, GPA, links and short answers, in one place your whole exec team can use.

![Applicant board](docs/board.png)

## Why

Most orgs run recruitment out of a Google Form and a messy spreadsheet. Names come in as `jOHN`, majors as `cs`, `comp sci` and `Computer Science`, phone numbers in five formats, and someone always submits twice. Headshots end up in a Drive folder that nobody can match to the right row. Recruitly fixes all of that on import and gives you a board you can actually run rush from.

## Features (v0.1)

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

That one command sets up everything the first time, loads 12 sample form responses (fictional people, deliberately messy data), and opens the app at http://localhost:8000. Use `python3 run.py` without `demo` to start with an empty board.

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

You can also import from the terminal:

```bash
recruitly import responses.csv
```

## Configuration

Set these as environment variables:

| Variable | Default | What it does |
|---|---|---|
| `RECRUITLY_ORG_NAME` | `Recruitly` | Name shown in the header |
| `RECRUITLY_CYCLE` | `Fall Rush` | Recruitment cycle label |
| `RECRUITLY_EMAIL_DOMAIN` | none | Warn when an email isn't on this domain, e.g. `utexas.edu` |
| `RECRUITLY_DATA_DIR` | `./data` | Where the database and headshots live |
| `RECRUITLY_DB_URL` | SQLite in the data dir | Any SQLAlchemy database URL |
| `RECRUITLY_FETCH_HEADSHOTS` | `1` | Set to `0` to skip downloading headshots from Drive links |

## How it's built

- **FastAPI** + **Jinja** templates, server-rendered with plain CSS and no frontend framework
- **SQLAlchemy 2.0** with SQLite by default
- **Pillow** for headshot processing
- Cleaning lives in `recruitly/services/cleaning.py` as pure functions, so every rule is unit tested

```
recruitly/
  app.py              routes
  models.py           Applicant, ImportPreview
  services/
    cleaning.py       header mapping + field validation/cleanup
    importer.py       two-step import: preview, then apply
    headshots.py      Drive download, zip matching, crop/resize
  templates/          Jinja pages
  sample_data/        demo form export and placeholder headshots
tests/                pytest suite
run.py                one-command setup + start
```

Run the tests with `pip install -e ".[dev]" && pytest`.

## Roadmap

Accounts and roles, interview scheduling, scoring rubrics, voting, live Sheets sync and Docker are planned. See [ROADMAP.md](ROADMAP.md).

## Privacy note

Applicant data stays wherever you run Recruitly. v0.1 has no login, so run it on your own machine (the default only listens on localhost). Accounts and roles arrive in v0.2.

## License

MIT
