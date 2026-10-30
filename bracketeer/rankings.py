"""Cross-tournament records: one row per player, built from every tournament of a sport."""
from dataclasses import dataclass, field

from .engine import champion
from .models import Player, Tournament
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
