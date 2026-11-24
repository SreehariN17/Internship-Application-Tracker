"""Flask application and command-line setup."""

from datetime import date
from pathlib import Path
import sqlite3

import click
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from database import connect_db, init_db, migrate_statuses


STATUSES = ("Applied", "Assessment", "Interview", "Offer", "Rejected", "Withdrawn")
LEGACY_STATUSES = {"applied": "Applied", "interviewing": "Interview", "offer": "Offer",
                   "rejected": "Rejected", "withdrawn": "Withdrawn"}
APPLICATION_SELECT = (
    "SELECT a.id, a.company_id, c.name AS company_name, a.position, "
    "a.status, a.applied_date, a.notes FROM applications AS a "
    "JOIN companies AS c ON c.id = a.company_id"
)


def application_json(row):
    result = dict(row)
    result["status"] = LEGACY_STATUSES.get(result["status"], result["status"])
    return result


def validated_body(partial=False):
    """Return cleaned fields or raise ValueError with a useful client message."""
    try:
        data = request.get_json()
    except (BadRequest, UnsupportedMediaType) as error:
        raise ValueError("Send a valid JSON object with Content-Type: application/json.") from error
    if not isinstance(data, dict) or not data:
        raise ValueError("Request body must be a non-empty JSON object.")
    fields = {"company_name", "position", "status", "applied_date", "notes"}
    if data.keys() - fields:
        raise ValueError("Unknown fields: " + ", ".join(sorted(data.keys() - fields)))
    required = fields - {"notes"}
    if not partial and required - data.keys():
        raise ValueError("Missing required fields: " + ", ".join(sorted(required - data.keys())))
    for field in required & data.keys():
        if not isinstance(data[field], str) or not data[field].strip():
            raise ValueError(f"{field} must be a non-empty string.")
    for field in ("company_name", "position"):
        if field in data:
            data[field] = data[field].strip()
    if "status" in data and data["status"] not in STATUSES:
        raise ValueError("status must be one of: " + ", ".join(STATUSES))
    if "applied_date" in data:
        try:
            parsed = date.fromisoformat(data["applied_date"])
            if parsed.isoformat() != data["applied_date"]:
                raise ValueError
        except ValueError as error:
            raise ValueError("applied_date must be a valid date in YYYY-MM-DD format.") from error
    if "notes" in data and data["notes"] is not None and not isinstance(data["notes"], str):
        raise ValueError("notes must be a string or null.")
    return data


def company_id_for(connection, name):
    """Compare trimmed, casefolded names, including existing company records."""
    for company in connection.execute("SELECT id, name FROM companies ORDER BY id"):
        if company["name"].strip().casefold() == name.casefold():
            return company["id"]
    return connection.execute("INSERT INTO companies (name) VALUES (?)", (name,)).lastrowid


