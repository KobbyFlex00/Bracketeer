import json
import os

import click

from . import onchain
from .backup import import_data, name_from_filename
from .extensions import db
from .models import AdminUser, Tournament


def ensure_admin(username: str, password: str) -> AdminUser:
    """The bootstrap login from ADMIN_USERNAME / ADMIN_PASSWORD is always a super admin."""
    user = AdminUser.query.filter_by(username=username).first()
    if user is None:
        user = AdminUser(username=username, sports=[])
        db.session.add(user)
    user.is_super = True
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

    def _by_slug(slug):
        t = Tournament.query.filter_by(slug=slug).first()
        if t is None:
            raise click.ClickException(f"No tournament with slug {slug!r}.")
        return t

    @app.cli.command("onchain-publish")
    @click.argument("slug", required=False)
    @click.option("--all-finished", is_flag=True, help="Publish every finished tournament whose results changed.")
    def onchain_publish_cmd(slug, all_finished):
        """Publish result fingerprints to the Stellar results registry."""
        if bool(slug) == all_finished:
            raise click.ClickException("Give one tournament slug, or --all-finished.")
        targets = Tournament.query.filter_by(status="finished").order_by(Tournament.id).all() if all_finished else [_by_slug(slug)]
        for t in targets:
            try:
                anchor, created = onchain.publish(t, by="cli")
            except onchain.OnchainError as e:
                raise click.ClickException(f"{t.slug}: {e}") from None
            state = "published" if created else "already up to date"
            link = f" {onchain.explorer_url('tx', anchor.tx_hash)}" if anchor.tx_hash else ""
            click.echo(f"{t.slug}: v{anchor.version} {state} ({anchor.hash[:12]}…){link}")

    @app.cli.command("onchain-verify")
    @click.argument("slug")
    def onchain_verify_cmd(slug):
        """Compare a tournament's current results with its latest fingerprint onchain."""
        if not onchain.enabled():
            raise click.ClickException("STELLAR_CONTRACT_ID is not set.")
        result = onchain.verify(_by_slug(slug))
        click.echo(f"site:    {result['local']}")
        rec = result["onchain"]
        click.echo(f"onchain: {rec['hash']} (v{rec['version']}, ledger {rec['ledger']})" if rec else "onchain: not published")
        click.echo("MATCH" if result["match"] else "MISMATCH" if rec else "NOT PUBLISHED")
        if rec and not result["match"]:
            raise SystemExit(1)

    @app.cli.command("onchain-extend")
    def onchain_extend_cmd():
        """Keep every published version alive on Stellar (run every few months)."""
        if not onchain.can_publish():
            raise click.ClickException("STELLAR_CONTRACT_ID and STELLAR_SECRET_KEY must be set.")
        click.echo(f"Extended in {onchain.extend_all()} call(s).")
