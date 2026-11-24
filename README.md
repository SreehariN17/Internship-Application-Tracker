# Internship Application Tracker

A beginner-friendly Rutgers Blueprint Fellowship backend project for a team of
three. Built with Python, Flask, and SQLite to practice REST APIs and SQL JOINs.

## Setup and run

Use Python 3.11 or newer. From the project directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m flask --app app init-db
python -m flask --app app migrate-statuses
python -m flask --app app run
```

If `.venv` already exists, activate it and skip the first command.
The initialization command creates `instance/tracker.db` and missing tables.
It preserves existing data; it does not migrate changed table definitions.
The development server runs at `http://127.0.0.1:5000`. Stop it with Ctrl+C.

Open `http://127.0.0.1:5000/` in your browser to view the dashboard.
The ScarletTrack dashboard loads existing applications automatically. Use
**Add Application** to open a form, enter the company and position, select a
status, and save. Applied Date defaults to today's local date; notes are optional.
The form sends JSON to `POST /applications`, then reloads `GET /applications`
after a successful save. Failed requests leave your inputs in place and show
an error. Submission is disabled while saving to prevent duplicate requests.
JavaScript fetches `GET /applications`, reads its `applications` array, and
renders rows with `textContent` in the order returned by the API. Null notes
appear as an em dash. Loading, empty, and failed-request messages are included.
On small screens, scroll the table horizontally to view all five columns.

```sh
curl -i http://127.0.0.1:5000/health
```

Expected: HTTP 200 with `{"status":"ok"}`. This endpoint checks that the API
is running; it does not check the database. Application CRUD routes are described below.

## Files

| File | Purpose |
| --- | --- |
| `app.py` | App factory, JSON health route, and `init-db` command with readable failure messages. |
| `templates/index.html` | Dashboard page with the applications table and loading, empty, and error states. |
| `static/style.css` | Light dashboard styling, distinct status colors, and a responsive table container. |
| `static/script.js` | Fetches `/applications` and safely displays its JSON data using `textContent`. |
| `tests/test_frontend.py` | Checks the dashboard title, page response, asset links, and static file delivery. |
| `database.py` | Opens and closes SQLite connections, enables foreign keys, commits successful transactions, rolls back failures, and initializes the schema. Errors propagate to the caller. |
| `tests/test_applications.py` | Application CRUD, validation, transactions, and status migration tests. |
| `schema.sql` | Companies, applications, and interviews tables, constraints, and foreign-key indexes. |
| `requirements.txt` | Flask, the only direct third-party dependency; pip installs its dependencies automatically. SQLite and unittest are included in Python. |
| `.gitignore` | Excludes the virtual environment, local databases, secrets files, and Python cache files. |
| `AGENTS.md` | Project conventions for future coding assistants and contributors. |
| `tests/test_app.py` | Tests the endpoint, initialization, safe SQL values, JOINs, persistence, foreign keys, rollback, and CLI error handling using temporary databases. |
| `README.md` | Setup, architecture, examples, tests, and suggested next steps. |

## Database basics

One company can have many applications. Each application must reference an
existing company. Each application can have many interviews, and each interview
must reference an existing application. Deleting a company with applications or
an application with interviews is restricted. This is a single-user app; no users
table or authentication is needed. Company websites and application notes are optional.
API statuses are `Applied`, `Assessment`, `Interview`, `Offer`,
`Rejected`, and `Withdrawn`. Legacy lowercase database values remain supported
and are displayed with the API labels. New API writes require the exact labels above. `applied_date` is a text date, defaulting to today's UTC date in
`YYYY-MM-DD` format. Store interview dates as ISO 8601 text (for example,
`2026-11-20T14:00:00-05:00`) and types as text (for example, `technical`
or `behavioral`). Future routes should validate dates; SQLite does not enforce
their format. Interview types are not restricted to a fixed list.

Always bind data values with placeholders, including values coming from HTTP
requests. Example after initializing the database:

```python
from database import connect_db

with connect_db("instance/tracker.db") as connection:
    company = connection.execute(
        "INSERT INTO companies (name) VALUES (?)", ("Example Company",)
    )
    connection.execute(
        "INSERT INTO applications (company_id, position) VALUES (?, ?)",
        (company.lastrowid, "Backend Intern"),
    )
    rows = connection.execute(
        "SELECT a.id, c.name, a.position, a.status "
        "FROM applications AS a JOIN companies AS c ON a.company_id = c.id "
        "WHERE a.status = ?",
        ("applied",),
    ).fetchall()
    for row in rows:
        print(dict(row))
```

The connection helper commits on success, rolls back on failure, and closes
the connection. Schema initialization uses a trusted local SQL file; never
pass user input to `executescript`. Future routes should catch expected database
errors and return clear JSON errors without exposing SQL or internal details.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests use temporary databases and do not modify `instance/tracker.db`.

