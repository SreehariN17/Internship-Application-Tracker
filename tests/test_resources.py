"""Resource CRUD and migration checks; all databases live in temporary folders."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app import create_app
from database import connect_db, init_db, migrate_resources, migrate_statuses


# A pre-resource, pre-status-migration database, independent of the new schema.
LEGACY_SCHEMA = """
CREATE TABLE companies (id INTEGER PRIMARY KEY, name TEXT NOT NULL, website TEXT);
CREATE TABLE applications (
    id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, position TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'applied'
        CHECK (status IN ('applied', 'interviewing', 'offer', 'rejected', 'withdrawn')),
    applied_date TEXT NOT NULL DEFAULT (date('now')), notes TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT
);
CREATE INDEX idx_applications_company_id ON applications(company_id);
CREATE TABLE interviews (
    id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL,
    interview_date TEXT NOT NULL, type TEXT NOT NULL,
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE RESTRICT
);
CREATE INDEX idx_interviews_application_id ON interviews(application_id);
"""


class ResourceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'test.db'
        init_db(self.path)
        self.app = create_app({'TESTING': True, 'DATABASE': str(self.path)})
        self.client = self.app.test_client()
        self.base = dict(company_name='Example', position='Intern', status='Applied',
                         applied_date='2026-11-23', notes='Keep notes')
        self.resources = dict(job_posting_url='https://example.com/jobs/123',
                              application_portal_url='https://example.com/portal',
                              email_links=[{'label': 'Assessment', 'url': 'https://mail.google.com/mail/u/0/#inbox/abc'},
                                           {'label': 'Recruiter', 'url': 'https://outlook.office.com/mail/inbox/id/abc'}])

    def create(self, **fields):
        response = self.client.post('/applications', json={**self.base, **fields})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json['application']

    def test_without_resources(self):
        application = self.create()
        self.assertIsNone(application['job_posting_url'])
        self.assertIsNone(application['application_portal_url'])
        self.assertEqual(application['email_links'], [])

    def test_create_and_both_get_endpoints(self):
        application = self.create(**self.resources)
        for key, value in self.resources.items():
            self.assertEqual(application[key], value)
        self.assertEqual(self.client.get('/applications').json, {'applications': [application]})
        self.assertEqual(self.client.get(f"/applications/{application['id']}").json, {'application': application})

    def test_filter_order_and_resources(self):
        old = self.create(**self.resources, status='Interview', applied_date='2026-01-01')
        first = self.create(**self.resources, status='Interview')
        last = self.create(**self.resources, status='Interview')
        self.create(status='Offer')
        with connect_db(self.path) as connection:
            connection.execute('UPDATE applications SET status = ? WHERE id = ?', ('interviewing', old['id']))
        response = self.client.get('/applications?status=Interview')
        self.assertEqual(response.json, {'applications': [last, first, old]})

    def test_update_urls_clear_and_preserve_omitted_fields(self):
        original = self.create(**self.resources)
        url = f"/applications/{original['id']}"
        updated = self.client.patch(url, json={'job_posting_url': 'https://example.org/new'}).json['application']
        self.assertEqual(updated, {**original, 'job_posting_url': 'https://example.org/new'})
        response = self.client.patch(url, json={'job_posting_url': '  ', 'application_portal_url': None})
        self.assertEqual(response.status_code, 200)
        cleared = response.json['application']
        self.assertEqual(cleared, {**original, 'job_posting_url': None, 'application_portal_url': None})
        self.assertEqual(self.create(job_posting_url='', application_portal_url='  ')['job_posting_url'], None)

    def test_replace_and_clear_emails_only(self):
        original = self.create(**self.resources)
        url = f"/applications/{original['id']}"
        links = [{'label': "Recruiter's update", 'url': 'https://example.org/email?x=1&y=2'}]
        response = self.client.patch(url, json={'email_links': links})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['application'], {**original, 'email_links': links})
        response = self.client.patch(url, json={'email_links': []})
        self.assertEqual(response.json['application'], {**original, 'email_links': []})
        response = self.client.patch(url, json={'status': 'Offer'})
        self.assertEqual(response.json['application']['job_posting_url'], original['job_posting_url'])

    def test_invalid_urls_in_post_and_patch(self):
        original = self.create(**self.resources)
        bad_urls = ['javascript:alert(1)', 'data:text/html,hello', 'file:///etc/passwd', '/relative',
                    '//example.com', 'https://', 'https://user:pass@example.com', 'https://@example.com',
                    'https://exam ple.com', 'https://example.com/a\nb', 'https://example.com:bad',
                    'https://example.com:99999', 'https://[broken', 'https://example.com/%zz',
                    'https://[::1]junk', 'https://example.com/<script>',
                    'https://example.com\\@evil.com', 'https://-bad.com', 'https://foo..com',
                    'https://example.com/' + 'x' * 2048, 1, True, [], {}]
        for bad in bad_urls:
            for field in ('job_posting_url', 'application_portal_url', 'email_links'):
                data = {field: [{'label': 'Test', 'url': bad}] if field == 'email_links' else bad}
                with self.subTest(value=bad, field=field):
                    for response in (self.client.post('/applications', json={**self.base, **data}),
                                     self.client.patch(f"/applications/{original['id']}", json=data)):
                        self.assertEqual(response.status_code, 400)
                        self.assertIn('error', response.json)
        self.assertEqual(self.client.get(f"/applications/{original['id']}").json['application'], original)

    def test_email_shape_limits_and_labels(self):
        invalid = [None, {}, 'text', [None], ['text'], [{}], [{'label': 'Only'}],
                   [{'label': 'X', 'url': 'https://example.com', 'other': 1}],
                   [{'label': 1, 'url': 'https://example.com'}],
                   [{'label': '  ', 'url': 'https://example.com'}],
                   [{'label': 'X' * 121, 'url': 'https://example.com'}],
                   [{'label': 'X', 'url': ''}], [{'label': 'X', 'url': None}],
                   [{'label': 'X', 'url': 'https://example.com'}] * 21]
        original = self.create()
        for links in invalid:
            with self.subTest(links=links):
                for response in (self.client.post('/applications', json={**self.base, 'email_links': links}),
                                 self.client.patch(f"/applications/{original['id']}", json={'email_links': links})):
                    self.assertEqual(response.status_code, 400)
                    self.assertIn('email_links', response.json['error'])
        self.assertEqual(len(self.create(email_links=[{'label': 'X', 'url': 'https://example.com'}] * 20)['email_links']), 20)

    def test_url_normalization_and_valid_variants(self):
        for url in ('http://localhost:5000/job', 'https://[::1]/job', 'https://example.com/a%20b?q=1#part',
                    'https://例え.jp/job'):
            with self.subTest(url=url):
                self.assertEqual(self.create(job_posting_url='  ' + url + '  ')['job_posting_url'], url)
        application = self.create(email_links=[{'label': '  Invite  ', 'url': 'https://example.com'}])
        self.assertEqual(application['email_links'][0]['label'], 'Invite')

    def test_post_email_failure_rolls_back_everything(self):
        with connect_db(self.path) as connection:
            connection.execute("CREATE TRIGGER fail_email BEFORE INSERT ON application_email_links "
                               "WHEN NEW.label = 'Recruiter' BEGIN SELECT RAISE(ABORT, 'forced'); END")
        response = self.client.post('/applications', json={**self.base, **self.resources})
        self.assertEqual(response.status_code, 500)
        with connect_db(self.path) as connection:
            for table in ('companies', 'applications', 'application_email_links'):
                self.assertEqual(connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    def test_patch_email_failure_rolls_back_replacement_and_fields(self):
        original = self.create(**self.resources)
        with connect_db(self.path) as connection:
            connection.execute("CREATE TRIGGER fail_email BEFORE INSERT ON application_email_links "
                               "BEGIN SELECT RAISE(ABORT, 'forced'); END")
        response = self.client.patch(f"/applications/{original['id']}", json={
            'company_name': 'Should roll back', 'job_posting_url': None, 'notes': 'Changed',
            'email_links': [{'label': 'New', 'url': 'https://example.com'}]})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.client.get(f"/applications/{original['id']}").json['application'], original)
        with connect_db(self.path) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM companies').fetchone()[0], 1)

    def test_cascade_and_interview_restriction(self):
        application = self.create(**self.resources)
        self.assertEqual(self.client.delete(f"/applications/{application['id']}").status_code, 204)
        with connect_db(self.path) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM application_email_links').fetchone()[0], 0)
        protected = self.create(**self.resources)
        with connect_db(self.path) as connection:
            connection.execute('INSERT INTO interviews (application_id, interview_date, type) VALUES (?, ?, ?)',
                               (protected['id'], '2026-12-01', 'technical'))
        self.assertEqual(self.client.delete(f"/applications/{protected['id']}").status_code, 409)
        self.assertEqual(self.client.get(f"/applications/{protected['id']}").json['application'], protected)

    def test_listing_uses_batch_read(self):
        for number in range(8):
            self.create(**self.resources)
        statements = []
        @contextmanager
        def traced(path):
            with connect_db(path) as connection:
                connection.set_trace_callback(statements.append)
                yield connection
        with patch('app.connect_db', traced):
            self.assertEqual(self.client.get('/applications').status_code, 200)
        selects = [sql for sql in statements if sql.startswith('SELECT')]
        self.assertEqual(len(selects), 2)

    def test_schema_constraints_and_foreign_key(self):
        application = self.create()
        with connect_db(self.path) as connection:
            key = connection.execute('PRAGMA foreign_key_list(application_email_links)').fetchone()
            self.assertEqual((key['table'], key['from'], key['to'], key['on_delete']),
                             ('applications', 'application_id', 'id', 'CASCADE'))
            self.assertIn('idx_application_email_links_application_id',
                          [row['name'] for row in connection.execute('PRAGMA index_list(application_email_links)')])
            for label, url in [(' ', 'https://example.com'), ('Test', '')]:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute('INSERT INTO application_email_links (application_id, label, url) VALUES (?, ?, ?)',
                                       (application['id'], label, url))


class ResourceMigrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'legacy.db'
        with connect_db(self.path) as connection:
            connection.executescript(LEGACY_SCHEMA)
            connection.execute('INSERT INTO companies (id, name, website) VALUES (?, ?, ?)', (7, 'Legacy', 'https://example.com'))
            connection.execute('INSERT INTO applications (id, company_id, position, status, applied_date, notes) VALUES (?, ?, ?, ?, ?, ?)',
                               (13, 7, 'Intern', 'interviewing', '2026-01-01', 'Keep notes'))
            connection.execute('INSERT INTO interviews (id, application_id, interview_date, type) VALUES (?, ?, ?, ?)',
                               (19, 13, '2026-12-01', 'technical'))
        self.original = self.snapshot()

    def snapshot(self):
        with connect_db(self.path) as connection:
            return {table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY id')]
                    for table in ('companies', 'applications', 'interviews')}

    def assert_preserved(self):
        current = self.snapshot()
        self.assertEqual(current['companies'], self.original['companies'])
        self.assertEqual(current['interviews'], self.original['interviews'])
        original_application = self.original['applications'][0]
        self.assertEqual(current['applications'][0][:len(original_application)], original_application)
        with connect_db(self.path) as connection:
            self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_resources_upgrade_repeat_and_cli(self):
        app = create_app({'TESTING': True, 'DATABASE': str(self.path)})
        runner = app.test_cli_runner()
        for _ in range(2):
            result = runner.invoke(args=['migrate-resources'])
            self.assertEqual(result.exit_code, 0, result.output)
        self.assert_preserved()
        with connect_db(self.path) as connection:
            self.assertEqual(connection.execute('SELECT job_posting_url FROM applications').fetchone()[0], None)

    def test_partial_upgrade_adds_only_missing_column(self):
        with connect_db(self.path) as connection:
            connection.execute('ALTER TABLE applications ADD COLUMN job_posting_url TEXT')
            connection.execute('UPDATE applications SET job_posting_url = ?', ('https://example.com/job',))
        migrate_resources(self.path)
        self.assert_preserved()
        with connect_db(self.path) as connection:
            self.assertEqual(connection.execute('SELECT job_posting_url FROM applications').fetchone()[0], 'https://example.com/job')

    def test_resources_then_statuses_preserves_links_and_custom_columns(self):
        migrate_resources(self.path)
        with connect_db(self.path) as connection:
            interview_sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='interviews'").fetchone()[0]
            connection.execute('UPDATE applications SET job_posting_url = ?, application_portal_url = ?',
                               ('https://example.com/job', 'https://example.com/portal'))
            connection.execute('ALTER TABLE applications ADD COLUMN teammate_field TEXT')
            connection.execute('UPDATE applications SET teammate_field = ?', ('Keep extra field',))
            connection.execute('CREATE INDEX custom_application_index ON applications(position)')
            connection.execute("CREATE TRIGGER keep_trigger AFTER UPDATE ON applications BEGIN SELECT 1; END")
            connection.execute('INSERT INTO application_email_links (id, application_id, label, url) VALUES (?, ?, ?, ?)',
                               (23, 13, 'Invitation', 'https://example.com/email'))
        for _ in range(2):
            migrate_statuses(self.path)
            migrate_resources(self.path)
        self.assert_preserved()
        with connect_db(self.path) as connection:
            self.assertEqual(tuple(connection.execute('SELECT * FROM application_email_links').fetchone()),
                             (23, 13, 'Invitation', 'https://example.com/email'))
            self.assertEqual(tuple(connection.execute('SELECT job_posting_url, application_portal_url, teammate_field FROM applications').fetchone()),
                             ('https://example.com/job', 'https://example.com/portal', 'Keep extra field'))
            self.assertEqual(connection.execute("SELECT sql FROM sqlite_master WHERE name='interviews'").fetchone()[0], interview_sql)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name IN ('custom_application_index','keep_trigger')").fetchone()[0], 2)
            connection.execute('UPDATE applications SET status = ?', ('Assessment',))

    def test_statuses_then_resources(self):
        for migration in (migrate_statuses, migrate_resources, migrate_statuses, migrate_resources):
            migration(self.path)
        self.assert_preserved()
        client = create_app({'TESTING': True, 'DATABASE': str(self.path)}).test_client()
        response = client.get('/applications/13')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['application']['status'], 'Interview')
        self.assertEqual(response.json['application']['email_links'], [])

    def test_fresh_initialization_and_repeat_migrations(self):
        path = self.path.parent / 'fresh.db'
        init_db(path)
        for _ in range(2):
            migrate_resources(path)
            migrate_statuses(path)
            init_db(path)
        with connect_db(path) as connection:
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertIn('application_portal_url', [row['name'] for row in connection.execute('PRAGMA table_info(applications)')])

    def test_migration_failure_rolls_back_and_keeps_data(self):
        # Seed a pre-existing integrity problem without touching the real database.
        with connect_db(self.path) as connection:
            connection.execute('PRAGMA foreign_keys = OFF')
            connection.execute('UPDATE applications SET company_id = ?', (999,))
        before = self.snapshot()
        for migration in (migrate_resources, migrate_statuses):
            with self.assertRaises(sqlite3.IntegrityError):
                migration(self.path)
            self.assertEqual(self.snapshot(), before)
        with connect_db(self.path) as connection:
            self.assertNotIn('job_posting_url', [row['name'] for row in connection.execute('PRAGMA table_info(applications)')])
            self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
