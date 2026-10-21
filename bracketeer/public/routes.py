import csv
import io

from flask import Blueprint, Response, abort, render_template, request

from ..engine import champion, knockout_rounds
from ..extensions import db
from ..models import Participant, Tournament
from ..sports import SPORTS

bp = Blueprint("public", __name__)


def _by_slug(slug) -> Tournament:
    return Tournament.query.filter_by(slug=slug).first_or_404()


def _round_arg(t):
    try:
        r = int(request.args.get("round", t.max_round))
    except ValueError:
        r = t.max_round
    return min(max(r, 1), max(t.max_round, 1))


def _ctx(t, page, **kw):
    return dict(t=t, rules=t.rules, page=page, live=t.status == "live", **kw)


@bp.route("/healthz")
def healthz():
    return {"ok": True}


@bp.route("/")
def home():
    groups = {}
    for key in SPORTS:
        ts = Tournament.query.filter_by(sport=key).order_by(Tournament.created_at.desc()).all()
        groups[key] = ts
    live = [t for ts in groups.values() for t in ts if t.status == "live"]
    return render_template("public/home.html", groups=groups, live=live)


@bp.route("/<any(scrabble, chess, football):sport>")
def sport(sport):
    ts = Tournament.query.filter_by(sport=sport).order_by(Tournament.created_at.desc()).all()
    sections = [(s, [t for t in ts if t.status == s]) for s in ("live", "upcoming", "finished")]
    return render_template("public/sport.html", sport=SPORTS[sport], sections=sections)


@bp.route("/t/<slug>")
def standings(slug):
    t = _by_slug(slug)
    if t.sport == "football" and t.format == "knockout":
        return bracket(slug)
    return render_template("public/standings.html", **_ctx(t, "standings", rows=t.rules.standings(t)))


@bp.route("/t/<slug>/pairings")
def pairings(slug):
    t = _by_slug(slug)
    rnd = _round_arg(t)
    return render_template("public/pairings.html", **_ctx(t, "pairings", rnd=rnd, games=t.games_in_round(rnd)))


@bp.route("/t/<slug>/scorecards")
def scorecards(slug):
    t = _by_slug(slug)
    rnd = _round_arg(t)
    games = [g for g in t.games_in_round(rnd) if g.p2_id is not None]
    return render_template("public/scorecards.html", **_ctx(t, "pairings", rnd=rnd, games=games))


@bp.route("/t/<slug>/crosstable")
def crosstable(slug):
    t = _by_slug(slug)
    if not t.rules.has_crosstable:
        abort(404)
    rows = t.rules.standings(t)
    rank = {r.p.id: r.rank for r in rows}
    grid = []
    for r in rows:
        cells = {}
        for g in t.games:
            if r.p.id in (g.p1_id, g.p2_id):
                opp = g.p2_id if g.p1_id == r.p.id else g.p1_id
                cells[g.round] = {"game": g, "opp_rank": rank.get(opp), "outcome": t.rules.outcome_for(g, r.p.id)}
        grid.append((r, cells))
    return render_template("public/crosstable.html", **_ctx(t, "crosstable", grid=grid, rounds=range(1, t.max_round + 1)))


@bp.route("/t/<slug>/teams")
def teams(slug):
    t = _by_slug(slug)
    if not t.rules.has_clubs:
        abort(404)
    main_key = t.rules.columns[0][0]
    clubs = {}
    for r in t.rules.standings(t):
        c = clubs.setdefault(r.p.club or "—", {"name": r.p.club or "—", "members": 0, "points": 0, "spread": 0, "losses": 0})
        c["members"] += 1
        c["points"] += r.stats.get(main_key, 0)
        c["spread"] += r.stats.get("spread", 0)
        c["losses"] += r.stats.get("losses", r.stats.get("played", 0) - r.stats.get(main_key, 0))
    rows = sorted(clubs.values(), key=lambda c: (c["points"], c["spread"], -c["losses"]), reverse=True)
    return render_template("public/teams.html", **_ctx(t, "teams", clubs=rows))


@bp.route("/t/<slug>/bracket")
def bracket(slug):
    t = _by_slug(slug)
    if not t.rules.has_bracket:
        abort(404)
    return render_template("public/bracket.html", **_ctx(t, "bracket", rounds=knockout_rounds(t), champion=champion(t)))


@bp.route("/t/<slug>/p/<int:pid>")
def profile(slug, pid):
    t = _by_slug(slug)
    p = db.session.get(Participant, pid)
    if p is None or p.tournament_id != t.id:
        abort(404)
    rows = t.rules.standings(t)
    row = next((r for r in rows if r.p.id == p.id), None)
    games = [g for g in t.games if p.id in (g.p1_id, g.p2_id)]
    return render_template("public/profile.html", **_ctx(t, "standings", p=p, row=row, games=games, total=len(rows)))


def _csv(t, name, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{t.slug}-{name}.csv"'})


@bp.route("/t/<slug>/standings.csv")
def standings_csv(slug):
    t = _by_slug(slug)
    cols = t.rules.columns
    rows = [[r.rank, r.p.name, r.p.club or ""] + [t.rules.fmt(k, r.stats[k]) for k, _, _ in cols]
            for r in t.rules.standings(t)]
    return _csv(t, "standings", ["Rank", "Name", "Club"] + [label for _, label, _ in cols], rows)


@bp.route("/t/<slug>/results.csv")
def results_csv(slug):
    t = _by_slug(slug)
    s1, s2 = t.rules.side_labels
    rows = [[g.round, g.stage, g.board, g.p1.name, g.p2.name if g.p2 else "BYE", t.rules.score_text(g), g.result]
            for g in t.games]
    return _csv(t, "results", ["Round", "Stage", "Board", s1, s2, "Score", "Result"], rows)
