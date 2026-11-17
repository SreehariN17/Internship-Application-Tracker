"""SQLite connections and schema initialization using Python's standard library."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3


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


def migrate_statuses(database_path):
    """Expand the original status constraint without losing applications/interviews.

    Rebuild both related tables in one transaction with foreign keys still ON.
    Run explicitly with the migrate-statuses CLI command on existing databases.
    """
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connect_db(database_path) as connection:
        definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("applications",),
        ).fetchone()
        if definition is None:
            raise ValueError("Initialize the database before migrating statuses.")
        if "'Assessment'" in definition["sql"]:
            return
        # BEGIN makes table creation and data copying part of the same transaction.
        connection.execute("BEGIN IMMEDIATE")
        for table in ("applications", "interviews"):
            statement = schema.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split(";", 1)[0]
            statement = f"CREATE TABLE {table}_new (" + statement
            if table == "interviews":
                statement = statement.replace("REFERENCES applications(id)", "REFERENCES applications_new(id)")
            connection.execute(statement)
            connection.execute(f"INSERT INTO {table}_new SELECT * FROM {table}")
        connection.execute("DROP TABLE interviews")
        connection.execute("DROP TABLE applications")
        connection.execute("ALTER TABLE applications_new RENAME TO applications")
        connection.execute("ALTER TABLE interviews_new RENAME TO interviews")
        connection.execute("CREATE INDEX idx_applications_company_id ON applications(company_id)")
        connection.execute("CREATE INDEX idx_interviews_application_id ON interviews(application_id)")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.IntegrityError("Foreign key integrity check failed during migration.")
