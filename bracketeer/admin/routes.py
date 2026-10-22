import csv
import io
import json

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..backup import export_tournament, import_data, name_from_filename
from ..engine import PairingError, delete_round, generate_round, unique_slug
from ..extensions import db
from ..models import PENDING, Game, Participant, Tournament
from ..sports import SPORTS

bp = Blueprint("admin", __name__, url_prefix="/admin")

STATUSES = ("upcoming", "live", "finished")
TABS = ("overview", "participants", "rounds", "settings", "export")


@bp.before_request
@login_required
def _require_login():
    pass


def _tournament(tid) -> Tournament:
    return db.get_or_404(Tournament, tid)


def _back(t, tab, **kw):
    return redirect(url_for("admin.tournament", tid=t.id, tab=tab, **kw))


def _clean_name(value, label="Name", upper=False):
    value = " ".join((value or "").split())
    if not value:
        raise ValueError(f"{label} is required.")
    if len(value) > 120:
        raise ValueError(f"{label} is too long.")
    return value.upper() if upper else value


def _rating(value, default):
    try:
        return int(value) if str(value or "").strip() else default
    except ValueError:
        raise ValueError("Rating must be a whole number.") from None


def default_system(t):
    if t.sport == "football":
        return {"double_league": "double_rr", "knockout": "knockout"}.get(t.format, "rr")
    return {"round_robin": "rr", "double_round_robin": "double_rr"}.get(t.format, "swiss")


# ---------- tournaments ----------

@bp.route("/")
def home():
    sport = request.args.get("sport", "scrabble")
    if sport not in SPORTS:
        sport = "scrabble"
    tournaments = Tournament.query.filter_by(sport=sport).order_by(Tournament.created_at.desc()).all()
    counts = {k: Tournament.query.filter_by(sport=k).count() for k in SPORTS}
    return render_template("admin/home.html", sport=SPORTS[sport], tournaments=tournaments, counts=counts)


@bp.route("/tournaments", methods=["POST"])
def create_tournament():
    sport_key = request.form.get("sport")
    rules = SPORTS.get(sport_key)
    try:
        if rules is None:
            raise ValueError("Pick a sport.")
        name = _clean_name(request.form.get("name"), "Tournament name")
        fmt = request.form.get("format")
        if fmt not in rules.formats:
            raise ValueError("Pick a format.")
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.home", sport=sport_key))
    t = Tournament(name=name, slug=unique_slug(name), sport=rules.key, format=fmt, status="upcoming",
                   venue=(request.form.get("venue") or "").strip()[:120], settings={})
    db.session.add(t)
    db.session.commit()
    flash(f"Created {t.name}. Add {rules.participant_plural.lower()} next.", "success")
    return _back(t, "participants")


@bp.route("/import", methods=["POST"])
def import_file():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose a .json file to import.", "danger")
        return redirect(url_for("admin.home"))
    try:
        data = json.load(upload.stream)
        t = import_data(data, name_from_filename(upload.filename))
    except (ValueError, KeyError, TypeError) as e:
        db.session.rollback()
        flash(f"Import failed: {e}", "danger")
        return redirect(url_for("admin.home"))
    flash(f"Imported {t.name} ({len(t.participants)} {t.rules.participant_plural.lower()}, {len(t.games)} games).", "success")
    return _back(t, "overview")


@bp.route("/t/<int:tid>")
def tournament(tid):
    t = _tournament(tid)
    tab = request.args.get("tab", "overview")
    if tab not in TABS:
        tab = "overview"
    rounds = sorted({g.round for g in t.games}, reverse=True)
    return render_template(
        "admin/tournament.html", t=t, rules=t.rules, tab=tab, rounds=rounds,
        standings=t.rules.standings(t), statuses=STATUSES, default_system=default_system(t),
        active=[p for p in t.participants if p.active],
    )


@bp.route("/t/<int:tid>/settings", methods=["POST"])
def update_settings(tid):
    t = _tournament(tid)
    f = request.form
    try:
        name = _clean_name(f.get("name"), "Tournament name")
        if name != t.name:
            t.name, t.slug = name, unique_slug(name, exclude_id=t.id)
        if f.get("format") in t.rules.formats:
            t.format = f["format"]
        if f.get("status") in STATUSES:
            t.status = f["status"]
        t.venue = (f.get("venue") or "").strip()[:120]
        settings = dict(t.settings or {})
        for key, cast in (("bye_spread", int), ("bye_points", float), ("elo_k", int), ("ko_teams", int),
                          ("win_points", int), ("rr_offset", int)):
            if f.get(key, "").strip() != "":
                settings[key] = cast(f[key])
        if "team_battle_present" in f:
            settings["team_battle"] = bool(f.get("team_battle"))
        t.settings = settings
    except ValueError as e:
        flash(str(e) if "required" in str(e) or "long" in str(e) else "Settings must be numbers.", "danger")
        return _back(t, "settings")
    db.session.commit()
    flash("Settings saved.", "success")
    return _back(t, "settings")


