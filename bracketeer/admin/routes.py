import csv
import io
import json
from datetime import date

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..backup import export_tournament, import_data, name_from_filename
from ..engine import PairingError, delete_round, generate_round, unique_slug
from ..extensions import db
from ..models import PENDING, AdminUser, Game, Participant, Player, Tournament
from ..players import drop_if_empty, link, merge, relink_on_rename
from ..ratings import career_ratings
from ..sports import SPORTS

bp = Blueprint("admin", __name__, url_prefix="/admin")

STATUSES = ("upcoming", "live", "finished")
TABS = ("overview", "participants", "rounds", "settings", "export")


@bp.before_request
@login_required
def _require_login():
    pass


def _require(sport):
    """Stop here unless the signed-in admin manages this sport."""
    if not current_user.can_manage(sport):
        abort(403)


def _tournament(tid) -> Tournament:
    t = db.get_or_404(Tournament, tid)
    _require(t.sport)
    return t


def _sport_arg():
    """The ?sport= the admin asked for if they manage it, else their first sport (None if they have none)."""
    allowed = current_user.managed(SPORTS)
    sport = request.args.get("sport")
    return sport if sport in allowed else (allowed[0] if allowed else None)


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


def _date(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("Date must look like 2026-03-14.") from None


def default_system(t):
    if t.sport == "football":
        return {"double_league": "double_rr", "knockout": "knockout"}.get(t.format, "rr")
    return {"round_robin": "rr", "double_round_robin": "double_rr"}.get(t.format, "swiss")


# ---------- tournaments ----------

@bp.route("/")
def home():
    sport = _sport_arg()
    if sport is None:
        return render_template("admin/no_sports.html")
    tournaments = Tournament.query.filter_by(sport=sport).order_by(Tournament.created_at.desc()).all()
    allowed = current_user.managed(SPORTS)
    counts = {k: Tournament.query.filter_by(sport=k).count() for k in allowed}
    return render_template("admin/home.html", sport=SPORTS[sport], tournaments=tournaments, counts=counts, allowed=allowed)


@bp.route("/tournaments", methods=["POST"])
def create_tournament():
    sport_key = request.form.get("sport")
    rules = SPORTS.get(sport_key)
    try:
        if rules is None:
            raise ValueError("Pick a sport.")
        _require(rules.key)
        name = _clean_name(request.form.get("name"), "Tournament name")
        fmt = request.form.get("format")
        if fmt not in rules.formats:
            raise ValueError("Pick a format.")
        held_on = _date(request.form.get("held_on"))
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.home", sport=sport_key))
    t = Tournament(name=name, slug=unique_slug(name), sport=rules.key, format=fmt, status="upcoming",
                   venue=(request.form.get("venue") or "").strip()[:120], settings={}, held_on=held_on)
    db.session.add(t)
    db.session.commit()
    flash(f"Created {t.name}. Add {rules.participant_plural.lower()} next.", "success")
    return _back(t, "participants")


def _file_sport(data):
    """Legacy engine files are always Scrabble; Bracketeer backups name their sport."""
    if isinstance(data, list):
        return "scrabble"
    if isinstance(data, dict):
        return (data.get("tournament") or {}).get("sport")
    return None


@bp.route("/import", methods=["POST"])
def import_file():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose a .json file to import.", "danger")
        return redirect(url_for("admin.home"))
    try:
        data = json.load(upload.stream)
        sport = _file_sport(data)
        if sport in SPORTS and not current_user.can_manage(sport):
            raise ValueError(f"You don't manage {SPORTS[sport].name}, so you can't import its tournaments.")
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
        if "held_on" in f:
            t.held_on = _date(f.get("held_on"))
        settings = dict(t.settings or {})
        for key, cast in (("bye_spread", int), ("bye_points", float), ("elo_k", int), ("ko_teams", int),
                          ("win_points", int), ("rr_offset", int)):
            if f.get(key, "").strip() != "":
                settings[key] = cast(f[key])
        if "team_battle_present" in f:
            settings["team_battle"] = bool(f.get("team_battle"))
        t.settings = settings
    except ValueError as e:
        known = any(w in str(e) for w in ("required", "long", "Date"))
        flash(str(e) if known else "Settings must be numbers.", "danger")
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


# ---------- players (career profiles) ----------

@bp.route("/players")
def players():
    sport = _sport_arg()
    if sport is None:
        return render_template("admin/no_sports.html")
    rules = SPORTS[sport]
    career = career_ratings(sport) if rules.has_ratings else None
    rows = []
    for pl in Player.query.filter_by(sport=sport).order_by(Player.name).all():
        names = sorted({p.name for p in pl.participants} - {pl.name})
        rating = int(round(career.rating[pl.id])) if career is not None and pl.id in career.rating else None
        rows.append({"pl": pl, "aliases": names, "events": len(pl.participants), "rating": rating})
    return render_template("admin/players.html", sport=rules, rows=rows)


@bp.route("/players/<int:plid>", methods=["POST"])
def manage_player(plid):
    pl = db.get_or_404(Player, plid)
    _require(pl.sport)
    action = request.form.get("action")
    try:
        if action == "rename":
            pl.name = _clean_name(request.form.get("name"))
            flash(f"Renamed to {pl.name}.", "success")
        elif action == "merge":
            target = db.session.get(Player, int(request.form.get("into") or 0))
            if target is None or target.sport != pl.sport:
                raise ValueError("Pick who to merge into.")
            moved = merge(pl, target)
            flash(f"Merged {pl.name} into {target.name} ({moved} tournament entr{'y' if moved == 1 else 'ies'} moved).", "success")
        else:
            raise ValueError("Unknown action.")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("admin.players", sport=pl.sport))
    db.session.commit()
    return redirect(url_for("admin.players", sport=pl.sport))


