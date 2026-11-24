"""SQLite connections and schema initialization using Python's standard library."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import re


@contextmanager
def connect_db(database_path):
    """Open a connection, commit on success, roll back on error, and always close.

    SQLite errors propagate to the caller so a CLI or route can handle them.
    """
    connection = sqlite3.connect(database_path)
    try:
        connection.row_factory = sqlite3.Row
        # SQLite requires foreign-key enforcement on every connection.
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def init_db(database_path):
    """Create the parent directory and missing tables from the trusted schema file."""
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).with_name("schema.sql")
    schema = schema_path.read_text(encoding="utf-8")
    with connect_db(database_path) as connection:
        connection.executescript(schema)


def migrate_resources(database_path):
    """Add resource columns and child table atomically; safe to run repeatedly."""
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connect_db(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(applications)")}
        if not columns:
            raise ValueError("Initialize the database before migrating resources.")
        for column in ("job_posting_url", "application_portal_url"):
            if column not in columns:
                # Column names are fixed project constants, never request input.
                connection.execute(f"ALTER TABLE applications ADD COLUMN {column} TEXT")
        for prefix in (
            "CREATE TABLE IF NOT EXISTS application_email_links (",
            "CREATE INDEX IF NOT EXISTS idx_application_email_links_application_id",
        ):
            statement = prefix + schema.split(prefix, 1)[1].split(";", 1)[0]
            connection.execute(statement)
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.IntegrityError("Foreign key integrity check failed during resource migration.")


def migrate_statuses(database_path):
    """Expand the legacy CHECK while preserving every column and dependent table.

    Only this migration connection temporarily disables foreign keys, outside
    its transaction. Otherwise dropping the old parent could cascade-delete
    email links. The interview table is never rebuilt or altered.
    """
    with connect_db(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.execute("BEGIN IMMEDIATE")
            definition = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("applications",),
            ).fetchone()
            if definition is None:
                raise ValueError("Initialize the database before migrating statuses.")
            if "'Assessment'" not in definition["sql"]:
                constraint = (
                    "CHECK (status IN ('Applied', 'Assessment', 'Interview', 'Offer', "
                    "'Rejected', 'Withdrawn', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn'))"
                )
                updated, count = re.subn(
                    r"CHECK\s*\(\s*status\s+IN\s*\([^)]*\)\s*\)",
                    constraint, definition["sql"], count=1, flags=re.IGNORECASE,
                )
                if count != 1:
                    raise ValueError("Unrecognized status constraint; migration stopped without changes.")
                objects = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE tbl_name = ? "
                    "AND type IN ('index', 'trigger') AND sql IS NOT NULL",
                    ("applications",),
                ).fetchall()
                # Preserve columns added by other features, not just the original seven.
                columns = [row["name"] for row in connection.execute("PRAGMA table_info(applications)")]
                names = ", ".join('"' + name.replace('"', '""') + '"' for name in columns)
                connection.execute("CREATE TABLE applications_new (" + updated.split("(", 1)[1])
                connection.execute(f"INSERT INTO applications_new ({names}) SELECT {names} FROM applications")
                connection.execute("DROP TABLE applications")
                connection.execute("ALTER TABLE applications_new RENAME TO applications")
                for item in objects:
                    connection.execute(item["sql"])
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise sqlite3.IntegrityError("Foreign key integrity check failed during status migration.")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")
