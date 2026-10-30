from collections import defaultdict
from dataclasses import dataclass, field

from .models import DRAW, P1, P2, Tournament


def _rated_rounds(games):
    by_round = defaultdict(list)
    for game in games:
        if game.result in (P1, P2, DRAW) and game.p2_id is not None:
            by_round[game.round].append(game)
    return [(rnd, by_round[rnd]) for rnd in sorted(by_round)]


def _replay(current: dict, games, k: float):
    """Apply Elo round by round, in place; swings apply at the end of each round. Yields after each round."""
    for rnd, round_games in _rated_rounds(games):
        changes, played = defaultdict(float), defaultdict(int)
        for game in round_games:
            if game.p1_id not in current or game.p2_id not in current:
                continue
            played[game.p1_id] += 1
            played[game.p2_id] += 1
            ra, rb = current[game.p1_id], current[game.p2_id]
            actual = 1.0 if game.result == P1 else 0.5 if game.result == DRAW else 0.0
            expected = 1 / (1 + 10 ** ((rb - ra) / 400))
            changes[game.p1_id] += k * (actual - expected)
            changes[game.p2_id] -= k * (actual - expected)
        for pid, delta in changes.items():
            current[pid] += delta
        yield rnd, changes, played


def elo_ratings(start: dict, games, k: float = 20) -> dict:
    """Replay decided games round by round; rating swings apply at the end of each round.

    start: participant id -> starting rating. Byes and pending games do not affect ratings.
    """
    current = {pid: float(r) for pid, r in start.items()}
    for _ in _replay(current, games, k):
        pass
    return {pid: int(round(r)) for pid, r in current.items()}


@dataclass
class Career:
    """Ratings for one sport, replayed across all its tournaments in date order."""

    rating: dict = field(default_factory=dict)  # player id -> current rating
    start: dict = field(default_factory=dict)  # participant id -> rating entering its tournament
    end: dict = field(default_factory=dict)  # participant id -> rating after its tournament's games so far
    history: dict = field(default_factory=lambda: defaultdict(list))  # player id -> [(tournament, round, rating)]
    rated_games: dict = field(default_factory=lambda: defaultdict(int))  # player id -> games that moved the rating

    def rating_of(self, p) -> int:
        return int(round(self.end.get(p.id, p.seed_rating)))


def career_ratings(sport: str) -> Career:
    """A player's first tournament starts from their entered rating; every later one starts where the last ended.

    Entries without a linked player keep the old behaviour (start from their seed rating, nothing carried).
    """
    career = Career()
    for t in sorted(Tournament.query.filter_by(sport=sport).all(), key=lambda t: t.chrono_key):
        owner = {p.id: p.player_id for p in t.participants}
        current = {}
        for p in t.participants:
            current[p.id] = float(career.rating.get(p.player_id, p.seed_rating) if p.player_id else p.seed_rating)
            career.start[p.id] = current[p.id]
        for rnd, changes, played in _replay(current, t.games, float(t.setting("elo_k", 20))):
            for pid in changes:
                if owner.get(pid):
                    if owner[pid] not in career.history:  # chart starts where their first rated game did
                        career.history[owner[pid]].append((t, 0, int(round(career.start[pid]))))
                    career.history[owner[pid]].append((t, rnd, int(round(current[pid]))))
                    career.rated_games[owner[pid]] += played[pid]
        for p in t.participants:
            career.end[p.id] = current[p.id]
            if p.player_id:
                career.rating[p.player_id] = current[p.id]
    return career