def create_app(test_config=None):
    """Create an app; tests can override the database path."""
    app = Flask(__name__, instance_relative_config=True)
    app.config["DATABASE"] = str(Path(app.instance_path) / "tracker.db")
    if test_config is not None:
        app.config.update(test_config)

    @app.get("/")
    def dashboard():
        """Serve the read-only application dashboard."""
        return render_template("index.html")

    @app.get("/health")
    def health():
        """Report that the API is running (does not check database readiness)."""
        return jsonify(status="ok"), 200

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        app.logger.error("Database request failed: %s", error)
        return jsonify(error="Database operation failed."), 500

    @app.get("/applications")
    def list_applications():
        status = request.args.get("status")
        if status is not None and status not in STATUSES:
            return jsonify(error="status must be one of: " + ", ".join(STATUSES)), 400

        query = APPLICATION_SELECT
        parameters = []
        if status is not None:
            # Include old stored labels that represent the requested API status.
            parameters = [status] + [
                legacy for legacy, current in LEGACY_STATUSES.items() if current == status
            ]
            placeholders = ", ".join("?" for _ in parameters)
            query += f" WHERE a.status IN ({placeholders})"
        query += " ORDER BY a.applied_date DESC, a.id DESC"
        with connect_db(app.config["DATABASE"]) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return jsonify(applications=[application_json(row) for row in rows])

    @app.get("/statistics")
    def statistics():
        """Return application totals, including a count for every API status."""
        with connect_db(app.config["DATABASE"]) as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM applications GROUP BY status"
            ).fetchall()
        by_status = {status: 0 for status in STATUSES}
        total_applications = 0
        for row in rows:
            count = row["count"]
            total_applications += count
            label = LEGACY_STATUSES.get(row["status"], row["status"])
            if label in by_status:
                by_status[label] += count
        return jsonify(total_applications=total_applications, by_status=by_status)

    @app.get("/applications/<int:application_id>")
    def get_application(application_id):
        with connect_db(app.config["DATABASE"]) as connection:
            row = connection.execute(APPLICATION_SELECT + " WHERE a.id = ?", (application_id,)).fetchone()
        if row is None:
            return jsonify(error="Application not found."), 404
        return jsonify(application=application_json(row))

    @app.post("/applications")
    def create_application():
        try:
            data = validated_body()
        except ValueError as error:
            return jsonify(error=str(error)), 400
        with connect_db(app.config["DATABASE"]) as connection:
            # Acquire the write lock before company lookup to prevent duplicate creation.
            connection.execute("BEGIN IMMEDIATE")
            company_id = company_id_for(connection, data["company_name"])
            cursor = connection.execute(
                "INSERT INTO applications (company_id, position, status, applied_date, notes) "
                "VALUES (?, ?, ?, ?, ?)",
                (company_id, data["position"], data["status"], data["applied_date"], data.get("notes")),
            )
            row = connection.execute(APPLICATION_SELECT + " WHERE a.id = ?", (cursor.lastrowid,)).fetchone()
        return jsonify(application=application_json(row)), 201, {"Location": f"/applications/{row['id']}"}

    @app.patch("/applications/<int:application_id>")
    def update_application(application_id):
        try:
            data = validated_body(partial=True)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        with connect_db(app.config["DATABASE"]) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT id FROM applications WHERE id = ?", (application_id,)).fetchone() is None:
                return jsonify(error="Application not found."), 404
            if "company_name" in data:
                data["company_id"] = company_id_for(connection, data.pop("company_name"))
            # Column names come only from validated fields above; all values are bound.
            assignments = ", ".join(f"{field} = ?" for field in data)
            connection.execute(
                f"UPDATE applications SET {assignments} WHERE id = ?",
                (*data.values(), application_id),
            )
            row = connection.execute(APPLICATION_SELECT + " WHERE a.id = ?", (application_id,)).fetchone()
        return jsonify(application=application_json(row))

    @app.delete("/applications/<int:application_id>")
    def delete_application(application_id):
        with connect_db(app.config["DATABASE"]) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT id FROM applications WHERE id = ?", (application_id,)).fetchone() is None:
                return jsonify(error="Application not found."), 404
            if connection.execute("SELECT id FROM interviews WHERE application_id = ? LIMIT 1", (application_id,)).fetchone():
                return jsonify(error="Application has related interviews and cannot be deleted."), 409
            connection.execute("DELETE FROM applications WHERE id = ?", (application_id,))
        return "", 204

    @app.cli.command("migrate-statuses")
    def migrate_statuses_command():
        """Expand status choices in an existing database, preserving its data."""
        try:
            migrate_statuses(app.config["DATABASE"])
        except (sqlite3.Error, OSError, ValueError) as error:
            raise click.ClickException(f"Status migration failed: {error}") from error
        click.echo("Status migration complete.")

    @app.cli.command("init-db")
    def init_db_command():
        """Create missing database tables without deleting existing data."""
        try:
            init_db(app.config["DATABASE"])
        except (sqlite3.Error, OSError) as error:
            raise click.ClickException(f"Database initialization failed: {error}") from error
        click.echo("Database initialized.")

    return app


if __name__ == "__main__":
    create_app().run()
