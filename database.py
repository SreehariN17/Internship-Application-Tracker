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