@bp.route("/t/<int:tid>/delete", methods=["POST"])
def delete_tournament(tid):
    t = _tournament(tid)
    if request.form.get("confirm_name", "").strip() != t.name:
        flash("Type the tournament name exactly to confirm deletion.", "danger")
        return _back(t, "settings")
    sport = t.sport
    db.session.delete(t)
    db.session.commit()
    flash("Tournament deleted.", "success")
    return redirect(url_for("admin.home", sport=sport))


@bp.route("/t/<int:tid>/export.json")
def export_json(tid):
    t = _tournament(tid)
    body = json.dumps(export_tournament(t), indent=2)
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{t.slug}-backup.json"'})


# ---------- participants ----------

def _add_participant(t, name, club, rating):
    p = Participant(tournament=t, name=name, club=club, seed_rating=rating)
    db.session.add(p)
    return p


@bp.route("/t/<int:tid>/participants", methods=["POST"])
def add_participant(tid):
    t = _tournament(tid)
    upper = t.sport == "scrabble"
    try:
        name = _clean_name(request.form.get("name"), upper=upper)
        club = " ".join((request.form.get("club") or "").split())[:120]
        _add_participant(t, name, club.upper() if upper else club, _rating(request.form.get("rating"), t.rules.default_rating))
    except ValueError as e:
        flash(str(e), "danger")
        return _back(t, "participants")
    db.session.commit()
    flash(f"Added {name}.", "success")
    return _back(t, "participants")


@bp.route("/t/<int:tid>/participants/bulk", methods=["POST"])
def bulk_participants(tid):
    """One per line: Name, Club, Rating (club and rating optional). Also accepts an uploaded CSV."""
    t = _tournament(tid)
    text = request.form.get("lines", "")
    upload = request.files.get("csv")
    if upload and upload.filename:
        text = upload.stream.read().decode("utf-8-sig", errors="replace")
    upper = t.sport == "scrabble"
    added, errors = 0, []
    for i, row in enumerate(csv.reader(io.StringIO(text)), 1):
        cells = [c.strip() for c in row]
        if not cells or not cells[0] or cells[0].lower() == "name":
            continue
        try:
            name = _clean_name(cells[0], upper=upper)
            club = cells[1] if len(cells) > 1 else ""
            rating = _rating(cells[2] if len(cells) > 2 else "", t.rules.default_rating)
            _add_participant(t, name, club.upper() if upper else club, rating)
            added += 1
        except ValueError as e:
            errors.append(f"line {i}: {e}")
    db.session.commit()
    flash(f"Added {added} {t.rules.participant_plural.lower()}.", "success" if added else "warning")
    if errors:
        flash("Skipped " + "; ".join(errors[:5]), "warning")
    return _back(t, "participants")


@bp.route("/t/<int:tid>/participants/<int:pid>", methods=["POST"])
def manage_participant(tid, pid):
    t = _tournament(tid)
    p = db.get_or_404(Participant, pid)
    if p.tournament_id != t.id:
        abort(404)
    action = request.form.get("action")
    if action == "edit":
        try:
            upper = t.sport == "scrabble"
            p.name = _clean_name(request.form.get("name"), upper=upper)
            club = " ".join((request.form.get("club") or "").split())[:120]
            p.club = club.upper() if upper else club
            p.seed_rating = _rating(request.form.get("rating"), p.seed_rating)
        except ValueError as e:
            flash(str(e), "danger")
            return _back(t, "participants")
        flash(f"Updated {p.name}.", "success")
    elif action == "toggle":
        p.active = not p.active
        flash(f"{p.name} {'reinstated' if p.active else 'withdrawn — no longer paired, results kept'}.", "success")
    elif action == "delete":
        if p.has_games():
            flash(f"{p.name} has games recorded. Withdraw them instead so results stay consistent.", "danger")
            return _back(t, "participants")
        db.session.delete(p)
        flash("Removed.", "success")
    db.session.commit()
    return _back(t, "participants")


# ---------- rounds & games ----------

