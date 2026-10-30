"""Cross-tournament records: one row per player, built from every tournament of a sport."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace

from .engine import champion
from .models import DRAW, P1, P2, Player, Tournament
from .ratings import career_ratings
from .sports import get_sport


@dataclass
class Event:
    """One tournament in a player's career."""

    t: Tournament
    p: object  # the Participant entry
    rank: int | None
    field: int
    record: dict  # W / L / D / B counts
    rating_in: int | None = None
    rating_out: int | None = None

    @property
    def change(self):
        return None if self.rating_in is None else self.rating_out - self.rating_in


@dataclass
class Record:
    player: Player
    events: list = field(default_factory=list)
    rating: int | None = None
    rated_games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    byes: int = 0
    points: int = 0  # football: league-style points across all tournaments
    gd: int = 0
    gf: int = 0
    spread: int = 0  # scrabble: total margin over real games
    high_score: int | None = None  # scrabble: best single-game score (only games entered with scores)
    score_total: int = 0
    scored_games: int = 0
    titles: int = 0
    best: tuple | None = None  # (rank, field) of the best finish in a finished tournament
    position: int = 0

    @property
    def played(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def win_pct(self) -> float:
        return 100 * (self.wins + self.draws / 2) / self.played if self.played else 0.0

    @property
    def change(self):
        """Rating movement in the player's latest tournament."""
        rated = [e for e in self.events if e.change is not None]
        return rated[-1].change if rated else None

    @property
    def provisional(self) -> bool:
        return self.rated_games < 5

    @property
    def club(self) -> str:
        return club_key(self.player.club)


def _won(t, rows):
    if t.status != "finished":
        return None
    if t.rules.has_bracket and t.format in ("knockout", "league_knockout"):
        return champion(t)
    return rows[0].p if rows else None


def sport_records(sport: str) -> list[Record]:
    """Every player with at least one played game, best first: by rating, or by points for unrated sports."""
    rules = get_sport(sport)
    career = career_ratings(sport) if rules.has_ratings else None
    records = {pl.id: Record(pl) for pl in Player.query.filter_by(sport=sport).all()}
    for t in sorted(Tournament.query.filter_by(sport=sport).all(), key=lambda t: t.chrono_key):
        rows = t.rules.standings(t, career=career)
        rank = {r.p.id: r.rank for r in rows}
        entries = t.rules.entries(t)
        winner = _won(t, rows)
        for p in t.participants:
            rec = records.get(p.player_id)
            if rec is None:
                continue
            es = entries.get(p.id, [])
            counts = {o: sum(1 for e in es if e.outcome == o) for o in "WLDB"}
            if not es:
                continue
            ev = Event(t, p, rank.get(p.id), len(rows), counts)
            if career is not None:
                ev.rating_in, ev.rating_out = int(round(career.start[p.id])), int(round(career.end[p.id]))
            rec.events.append(ev)
            rec.wins += counts["W"]
            rec.losses += counts["L"]
            rec.draws += counts["D"]
            rec.byes += counts["B"]
            real = [e for e in es if e.outcome != "B"]
            for e in real:
                if e.game.score1 is not None and e.game.score2 is not None:
                    rec.scored_games += 1
                    rec.score_total += e.gf
                    rec.high_score = e.gf if rec.high_score is None else max(rec.high_score, e.gf)
            rec.spread += sum(e.margin for e in real)
            rec.gf += sum(e.gf for e in real)
            rec.gd += sum(e.gf - e.ga for e in real)
            rec.points += counts["W"] * int(t.setting("win_points", 3)) + counts["D"]
            if winner is not None and winner.id == p.id:
                rec.titles += 1
            if t.status == "finished" and ev.rank and (rec.best is None or ev.rank < rec.best[0]):
                rec.best = (ev.rank, ev.field)
    out = [r for r in records.values() if r.events and r.played + r.byes]
    for r in out:
        if career is not None:
            r.rating = int(round(career.rating.get(r.player.id, r.events[-1].rating_out)))
            r.rated_games = career.rated_games.get(r.player.id, 0)
    if career is not None:
        out.sort(key=lambda r: (r.rating, r.played, r.win_pct), reverse=True)
    else:
        out.sort(key=lambda r: (r.points, r.gd, r.gf, r.win_pct), reverse=True)
    for i, r in enumerate(out, 1):
        r.position = i
    return out


def player_record(player: Player):
    """The player's Record and the full list it was ranked in (for 'rank N of M')."""
    records = sport_records(player.sport)
    return next((r for r in records if r.player.id == player.id), None), records


# ---------- clubs ----------

MIN_GAMES = 5  # for per-game averages and win %, so one lucky game doesn't top the list


def club_key(name) -> str:
    return " ".join((name or "").split()).casefold()


@dataclass
class Club:
    key: str
    name: str
    members: list = field(default_factory=list)
    wins: int = 0  # against other clubs only
    losses: int = 0
    draws: int = 0
    h2h: dict = field(default_factory=dict)  # other club key -> [wins, losses, draws]

    @property
    def avg_rating(self):
        rated = [r.rating for r in self.members if r.rating is not None]
        return round(sum(rated) / len(rated)) if rated else None

    @property
    def top(self):
        return self.members[0] if self.members else None


def in_club(records: list[Record], key: str) -> list[Record]:
    """The club's members, ranked among themselves. A player belongs to the club of their latest entry."""
    out = [replace(r) for r in records if r.club == key]
    for i, r in enumerate(out, 1):
        r.position = i
    return out


def clubs(sport: str, records: list[Record]) -> list[Club]:
    """Clubs with at least one ranked player, biggest first, with results between clubs."""
    found = {}
    spellings = defaultdict(Counter)
    for r in records:
        if r.club:
            found.setdefault(r.club, Club(r.club, "")).members.append(r)
            spellings[r.club][r.player.club.strip()] += 1
    for key, c in found.items():
        c.name = spellings[key].most_common(1)[0][0]
    # Club-vs-club results use each entry's club at the time of the game.
    for t in Tournament.query.filter_by(sport=sport).all():
        for g in t.games:
            if g.p2_id is None or g.result not in (P1, P2, DRAW):
                continue
            a, b = club_key(g.p1.club), club_key(g.p2.club)
            if a == b or a not in found or b not in found:
                continue
            for me, them, won in ((a, b, g.result == P1), (b, a, g.result == P2)):
                idx = 2 if g.result == DRAW else 0 if won else 1
                found[me].h2h.setdefault(them, [0, 0, 0])[idx] += 1
                outcome = ("wins", "losses", "draws")[idx]
                setattr(found[me], outcome, getattr(found[me], outcome) + 1)
    return sorted(found.values(), key=lambda c: (-len(c.members), c.name))


def head_to_head(club_list: list[Club]) -> list[tuple]:
    """(club a, club b, [a wins, b wins, draws]) for every pair of clubs that has met."""
    by_key = {c.key: c for c in club_list}
    pairs = [(c, by_key[other], wld) for c in club_list for other, wld in c.h2h.items() if c.key < other]
    return [(a, b, wld) if wld[0] >= wld[1] else (b, a, [wld[1], wld[0], wld[2]]) for a, b, wld in pairs]  # leader first


def leaders(sport, records: list[Record], n: int = 3) -> list[dict]:
    """Top n performers in each category. Averages and win % need MIN_GAMES games."""
    out = []

    def best(label, rows, value, fmt=str, note=""):
        rows = sorted((r for r in rows if value(r) is not None), key=lambda r: (value(r), r.played), reverse=True)
        if rows:
            out.append({"label": label, "note": note, "top": [(r, fmt(value(r))) for r in rows[:n]]})

    regular = [r for r in records if r.played >= MIN_GAMES]
    if sport.has_ratings:
        best("Highest rating", records, lambda r: r.rating)
        best("Biggest climber", records, lambda r: r.change if r.change and r.change > 0 else None,
             lambda v: f"+{v}", "in their latest tournament")
    else:
        best("Most points", records, lambda r: r.points)
        best("Most goals", records, lambda r: r.gf)
    best("Most wins", records, lambda r: r.wins or None)
    best("Best win rate", regular, lambda r: r.win_pct, lambda v: f"{v:.0f}%", f"{MIN_GAMES}+ games")
    if sport.key == "scrabble":
        best("Top score", records, lambda r: r.high_score, note="highest single game")
        best("Best average score", [r for r in records if r.scored_games >= MIN_GAMES],
             lambda r: r.score_total / r.scored_games, lambda v: f"{v:.0f}", f"{MIN_GAMES}+ scored games")
        best("Best average spread", regular, lambda r: r.spread / r.played, lambda v: f"{v:+.0f}", f"{MIN_GAMES}+ games")
    return out
