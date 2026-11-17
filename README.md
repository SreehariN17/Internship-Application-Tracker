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
python -m flask --app app run
```

If `.venv` already exists, activate it and skip the first command.
The initialization command creates `instance/tracker.db` and missing tables.
It preserves existing data; it does not migrate changed table definitions.
The development server runs at `http://127.0.0.1:5000`. Stop it with Ctrl+C.

```sh
curl -i http://127.0.0.1:5000/health
```

Expected: HTTP 200 with `{"status":"ok"}`. This endpoint checks that the API
is running; it does not check the database. No application CRUD routes exist yet.

## Files

| File | Purpose |
| --- | --- |
| `app.py` | App factory, JSON health route, and `init-db` command with readable failure messages. |
| `database.py` | Opens and closes SQLite connections, enables foreign keys, commits successful transactions, rolls back failures, and initializes the schema. Errors propagate to the caller. |
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
Application statuses are `applied`, `interviewing`, `offer`, `rejected`, and
`withdrawn`. `applied_date` is a text date, defaulting to today's UTC date in
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

## Two-week scope

In week one, split work across company routes, application routes, and
validation/tests. Agree on request and response shapes together. In week two,
add JOIN-based application listings, status filtering, integration tests, and
documentation. Keep authentication, frontend work, and additional frameworks
outside this initial scope.
