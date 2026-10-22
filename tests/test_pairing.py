from collections import Counter
from itertools import combinations

import pytest

from bracketeer.pairing.knockout import first_round_pairs, next_round_pairs, seed_order
from bracketeer.pairing.round_robin import RoundRobinComplete, cycle_length, round_robin_pairs
from bracketeer.pairing.sides import orient
from bracketeer.pairing.swiss import koh_pairs, swiss_pairs


def _check_round(pairs, ids):
    seen = [p for pair in pairs for p in pair if p is not None]
    assert sorted(seen) == sorted(ids), "everyone appears exactly once"


@pytest.mark.parametrize("n", [2, 3, 4, 5, 7, 8, 11])
def test_round_robin_everyone_meets_once(n):
    ids = list(range(1, n + 1))
    met = Counter()
    for r in range(1, cycle_length(n) + 1):
        pairs = round_robin_pairs(ids, r)
        _check_round(pairs, ids)
        for a, b in pairs:
            if b is not None:
                met[frozenset((a, b))] += 1
    assert set(met) == {frozenset(c) for c in combinations(ids, 2)}
    assert set(met.values()) == {1}
    with pytest.raises(RoundRobinComplete):
        round_robin_pairs(ids, cycle_length(n) + 1)


def test_double_round_robin_repeats_cycle():
    ids = [1, 2, 3, 4]
    first = [set(map(frozenset, round_robin_pairs(ids, r))) for r in (1, 2, 3)]
    second = [set(map(frozenset, round_robin_pairs(ids, r, cycles=2))) for r in (4, 5, 6)]
    assert first == second


def test_team_battle_only_cross_club():
    team1, team2 = [1, 2, 3], [10, 20, 30]
    met = set()
    for r in (1, 2, 3):
        pairs = round_robin_pairs([], r, teams=(team1, team2))
        for a, b in pairs:
            assert (a in team1) != (b in team1)
            met.add(frozenset((a, b)))
    assert len(met) == 9


def test_swiss_avoids_repeats_when_greedy_would_fail():
    # Greedy top-down pairs 1-3 (1-2 played), leaving 2-4 which also already played.
    # Backtracking must find 1-4, 2-3 instead.
    played = Counter({frozenset((1, 2)): 1, frozenset((2, 4)): 1})
    pairs = swiss_pairs([1, 2, 3, 4], played, set())
    assert {frozenset(p) for p in pairs} == {frozenset((1, 4)), frozenset((2, 3))}


def test_swiss_simulation_no_repeats_and_byes_rotate():
    ids = list(range(1, 10))  # 9 players -> a bye every round
    played, had_bye = Counter(), set()
    for _ in range(5):
        pairs = swiss_pairs(ids, played, had_bye)
        _check_round(pairs, ids)
        for a, b in pairs:
            if b is None:
                assert a not in had_bye
                had_bye.add(a)
            else:
                assert played[frozenset((a, b))] == 0
                played[frozenset((a, b))] += 1
        ids = ids[1:] + ids[:1]  # shuffle the ranking a bit


def test_swiss_falls_back_when_repeats_unavoidable():
    played = Counter({frozenset((1, 2)): 1})
    assert swiss_pairs([1, 2], played, set()) == [(1, 2)]


def test_koh():
    assert koh_pairs([1, 2, 3, 4, 5]) == [(1, 2), (3, 4), (5, None)]


def test_knockout_seeding_and_byes():
    assert seed_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    pairs = first_round_pairs(["s1", "s2", "s3", "s4", "s5", "s6"])
    assert pairs == [("s1", None), ("s4", "s5"), ("s2", None), ("s3", "s6")]
    assert next_round_pairs(["s1", "s4", "s2", "s3"]) == [("s1", "s4"), ("s2", "s3")]
    with pytest.raises(ValueError):
        next_round_pairs(["champ"])


def test_orient_balances_and_flips_rematches():
    sides = {1: [1, 1], 2: [2, 2]}
    assert orient([(1, 2)], sides, {}, {1: 0, 2: 1}) == [(2, 1)]
    # Rematch: whoever was P1 last time is P2 now.
    assert orient([(1, 2)], {}, {frozenset((1, 2)): 2}, {}) == [(1, 2)]
    assert orient([(1, 2)], {}, {frozenset((1, 2)): 1}, {}) == [(2, 1)]
    # Fresh players: higher rank gets P1.
    assert orient([(5, 3)], {}, {}, {3: 0, 5: 1}) == [(3, 5)]
