"""API and database tests; each test gets a temporary SQLite database."""

from pathlib import Path
import sqlite3
import tempfile
import unittest

from app import create_app
from database import connect_db, init_db


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database_path = Path(self.directory.name) / "data" / "test.db"
        self.app = create_app({"TESTING": True, "DATABASE": str(self.database_path)})

    def test_health(self):
        response = self.app.test_client().get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_initialization_and_join_with_parameterized_values(self):
        init_db(self.database_path)
        company_name = "Example's Company'); DROP TABLE companies; --"
        with connect_db(self.database_path) as connection:
            company = connection.execute(
                "INSERT INTO companies (name) VALUES (?)", (company_name,)
            )
            connection.execute(
                "INSERT INTO applications (company_id, position) VALUES (?, ?)",
                (company.lastrowid, "Backend Intern"),
            )
        # Read through a new connection to verify the inserts were committed.
        with connect_db(self.database_path) as connection:
            row = connection.execute(
                "SELECT c.name, a.position, a.status FROM applications AS a "
                "JOIN companies AS c ON a.company_id = c.id WHERE c.name = ?",
                (company_name,),
            ).fetchone()
            self.assertEqual(tuple(row), (company_name, "Backend Intern", "applied"))

    def test_initialization_preserves_data(self):
        init_db(self.database_path)
        with connect_db(self.database_path) as connection:
            connection.execute("INSERT INTO companies (name) VALUES (?)", ("Example",))
        init_db(self.database_path)
        with connect_db(self.database_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 1)

    def test_foreign_keys_and_rollback(self):
        init_db(self.database_path)
        with self.assertRaises(sqlite3.IntegrityError):
            with connect_db(self.database_path) as connection:
                connection.execute("INSERT INTO companies (name) VALUES (?)", ("Rolled back",))
                connection.execute(
                    "INSERT INTO applications (company_id, position) VALUES (?, ?)",
                    (999, "Intern"),
                )
        with connect_db(self.database_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 0)

    def test_init_db_command(self):
        result = self.app.test_cli_runner().invoke(args=["init-db"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Database initialized.", result.output)
        self.assertTrue(self.database_path.exists())

    def test_interviews_join_and_foreign_keys(self):
        init_db(self.database_path)
        with connect_db(self.database_path) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            company = connection.execute(
                "INSERT INTO companies (name, website) VALUES (?, ?)",
                ("Example", "https://example.com"),
            )
            application = connection.execute(
                "INSERT INTO applications (company_id, position) VALUES (?, ?)",
                (company.lastrowid, "Intern"),
            )
            for interview_type in ("technical", "behavioral"):
                connection.execute(
                    "INSERT INTO interviews (application_id, interview_date, type) VALUES (?, ?, ?)",
                    (application.lastrowid, "2026-11-20T14:00:00-05:00", interview_type),
                )
            rows = connection.execute(
                "SELECT c.website, a.position, i.type FROM companies AS c "
                "JOIN applications AS a ON a.company_id = c.id "
                "JOIN interviews AS i ON i.application_id = a.id ORDER BY i.id"
            ).fetchall()
            self.assertEqual([tuple(row) for row in rows], [
                ("https://example.com", "Intern", "technical"),
                ("https://example.com", "Intern", "behavioral"),
            ])
        with connect_db(self.database_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO interviews (application_id, interview_date, type) VALUES (?, ?, ?)",
                    (999, "2026-11-20", "technical"),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM applications WHERE id = ?", (application.lastrowid,))
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM companies WHERE id = ?", (company.lastrowid,))

    def test_init_db_command_reports_failure(self):
        # A directory cannot be opened as a SQLite database file.
        self.app.config["DATABASE"] = self.directory.name
        result = self.app.test_cli_runner().invoke(args=["init-db"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Database initialization failed:", result.output)


if __name__ == "__main__":
    unittest.main()
