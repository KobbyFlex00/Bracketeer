from collections import defaultdict

from .models import DRAW, P1, P2


def elo_ratings(start: dict, games, k: float = 20) -> dict:
    """Replay decided games round by round; rating swings apply at the end of each round.

    start: participant id -> starting rating. Byes and pending games do not affect ratings.
    """
    current = {pid: float(r) for pid, r in start.items()}
    by_round = defaultdict(list)
    for g in games:
        if g.result in (P1, P2, DRAW) and g.p2_id is not None:
            by_round[g.round].append(g)
    for rnd in sorted(by_round):
        changes = defaultdict(float)
        for g in by_round[rnd]:
            if g.p1_id not in current or g.p2_id not in current:
                continue
            ra, rb = current[g.p1_id], current[g.p2_id]
            actual = 1.0 if g.result == P1 else 0.5 if g.result == DRAW else 0.0
            expected = 1 / (1 + 10 ** ((rb - ra) / 400))
            changes[g.p1_id] += k * (actual - expected)
            changes[g.p2_id] -= k * (actual - expected)
        for pid, delta in changes.items():
            current[pid] += delta
    return {pid: int(round(r)) for pid, r in current.items()}
