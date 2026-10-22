import json
import os

import click

from .backup import import_data, name_from_filename
from .extensions import db
from .models import AdminUser


def ensure_admin(username: str, password: str) -> AdminUser:
    user = AdminUser.query.filter_by(username=username).first()
    if user is None:
        user = AdminUser(username=username)
        db.session.add(user)
    user.set_password(password)
    db.session.commit()
    return user


def register_cli(app):
    @app.cli.command("ensure-admin")
    def ensure_admin_cmd():
        """Create/update the TD login from ADMIN_USERNAME and ADMIN_PASSWORD."""
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD")
        if not password:
            click.echo("ADMIN_PASSWORD is not set; skipping admin bootstrap.")
            return
        if len(password) < 8:
            raise click.ClickException("ADMIN_PASSWORD must be at least 8 characters.")
        ensure_admin(username, password)
        click.echo(f"Admin user '{username}' is ready.")

    @app.cli.command("import-legacy")
    @click.argument("files", nargs=-1, type=click.Path(exists=True, dir_okay=False))
    def import_legacy_cmd(files):
        """Import old atu-scrabble-engine data/*.json files (or Bracketeer backups)."""
        for path in files:
            with open(path, encoding="utf-8") as f:
                t = import_data(json.load(f), name_from_filename(path))
            click.echo(f"Imported {path} -> {t.name} ({len(t.participants)} players, {len(t.games)} games)")

    @app.cli.command("init-db")
    def init_db_cmd():
        """Create tables directly (handy for quick local testing; production uses `flask db upgrade`)."""
        db.create_all()
        click.echo("Tables created.")