# ---------- participants ----------

def _add_participant(t, name, club, rating, career=None):
    """rating=None: a returning player starts from their carried-over rating, a new one from the sport default."""
    p = Participant(tournament=t, name=name, club=club, seed_rating=rating or t.rules.default_rating)
    db.session.add(p)
    player = link(p, t.sport)
    if rating is None and career is not None and player.id in career.rating:
        p.seed_rating = int(round(career.rating[player.id]))
    return p


def _career(t):
    return career_ratings(t.sport) if t.rules.has_ratings else None


@bp.route("/t/<int:tid>/participants", methods=["POST"])
def add_participant(tid):
    t = _tournament(tid)
    upper = t.sport == "scrabble"
    try:
        name = _clean_name(request.form.get("name"), upper=upper)
        club = " ".join((request.form.get("club") or "").split())[:120]
        _add_participant(t, name, club.upper() if upper else club, _rating(request.form.get("rating"), None), _career(t))
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
    career = _career(t)
    for i, row in enumerate(csv.reader(io.StringIO(text)), 1):
        cells = [c.strip() for c in row]
        if not cells or not cells[0] or cells[0].lower() == "name":
            continue
        try:
            name = _clean_name(cells[0], upper=upper)
            club = cells[1] if len(cells) > 1 else ""
            rating = _rating(cells[2] if len(cells) > 2 else "", None)
            _add_participant(t, name, club.upper() if upper else club, rating, career)
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
            old_name = p.name
            p.name = _clean_name(request.form.get("name"), upper=upper)
            club = " ".join((request.form.get("club") or "").split())[:120]
            p.club = club.upper() if upper else club
            p.seed_rating = _rating(request.form.get("rating"), p.seed_rating)
        except ValueError as e:
            flash(str(e), "danger")
            return _back(t, "participants")
        if p.player is None or p.name.casefold() != old_name.casefold():
            relink_on_rename(p, t.sport)
        flash(f"Updated {p.name}.", "success")
    elif action == "toggle":
        p.active = not p.active
        flash(f"{p.name} {'reinstated' if p.active else 'withdrawn — no longer paired, results kept'}.", "success")
    elif action == "delete":
        if p.has_games():
            flash(f"{p.name} has games recorded. Withdraw them instead so results stay consistent.", "danger")
            return _back(t, "participants")
        player = p.player
        db.session.delete(p)
        drop_if_empty(player)
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


# ---------- admins (super admin only) & own account ----------

def _require_super():
    if not current_user.is_super:
        abort(403)


def _password(value, required=True):
    value = value or ""
    if not value and not required:
        return None
    if len(value) < 8:
        raise ValueError("Passwords need at least 8 characters.")
    return value


def _sports_from(form):
    return [k for k in SPORTS if form.get(f"sport_{k}")]


def _supers_left(excluding):
    return AdminUser.query.filter(AdminUser.is_super.is_(True), AdminUser.id != excluding.id).count()


@bp.route("/admins")
def admins():
    _require_super()
    users = AdminUser.query.order_by(AdminUser.is_super.desc(), AdminUser.username).all()
    return render_template("admin/admins.html", users=users)


@bp.route("/admins", methods=["POST"])
def create_admin():
    _require_super()
    f = request.form
    try:
        username = _clean_name(f.get("username"), "Username")[:80]
        if AdminUser.query.filter(db.func.lower(AdminUser.username) == username.lower()).first():
            raise ValueError(f"There is already an admin called {username}.")
        is_super = bool(f.get("is_super"))
        sports = [] if is_super else _sports_from(f)
        if not is_super and not sports:
            raise ValueError("Tick at least one game for this admin to manage, or make them a super admin.")
        user = AdminUser(username=username, is_super=is_super, sports=sports)
        user.set_password(_password(f.get("password")))
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.admins"))
    db.session.add(user)
    db.session.commit()
    flash(f"Added {username}. Share the password with them; they can change it under Account.", "success")
    return redirect(url_for("admin.admins"))


@bp.route("/admins/<int:uid>", methods=["POST"])
def manage_admin(uid):
    _require_super()
    user = db.get_or_404(AdminUser, uid)
    f = request.form
    action = f.get("action")
    try:
        if action == "update":
            is_super = bool(f.get("is_super"))
            if user.is_super and not is_super and not _supers_left(user):
                raise ValueError("Keep at least one super admin.")
            sports = [] if is_super else _sports_from(f)
            if not is_super and not sports:
                raise ValueError("Tick at least one game, or remove the admin instead.")
            user.is_super, user.sports = is_super, sports
            new_password = _password(f.get("password"), required=False)
            if new_password:
                user.set_password(new_password)
            flash(f"Updated {user.username}.", "success")
        elif action == "delete":
            if user.id == current_user.id:
                raise ValueError("You can't remove your own login.")
            if user.is_super and not _supers_left(user):
                raise ValueError("Keep at least one super admin.")
            db.session.delete(user)
            flash(f"Removed {user.username}.", "success")
        else:
            raise ValueError("Unknown action.")
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "danger")
        return redirect(url_for("admin.admins"))
    db.session.commit()
    return redirect(url_for("admin.admins"))


@bp.route("/account", methods=["GET", "POST"])
def account():
    if request.method == "POST":
        try:
            if not current_user.check_password(request.form.get("current", "")):
                raise ValueError("Your current password is wrong.")
            new = _password(request.form.get("new"))
            if new != request.form.get("confirm"):
                raise ValueError("The new passwords don't match.")
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("admin.account"))
        current_user.set_password(new)
        db.session.commit()
        flash("Password changed.", "success")
        return redirect(url_for("admin.account"))
    return render_template("admin/account.html")
