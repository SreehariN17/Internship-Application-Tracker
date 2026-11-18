"""Application API tests use isolated databases, never the project database."""
from pathlib import Path
import json
import tempfile
import unittest

from app import create_app, STATUSES
from database import connect_db, init_db, migrate_statuses


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "test.db"
        init_db(self.path)
        self.app = create_app({"TESTING": True, "DATABASE": str(self.path)})
        self.client = self.app.test_client()
        self.payload = dict(company_name="Example", position="Backend Intern",
                            status="Applied", applied_date="2026-11-17", notes="Referral")

    def create(self, **changes):
        return self.client.post("/applications", json={**self.payload, **changes})

    def test_create_get_list_and_order(self):
        self.assertEqual(self.client.get("/applications").json, {"applications": []})
        first = self.create(applied_date="2026-01-01")
        self.assertEqual(first.status_code, 201)
        application = first.json["application"]
        self.assertEqual(first.headers["Location"], f"/applications/{application['id']}")
        self.assertEqual(application["company_name"], "Example")
        self.assertEqual(application["position"], "Backend Intern")
        second = self.create().json["application"]
        rows = self.client.get("/applications").json["applications"]
        self.assertEqual([row["id"] for row in rows], [second["id"], application["id"]])
        response = self.client.get(f"/applications/{application['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"application": application})

    def test_company_reuse_and_optional_notes(self):
        first = self.create().json["application"]
        data = {**self.payload, "company_name": "  eXaMpLe  "}
        del data["notes"]
        second = self.client.post("/applications", json=data).json["application"]
        self.assertEqual(first["company_id"], second["company_id"])
        self.assertIsNone(second["notes"])
        with connect_db(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 1)

    def test_list_without_filter_includes_all_statuses(self):
        created = [self.create(status=status).json["application"] for status in STATUSES]
        response = self.client.get("/applications")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"applications": list(reversed(created))})

    def test_filter_each_valid_status(self):
        created = {status: self.create(status=status).json["application"] for status in STATUSES}
        for status in STATUSES:
            with self.subTest(status=status):
                response = self.client.get("/applications", query_string={"status": status})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {"applications": [created[status]]})

    def test_filter_without_matches(self):
        self.create(status="Applied")
        response = self.client.get("/applications?status=Interview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"applications": []})

    def test_filter_rejects_invalid_or_empty_status(self):
        self.create()
        for status in ("", " ", "interviewing", "applied", "Unknown", "Interview ",
                       "Interview' OR 1=1 --"):
            with self.subTest(status=status):
                response = self.client.get("/applications", query_string={"status": status})
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json)
        self.assertEqual(self.client.get("/applications?status").status_code, 400)

    def test_filter_includes_legacy_statuses(self):
        legacy_statuses = {"applied": "Applied", "interviewing": "Interview", "offer": "Offer",
                           "rejected": "Rejected", "withdrawn": "Withdrawn"}
        for legacy, current in legacy_statuses.items():
            modern = self.create(status=current).json["application"]
            old = self.create(status=current).json["application"]
            with connect_db(self.path) as connection:
                connection.execute("UPDATE applications SET status = ? WHERE id = ?", (legacy, old["id"]))
            with self.subTest(status=current):
                response = self.client.get("/applications", query_string={"status": current})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {"applications": [old, modern]})

    def test_filter_preserves_ordering_and_company_names(self):
        older = self.create(status="Interview", company_name="First", applied_date="2026-01-01").json["application"]
        newer = self.create(status="Interview", company_name="Second").json["application"]
        tied = self.create(status="Interview", company_name="Third").json["application"]
        self.create(status="Offer", company_name="Excluded", applied_date="2026-12-01")
        response = self.client.get("/applications?status=Interview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"applications": [tied, newer, older]})

    def test_all_statuses(self):
        for status in STATUSES:
            with self.subTest(status=status):
                response = self.create(status=status)
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json["application"]["status"], status)

    def test_partial_update_and_company_changes(self):
        original = self.create().json["application"]
        url = f"/applications/{original['id']}"
        response = self.client.patch(url, json={"status": "Assessment", "notes": None})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["application"]["position"], original["position"])
        self.assertEqual(response.json["application"]["status"], "Assessment")
        self.assertIsNone(response.json["application"]["notes"])
        other = self.create(company_name="Other").json["application"]
        updated = self.client.patch(url, json={"company_name": " OTHER "}).json["application"]
        self.assertEqual(updated["company_id"], other["company_id"])
        updated = self.client.patch(url, json={"company_name": "New", "position": "Engineer",
                                               "applied_date": "2024-02-29"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["application"]["company_name"], "New")

    def test_invalid_fields_for_post_and_patch(self):
        application_id = self.create().json["application"]["id"]
        bad_fields = [dict(company_name=" "), dict(position=None), dict(status="applied"),
                      dict(status="Unknown"), dict(applied_date="2026-02-29"),
                      dict(applied_date="20261117"), dict(applied_date="2026-1-1"),
                      dict(applied_date=42), dict(notes=[]), dict(company_id=1), dict(extra="x")]
        for fields in bad_fields:
            for method, url, body in [(self.client.post, "/applications", {**self.payload, **fields}),
                                      (self.client.patch, f"/applications/{application_id}", fields)]:
                with self.subTest(fields=fields, method=method.__name__):
                    response = method(url, json=body)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("error", response.json)
        for field in ("company_name", "position", "status", "applied_date"):
            body = self.payload.copy()
            del body[field]
            self.assertEqual(self.client.post("/applications", json=body).status_code, 400)

    def test_invalid_json_bodies(self):
        for method, url in [(self.client.post, "/applications"), (self.client.patch, "/applications/1")]:
            for body in (None, [], "text", 12, {}):
                response = method(url, data=json.dumps(body), content_type="application/json")
                self.assertEqual(response.status_code, 400)
            self.assertEqual(method(url, data="{", content_type="application/json").status_code, 400)
            self.assertEqual(method(url, data="hello").status_code, 400)

    def test_missing_records_and_deletion(self):
        self.assertEqual(self.client.get("/applications/999").status_code, 404)
        self.assertEqual(self.client.patch("/applications/999", json={"status": "Offer"}).status_code, 404)
        self.assertEqual(self.client.delete("/applications/999").status_code, 404)
        application_id = self.create().json["application"]["id"]
        response = self.client.delete(f"/applications/{application_id}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.data, b"")
        self.assertEqual(self.client.get(f"/applications/{application_id}").status_code, 404)

    def test_interviews_block_deletion(self):
        application_id = self.create().json["application"]["id"]
        with connect_db(self.path) as connection:
            connection.execute("INSERT INTO interviews (application_id, interview_date, type) VALUES (?, ?, ?)",
                               (application_id, "2026-11-20", "technical"))
        self.assertEqual(self.client.delete(f"/applications/{application_id}").status_code, 409)
        self.assertEqual(self.client.get(f"/applications/{application_id}").status_code, 200)

    def test_sql_values_are_safe(self):
        name = "Example'); DROP TABLE companies; --"
        response = self.create(company_name=name, position=name, notes=name)
        self.assertEqual(response.status_code, 201)
        application_id = response.json["application"]["id"]
        response = self.client.patch(f"/applications/{application_id}", json={"notes": name})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["application"]["notes"], name)

    def test_failed_insert_rolls_back_new_company(self):
        with connect_db(self.path) as connection:
            connection.execute("CREATE TRIGGER reject_insert BEFORE INSERT ON applications "
                               "BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        response = self.create(company_name="Must Roll Back")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {"error": "Database operation failed."})
        with connect_db(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 0)

    def test_failed_update_rolls_back_new_company(self):
        application_id = self.create().json["application"]["id"]
        with connect_db(self.path) as connection:
            connection.execute("CREATE TRIGGER reject_update BEFORE UPDATE ON applications "
                               "BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        response = self.client.patch(f"/applications/{application_id}", json={"company_name": "Must Roll Back"})
        self.assertEqual(response.status_code, 500)
        with connect_db(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 1)

    def test_database_unavailable(self):
        self.app.config["DATABASE"] = str(self.path.parent)
        self.assertEqual(self.client.get("/applications").status_code, 500)

    def test_legacy_status_migration_preserves_related_data(self):
        # Reproduce the original constraint in an isolated database.
        old_path = self.path.parent / "legacy.db"
        schema = Path("schema.sql").read_text()
        start = schema.index("CHECK (status IN")
        end = schema.index(")),", start) + 2
        schema = schema[:start] + "CHECK (status IN ('applied', 'interviewing', 'offer', 'rejected', 'withdrawn'))" + schema[end:]
        with connect_db(old_path) as connection:
            connection.executescript(schema)
            connection.execute("INSERT INTO companies (id, name) VALUES (?, ?)", (1, "Legacy"))
            connection.execute("INSERT INTO applications (id, company_id, position, notes) VALUES (?, ?, ?, ?)",
                               (1, 1, "Intern", "Keep me"))
            connection.execute("INSERT INTO interviews (application_id, interview_date, type) VALUES (?, ?, ?)",
                               (1, "2026-11-20", "technical"))
        migrate_statuses(old_path)
        migrate_statuses(old_path)
        with connect_db(old_path) as connection:
            self.assertEqual(connection.execute("SELECT notes FROM applications").fetchone()[0], "Keep me")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM interviews").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            connection.execute("UPDATE applications SET status = ?", ("Assessment",))
        client = create_app({"TESTING": True, "DATABASE": str(old_path)}).test_client()
        self.assertEqual(client.get("/applications/1").json["application"]["status"], "Assessment")
