from collections import Counter

MAX_SEARCH_NODES = 200_000


def pick_bye(ranked_ids: list, had_bye: set):
    """Lowest-ranked player who has not had a bye yet (or the lowest-ranked overall)."""
    for pid in reversed(ranked_ids):
        if pid not in had_bye:
            return pid
    return ranked_ids[-1]


def swiss_pairs(ranked_ids: list, played: Counter, had_bye: set) -> list[tuple]:
    """Swiss pairing on a ranked list (best first).

    Pairs top-down with each player's nearest-ranked unplayed opponent, backtracking when a
    choice leaves the rest unpairable. Only if no repeat-free pairing exists does it fall back
    to a greedy pairing that picks the least-played opponent.
    """
    ids = list(ranked_ids)
    pairs = []
    if len(ids) % 2:
        bye = pick_bye(ids, had_bye)
        ids.remove(bye)
        pairs.append((bye, None))
    if not ids:
        return pairs

    def met(a, b):
        return played.get(frozenset((a, b)), 0)

    nodes = 0

    def solve(remaining):
        nonlocal nodes
        if not remaining:
            return []
        nodes += 1
        if nodes > MAX_SEARCH_NODES:
            return None
        head, rest = remaining[0], remaining[1:]
        for i, opp in enumerate(rest):
            if met(head, opp):
                continue
            tail = solve(rest[:i] + rest[i + 1:])
            if tail is not None:
                return [(head, opp)] + tail
        return None

    found = solve(ids)
    if found is None:
        found = []
        pool = list(ids)
        while pool:
            head = pool.pop(0)
            opp = min(pool, key=lambda o: (met(head, o), pool.index(o)))
            pool.remove(opp)
            found.append((head, opp))
    return found + pairs


def koh_pairs(ranked_ids: list) -> list[tuple]:
    """King of the Hill: 1v2, 3v4 ... regardless of history; bottom player gets the bye."""
    ids = list(ranked_ids)
    pairs = []
    if len(ids) % 2:
        pairs.append((ids.pop(), None))
    return [(ids[i], ids[i + 1]) for i in range(0, len(ids), 2)] + pairs