@bp.route("/t/<int:tid>/rounds", methods=["POST"])
def generate(tid):
    t = _tournament(tid)
    try:
        r = generate_round(t, request.form.get("system", default_system(t)))
        flash(f"Round {r} paired.", "success")
    except PairingError as e:
        db.session.rollback()
        flash(str(e), "danger")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return _back(t, "rounds")


@bp.route("/t/<int:tid>/rounds/<int:rnd>/delete", methods=["POST"])
def remove_round(tid, rnd):
    t = _tournament(tid)
    if rnd != t.max_round:
        flash("Only the latest round can be deleted.", "danger")
    else:
        delete_round(t, rnd)
        flash(f"Round {rnd} deleted.", "success")
    return _back(t, "rounds")


def _participant_in(t, raw, allow_none=False):
    if allow_none and (raw in (None, "", "0")):
        return None
    p = db.session.get(Participant, int(raw)) if str(raw).isdigit() else None
    if p is None or p.tournament_id != t.id:
        raise ValueError(f"Pick a valid {t.rules.participant_label.lower()}.")
    return p


def _check_free(t, rnd, people, ignore_game=None):
    for g in t.games_in_round(rnd):
        if g is ignore_game:
            continue
        for p in people:
            if p is not None and p.id in (g.p1_id, g.p2_id):
                raise ValueError(f"{p.name} already has a game in round {rnd}.")


@bp.route("/t/<int:tid>/rounds/<int:rnd>/games", methods=["POST"])
def add_game(tid, rnd):
    t = _tournament(tid)
    try:
        if rnd < 1 or rnd > t.max_round + 1:
            raise ValueError("Invalid round.")
        p1 = _participant_in(t, request.form.get("p1"))
        p2 = _participant_in(t, request.form.get("p2"), allow_none=True)
        if p2 is not None and p1.id == p2.id:
            raise ValueError("Pick two different opponents.")
        _check_free(t, rnd, (p1, p2))
        stage = request.form.get("stage") or ("league" if t.sport == "football" else "main")
        board = max((g.board for g in t.games_in_round(rnd)), default=0) + 1
        g = Game(tournament=t, round=rnd, stage=stage, board=board, p1=p1, p2=p2, result=PENDING)
        if p2 is None:
            t.rules.bye_result(t, g)
        db.session.add(g)
        db.session.commit()
        flash(f"Game added to round {rnd}.", "success")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return _back(t, "rounds", round=rnd)


def _game(t, gid) -> Game:
    g = db.get_or_404(Game, gid)
    if g.tournament_id != t.id:
        abort(404)
    return g


@bp.route("/t/<int:tid>/games/<int:gid>", methods=["POST"])
def update_game(tid, gid):
    t = _tournament(tid)
    g = _game(t, gid)
    action = request.form.get("action", "result")
    try:
        if action == "result":
            if g.p2_id is None:
                raise ValueError("Byes are scored automatically.")
            t.rules.record_result(g, request.form)
            msg = f"Saved: {g.p1.name} {t.rules.score_text(g)} {g.p2.name}"
        elif action == "clear":
            g.result, g.score1, g.score2, g.spread, g.pen_winner = PENDING, None, None, None, None
            if g.p2_id is None:
                t.rules.bye_result(t, g)
            msg = "Result cleared."
        elif action == "swap":
            if g.p2_id is None:
                raise ValueError("A bye has only one side.")
            g.p1_id, g.p2_id = g.p2_id, g.p1_id
            g.score1, g.score2 = g.score2, g.score1
            g.spread = -g.spread if g.spread is not None else None
            g.pen_winner = {1: 2, 2: 1}.get(g.pen_winner)
            g.result = t.rules.flip(g.result)
            msg = "Sides swapped."
        elif action == "repair":
            p1 = _participant_in(t, request.form.get("p1"))
            p2 = _participant_in(t, request.form.get("p2"), allow_none=True)
            if p2 is not None and p1.id == p2.id:
                raise ValueError("Pick two different opponents.")
            _check_free(t, g.round, (p1, p2), ignore_game=g)
            g.p1, g.p2 = p1, p2
            g.result, g.score1, g.score2, g.spread, g.pen_winner = PENDING, None, None, None, None
            if p2 is None:
                t.rules.bye_result(t, g)
            msg = "Pairing changed — re-enter the result."
        elif action == "delete":
            db.session.delete(g)
            msg = "Game deleted."
        else:
            raise ValueError("Unknown action.")
        db.session.commit()
        flash(msg, "success")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
    return _back(t, "rounds", round=g.round)
