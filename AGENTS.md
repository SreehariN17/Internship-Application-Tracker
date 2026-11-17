# Project guidelines

- Keep this beginner project focused on Python, Flask, SQLite, REST APIs, and SQL JOINs.
- Prefer small functions and Python's standard library. Explain new dependencies.
- Keep HTTP routes in `app.py`, connection helpers in `database.py`, and tables in `schema.sql`.
- Bind all SQL data values using `?` placeholders and parameter tuples. Never interpolate user input into SQL.
- Use `connect_db()` so every connection enforces foreign keys, handles transactions, and closes.
- Handle expected failures at the CLI or API boundary. Do not expose database internals in future API error responses.
- Keep initialization non-destructive. `CREATE TABLE IF NOT EXISTS` does not migrate existing tables; plan schema changes explicitly.
- Do not add authentication, a frontend, or extra frameworks without a project requirement.
- Add meaningful tests for new behavior. Run `.venv/bin/python -m unittest discover -s tests -v`.
- Do not commit or push unless explicitly requested.
