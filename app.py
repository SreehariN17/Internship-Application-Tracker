"""Flask application and command-line setup."""

from pathlib import Path
import sqlite3

import click
from flask import Flask, jsonify

from database import init_db


def create_app(test_config=None):
    """Create an app; tests can override the database path."""
    app = Flask(__name__, instance_relative_config=True)
    app.config["DATABASE"] = str(Path(app.instance_path) / "tracker.db")
    if test_config is not None:
        app.config.update(test_config)

    @app.get("/health")
    def health():
        """Report that the API is running (does not check database readiness)."""
        return jsonify(status="ok"), 200

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
