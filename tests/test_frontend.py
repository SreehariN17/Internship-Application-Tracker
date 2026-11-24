"""Dashboard page and static assets, using an isolated temporary database."""

from pathlib import Path
from html.parser import HTMLParser
import tempfile
import unittest

from app import create_app
from database import init_db


class DashboardParser(HTMLParser):
    """Inspect form attributes using the standard library, without dependencies."""
    def __init__(self):
        super().__init__()
        self.elements = {}
        self.options = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.elements[attributes["id"]] = (tag, attributes)
        if tag == "option":
            self.options.append(attributes)


class FrontendTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database_path = Path(directory.name) / "test.db"
        init_db(database_path)
        app = create_app({"TESTING": True, "DATABASE": str(database_path)})
        self.client = app.test_client()

    def test_dashboard_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/html")
        html = response.get_data(as_text=True)
        self.assertIn("ScarletTrack", html)
        self.assertIn("<h1>Your career dashboard</h1>", html)
        self.assertIn("Your career journey starts here.", html)
        self.assertIn("Built by Rutgers students, for students.", html)

    def parse_dashboard(self):
        parser = DashboardParser()
        parser.feed(self.client.get("/").get_data(as_text=True))
        return parser

    def test_accessible_add_application_dialog(self):
        elements = self.parse_dashboard().elements
        self.assertEqual(elements["application-dialog"][0], "dialog")
        self.assertEqual(elements["application-dialog"][1]["aria-labelledby"], "dialog-title")
        self.assertEqual(elements["application-form"][0], "form")
        self.assertEqual(elements["add-application"][1]["aria-controls"], "application-dialog")
        for button in ("close-dialog", "cancel-dialog", "submit-application"):
            self.assertEqual(elements[button][0], "button")

    def test_application_fields(self):
        elements = self.parse_dashboard().elements
        for field_id, name in (("company-name", "company_name"), ("position", "position"),
                               ("status", "status"), ("applied-date", "applied_date")):
            with self.subTest(field=field_id):
                attrs = elements[field_id][1]
                self.assertEqual(attrs["name"], name)
                self.assertIn("required", attrs)
        self.assertEqual(elements["applied-date"][1]["type"], "date")
        self.assertEqual(elements["notes"][0], "textarea")
        self.assertEqual(elements["notes"][1]["name"], "notes")
        self.assertNotIn("required", elements["notes"][1])

    def test_status_options_and_default(self):
        options = self.parse_dashboard().options
        self.assertEqual([option["value"] for option in options],
                         ["Applied", "Assessment", "Interview", "Offer", "Rejected", "Withdrawn"])
        self.assertEqual([option["value"] for option in options if "selected" in option], ["Applied"])

    def test_optional_resources_section(self):
        elements = self.parse_dashboard().elements
        self.assertEqual(elements["resource-fields"][0], "details")
        self.assertNotIn("open", elements["resource-fields"][1])
        for field_id in ("job-posting-url", "application-portal-url"):
            self.assertEqual(elements[field_id][1]["type"], "url")
            self.assertEqual(elements[field_id][1]["maxlength"], "2048")
            self.assertNotIn("required", elements[field_id][1])
        self.assertEqual(elements["add-email-link"][1]["type"], "button")
        self.assertIn("email-link-rows", elements)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Application Resources (Optional)", html)
        self.assertIn('<th scope="col">Resources</th>', html)

    def test_dashboard_links_static_assets(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('href="/static/style.css"', html)
        self.assertIn('src="/static/script.js"', html)

    def test_stylesheet_accessible(self):
        response = self.client.get("/static/style.css")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/css")
        self.assertTrue(response.get_data())

    def test_javascript_accessible(self):
        response = self.client.get("/static/script.js")
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.mimetype, ("text/javascript", "application/javascript"))
        self.assertTrue(response.get_data())