### Manual dashboard checklist

Start the server using the setup commands and open `http://127.0.0.1:5000/`.
Manual form submissions create real application records in your configured database.

- Check ScarletTrack branding, the tagline, scarlet buttons, company initials,
  status text/colors, and the student-built footer.
- Open Add Application. Verify Applied is selected and the date matches your
  local calendar. Check all six statuses and optional notes.
- Use Tab and Shift+Tab to navigate within the dialog. Check initial company-field
  focus, Escape, Cancel, and Close; focus should return to Add Application.
- Submit empty fields, whitespace-only company/position, and an invalid date;
  verify validation prevents saving.
- Save a valid application. Check the saving state, success message, closed/reset
  form, and refreshed table. Double-click Save and check that only one POST occurs.
- In browser developer tools, go offline after opening the form and submit.
  Check the error, preserved inputs, and enabled Save button; restore connectivity.
  A backend error should also appear as plain text without clearing the form.
- Check notes such as `<b>hello</b>` display literally as text. Check empty notes
  display an em dash and company names with multiple words have initials.
- Test desktop and narrow mobile widths (for example, 375px): table scrolling,
  full-width Add button, stacked form fields, scrollable dialog, and visible actions.
- Verify existing loading/empty/error states and that status remains understandable
  without relying on color. No interview, statistics, edit/delete, or filter controls
  should appear.

## Two-week scope

In week one, split work across company routes, application routes, and
validation/tests. Agree on request and response shapes together. In week two,
add JOIN-based application listings, status filtering, integration tests, and
documentation. Keep authentication and additional frameworks
outside this initial scope.

## Application API (Step C)

For a fresh database, run `init-db`. For an existing database with the original
status constraint, back it up and run:

```sh
python -m flask --app app migrate-statuses
```

This explicit, repeatable migration expands only the application status choices.
It preserves company, application, and interview records, IDs, and relationships.
It rebuilds the two related tables together in a transaction because SQLite
cannot alter a CHECK constraint directly. Foreign keys stay enabled. Initialization
alone does not migrate old constraints. The migration targets this project's
original schema; custom tables, indexes, and triggers need a separate migration.

| Method and path | Behavior | Success |
| --- | --- | --- |
| GET /applications | List applications with company names using a JOIN, newest applied_date first; higher ID breaks date ties. | 200 |
| GET /applications/1 | Get one application with its company name. | 200 |
| POST /applications | Create an application and reuse or create its company. | 201 |
| PATCH /applications/1 | Update only the supplied fields. | 200 |
| DELETE /applications/1 | Delete an application if it has no interviews; keep its company. | 204, empty body |

POST requires `company_name`, `position`, `status`, and `applied_date`.
`notes` is optional and accepts text or null. PATCH accepts any non-empty subset
of those five fields; unknown fields are rejected. Company names and positions
are trimmed. Company matching ignores surrounding whitespace and capitalization
(including Unicode case folding). Existing duplicates are not removed; the
oldest matching company is reused. Dates must be real calendar dates written
exactly as YYYY-MM-DD. Status labels are case-sensitive.

Writes use one transaction for company lookup/creation and application changes.
An immediate SQLite transaction serializes writes so simultaneous API requests
do not create the same company. No company management endpoints are included.

Example requests (start the Flask server first):

```sh
curl -i -X POST http://127.0.0.1:5000/applications \
  -H 'Content-Type: application/json' \
  -d '{"company_name":"Example","position":"Backend Intern","status":"Applied","applied_date":"2026-11-17","notes":"Referral"}'

curl http://127.0.0.1:5000/applications
curl http://127.0.0.1:5000/applications/1

curl -X PATCH http://127.0.0.1:5000/applications/1 \
  -H 'Content-Type: application/json' \
  -d '{"status":"Interview"}'

curl -i -X DELETE http://127.0.0.1:5000/applications/1
```

POST returns 201, a Location header such as /applications/1, and:

```json
{"application":{"id":1,"company_id":1,"company_name":"Example","position":"Backend Intern","status":"Applied","applied_date":"2026-11-17","notes":"Referral"}}
```

Single GET and PATCH return the same object envelope. PATCH returns updated values.
The list returns `{"applications":[...]}`, or `{"applications":[]}` when empty.
IDs depend on existing records; use the ID returned by POST in later requests.

Errors consistently use an `error` field:

- 400: invalid JSON/body, missing/unknown fields, invalid status or date.
- 404: `{"error":"Application not found."}`
- 409: `{"error":"Application has related interviews and cannot be deleted."}`
- 500: `{"error":"Database operation failed."}` for unexpected database errors;
  internal details are logged only on the server.
