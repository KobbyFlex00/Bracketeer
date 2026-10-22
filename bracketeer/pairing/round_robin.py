class RoundRobinComplete(ValueError):
    pass


def cycle_length(n_players: int) -> int:
    """Rounds needed for everyone to meet everyone once (circle method)."""
    return n_players - 1 if n_players % 2 == 0 else n_players


def circle_pairs(ids: list, round_num: int) -> list[tuple]:
    """Circle method: player 0 is fixed, the rest rotate one seat per round.

    Returns (a, b) tuples; b is None for the player sitting out (bye).
    """
    if not ids:
        return []
    seats = list(ids)
    if len(seats) % 2:
        seats.append(None)
    n = len(seats)
    if n == 2:
        return [(seats[0], seats[1])]
    fixed, rotatable = seats[0], seats[1:]
    shift = (round_num - 1) % (n - 1)
    rotated = rotatable[-shift:] + rotatable[:-shift] if shift else rotatable
    current = [fixed] + rotated
    pairs = []
    for i in range(n // 2):
        a, b = current[i], current[n - 1 - i]
        if a is None:
            a, b = b, a
        pairs.append((a, b))
    return pairs


def team_battle_pairs(team1: list, team2: list, round_num: int) -> list[tuple]:
    """Two clubs: every member of team1 plays every member of team2 once (Scheveningen style)."""
    size = max(len(team1), len(team2))
    t1 = list(team1) + [None] * (size - len(team1))
    t2 = list(team2) + [None] * (size - len(team2))
    shift = (round_num - 1) % size
    rotated = t2[-shift:] + t2[:-shift] if shift else t2
    pairs = []
    for a, b in zip(t1, rotated, strict=True):
        if a is None and b is None:
            continue
        if a is None:
            a, b = b, a
        pairs.append((a, b))
    return pairs


def round_robin_pairs(ids: list, round_num: int, teams: tuple | None = None, cycles: int = 1) -> list[tuple]:
    """Single (cycles=1) or double (cycles=2) round robin.

    ids must be in a stable order across rounds (e.g. by participant id) or the rotation breaks.
    Side swapping for the second leg is done by the orientation step, which flips repeat meetings.
    """
    if teams:
        length = max(len(teams[0]), len(teams[1]))
    else:
        length = cycle_length(len(ids))
    if length <= 0:
        return []
    if round_num > length * cycles:
        raise RoundRobinComplete(f"The round robin is complete after {length * cycles} rounds.")
    effective = (round_num - 1) % length + 1
    if teams:
        return team_battle_pairs(teams[0], teams[1], effective)
    return circle_pairs(ids, effective)
