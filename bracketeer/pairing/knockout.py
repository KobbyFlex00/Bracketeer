def bracket_size(n: int) -> int:
    size = 1
    while size < n:
        size *= 2
    return size


def seed_order(size: int) -> list[int]:
    """Standard bracket seed positions, e.g. 8 -> [1, 8, 4, 5, 2, 7, 3, 6]."""
    order = [1]
    while len(order) < size:
        total = len(order) * 2 + 1
        order = [s for seed in order for s in (seed, total - seed)]
    return order


def first_round_pairs(seeded_ids: list) -> list[tuple]:
    """Pairs in bracket order. Missing seeds become byes, which go to the top seeds."""
    if len(seeded_ids) < 2:
        raise ValueError("A knockout needs at least 2 entrants.")
    order = seed_order(bracket_size(len(seeded_ids)))
    slots = [seeded_ids[s - 1] if s <= len(seeded_ids) else None for s in order]
    return [(slots[i], slots[i + 1]) for i in range(0, len(slots), 2)]


def next_round_pairs(winners_in_bracket_order: list) -> list[tuple]:
    w = winners_in_bracket_order
    if len(w) < 2:
        raise ValueError("The knockout is finished.")
    return [(w[i], w[i + 1]) for i in range(0, len(w), 2)]


def round_name(entrants_left: int) -> str:
    return {2: "Final", 4: "Semi-finals", 8: "Quarter-finals"}.get(entrants_left, f"Round of {entrants_left}")
