def orient(pairs: list[tuple], sides: dict, last_meeting: dict, rank: dict) -> list[tuple]:
    """Decide who is P1 (White in chess, home in football, starts in Scrabble).

    - Rematches flip the sides of the previous meeting.
    - Otherwise the player who has been P1 less often gets P1, then whoever was P2 last,
      then the higher-ranked player.
    sides: id -> list of 1/2 in round order; last_meeting: frozenset -> id that was P1.
    """
    out = []
    for a, b in pairs:
        if b is None:
            out.append((a, None))
            continue
        prev = last_meeting.get(frozenset((a, b)))
        if prev is not None:
            out.append((b, a) if prev == a else (a, b))
            continue

        def key(pid):
            hist = sides.get(pid, [])
            balance = hist.count(1) - hist.count(2)
            last = hist[-1] if hist else 0
            return (balance, -last, rank.get(pid, 0))

        out.append((a, b) if key(a) <= key(b) else (b, a))
    return out
