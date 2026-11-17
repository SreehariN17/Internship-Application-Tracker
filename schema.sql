-- Re-running this file preserves existing tables and data.
-- Foreign keys must also be enabled on each connection (see database.py).
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    website TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL,
    position TEXT NOT NULL CHECK (length(trim(position)) > 0),
    status TEXT NOT NULL DEFAULT 'applied'
        CHECK (status IN ('applied', 'interviewing', 'offer', 'rejected', 'withdrawn')),
    applied_date TEXT NOT NULL DEFAULT (date('now')),
    notes TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_applications_company_id
    ON applications(company_id);

CREATE TABLE IF NOT EXISTS interviews (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL,
    interview_date TEXT NOT NULL CHECK (length(trim(interview_date)) > 0),
    type TEXT NOT NULL CHECK (length(trim(type)) > 0),
    FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_interviews_application_id
    ON interviews(application_id);
