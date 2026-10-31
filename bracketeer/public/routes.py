import csv
import io

from flask import Blueprint, Response, abort, current_app, render_template, request

from .. import onchain
from ..engine import champion, knockout_rounds
from ..extensions import db
from ..models import Participant, Player, Tournament
from ..rankings import club_key, clubs, head_to_head, in_club, leaders, player_record, sport_records
from ..ratings import career_ratings
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
    return dict(t=t, rules=t.rules, page=page, live=t.status == "live", stellar=onchain.status(t), **kw)


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
    records = sport_records(sport)
    club_list = clubs(sport, records) if SPORTS[sport].has_clubs else []
    return render_template("public/sport.html", sport=SPORTS[sport], sections=sections, top=records[:10], clubs=club_list)


@bp.route("/<any(scrabble, chess, football):sport>/rankings")
def rankings(sport):
    rules = SPORTS[sport]
    records = sport_records(sport)
    club_list = clubs(sport, records) if rules.has_clubs else []
    club = next((c for c in club_list if c.key == club_key(request.args.get("club"))), None)
    if club is not None:
        records = in_club(records, club.key)
    return render_template("public/rankings.html", sport=rules, records=records, clubs=club_list, club=club,
                           leaders=leaders(rules, records), h2h=head_to_head(club_list))


@bp.route("/<any(scrabble, chess, football):sport>/players/<int:pid>")
def player(sport, pid):
    pl = db.session.get(Player, pid)
    if pl is None or pl.sport != sport:
        abort(404)
    rec, records = player_record(pl)
    history = career_ratings(sport).history.get(pl.id, []) if SPORTS[sport].has_ratings else []
    return render_template("public/player.html", sport=SPORTS[sport], pl=pl, rec=rec, total=len(records),
                           chart=_rating_chart(history))


def _rating_chart(history, width=640, height=200, pad=(16, 12, 8, 44)):
    """SVG geometry for the rating line: one point per rated round, tournaments marked along the x axis."""
    if len(history) < 2:
        return None
    top, right, bottom, left = pad
    values = [r for _, _, r in history]
    lo, hi = min(values), max(values)
    span = max(hi - lo, 40)
    lo, hi = lo - span * 0.1, hi + span * 0.1
    step = (width - left - right) / (len(history) - 1)

    def y(v):
        return round(top + (hi - v) / (hi - lo) * (height - top - bottom), 1)

    points = [{"x": round(left + i * step, 1), "y": y(r), "rating": r, "t": t.name,
               "label": "start" if rnd == 0 else f"round {rnd}"} for i, (t, rnd, r) in enumerate(history)]
    ticks = sorted({round((lo + (hi - lo) * f) / 10) * 10 for f in (0.15, 0.5, 0.85)})
    starts, seen = [], set()
    for pt, (t, _, _) in zip(points, history, strict=True):
        if t.id not in seen:
            seen.add(t.id)
            starts.append({"x": pt["x"], "name": t.name})
    return {"w": width, "h": height, "points": points, "left": left, "right": width - right,
            "bottom": height - bottom, "line": " ".join(f"{p['x']},{p['y']}" for p in points),
            "ticks": [{"y": y(v), "v": v} for v in ticks if lo <= v <= hi], "starts": starts}


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


@bp.route("/t/<slug>/results.json")
def results_json(slug):
    """The exact bytes whose SHA-256 is published on Stellar, so anyone can recompute it."""
    t = _by_slug(slug)
    return Response(onchain.canonical_results(t), mimetype="application/json",
                    headers={"Content-Disposition": f'inline; filename="{t.slug}-results.json"'})


@bp.route("/t/<slug>/verify")
def verify(slug):
    t = _by_slug(slug)
    if not onchain.enabled():
        abort(404)
    check, error = None, None
    try:
        check = onchain.verify(t)
    except onchain.OnchainError as e:
        error = str(e)
    return render_template("public/verify.html", **_ctx(t, "verify", check=check, error=error,
                                                         local_hash=onchain.results_hash(t), key=onchain.chain_key(t),
                                                         contract=current_app.config["STELLAR_CONTRACT_ID"],
                                                         network=onchain.network(), explorer=onchain.explorer_url))


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
