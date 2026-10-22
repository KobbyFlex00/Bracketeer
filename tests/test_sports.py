import pytest

from bracketeer.engine import PairingError, champion, generate_round, knockout_rounds
from bracketeer.models import DRAW, P1, P2, PENDING, Game


def _game(t, rnd, a, b):
    return next(g for g in t.games_in_round(rnd) if {g.p1.name, g.p2.name if g.p2 else None} == {a, b})


def _play(t, db, rnd, a, b, **form):
    g = Game(tournament=t, round=rnd, board=0, p1=_p(t, a), p2=_p(t, b), result=PENDING)
    db.session.add(g)
    t.rules.record_result(g, form)
    db.session.commit()
    return g


def _p(t, name):
    return next(p for p in t.participants if p.name == name)


def test_chess_tiebreaks(db, make_tournament):
    t = make_tournament("chess", "swiss")
    _play(t, db, 1, "A", "B", result=P1)
    _play(t, db, 1, "C", "D", result=DRAW)
    _play(t, db, 2, "A", "C", result=DRAW)
    _play(t, db, 2, "B", "D", result=P1)
    rows = {r.p.name: r for r in t.rules.standings(t)}
    assert rows["A"]["points"] == 1.5 and rows["D"]["points"] == 0.5
    assert {r["buchholz"] for r in rows.values()} == {2.0}
    assert rows["A"]["sb"] == 1.5 and rows["B"]["sb"] == 0.5 and rows["C"]["sb"] == 1.0 and rows["D"]["sb"] == 0.5
    assert [r.p.name for r in t.rules.standings(t)] == ["A", "C", "B", "D"]
    assert t.rules.fmt("points", 1.5) == "1½" and t.rules.fmt("sb", 0.5) == "½"


def test_chess_rejects_bad_result(db, make_tournament):
    t = make_tournament("chess")
    with pytest.raises(ValueError):
        _play(t, db, 1, "A", "B", result="nope")


def test_chess_swiss_colours_alternate(db, make_tournament):
    t = make_tournament("chess", names=("A", "B", "C", "D", "E", "F"))
    for rnd in (1, 2, 3):
        generate_round(t, "swiss")
        for g in t.games_in_round(rnd):
            t.rules.record_result(g, {"result": P1})
        db.session.commit()
    for p in t.participants:
        sides = [1 if g.p1_id == p.id else 2 for g in t.games if p.id in (g.p1_id, g.p2_id)]
        assert abs(sides.count(1) - sides.count(2)) <= 1, (p.name, sides)


def test_scrabble_scores_and_spread_entry(db, make_tournament):
    t = make_tournament("scrabble")
    g = _play(t, db, 1, "A", "B", score1="410", score2="380")
    assert (g.result, g.spread) == (P1, 30)
    g2 = _play(t, db, 1, "C", "D", result=P2, spread="55")
    assert (g2.result, g2.spread) == (P2, -55)
    rows = {r.p.name: r for r in t.rules.standings(t)}
    assert rows["D"]["wins"] == 1 and rows["D"]["spread"] == 55 and rows["C"]["spread"] == -55
    assert t.rules.score_text(g, g.p2_id) == "380–410"
    with pytest.raises(ValueError):
        _play(t, db, 2, "A", "C", result=P1, spread="0")


def test_scrabble_bye_and_sos(db, make_tournament):
    t = make_tournament("scrabble", names=("A", "B", "C"))
    generate_round(t, "swiss")
    bye = next(g for g in t.games_in_round(1) if g.p2_id is None)
    assert bye.p1.name == "C" and bye.spread == 50  # lowest-ranked (all tied -> last) gets the bye
    real = next(g for g in t.games_in_round(1) if g.p2_id)
    t.rules.record_result(real, {"score1": "400", "score2": "300"})
    db.session.commit()
    rows = {r.p.name: r for r in t.rules.standings(t)}
    winner = real.p1.name
    assert rows[winner]["wins"] == 1 and rows["C"]["wins"] == 1 and rows["C"]["sos"] == 0


def test_cannot_pair_with_pending_results(db, make_tournament):
    t = make_tournament("scrabble")
    generate_round(t, "swiss")
    with pytest.raises(PairingError):
        generate_round(t, "swiss")


def test_withdrawn_players_not_paired(db, make_tournament):
    t = make_tournament("scrabble", names=("A", "B", "C", "D"))
    _p(t, "D").active = False
    db.session.commit()
    generate_round(t, "swiss")
    names = {p.name for g in t.games_in_round(1) for p in (g.p1, g.p2) if p}
    assert "D" not in names and len(names) == 3


def test_scrabble_two_club_round_robin(db, make_tournament):
    t = make_tournament("scrabble", "round_robin", names=("A", "B", "X", "Y"), clubs=("ATU", "ATU", "UG", "UG"))
    for rnd in (1, 2):
        generate_round(t, "rr")
        for g in t.games_in_round(rnd):
            assert g.p1.club != g.p2.club
            t.rules.record_result(g, {"result": P1, "spread": "10"})
        db.session.commit()
    with pytest.raises(PairingError):
        generate_round(t, "rr")


def test_football_league_table(db, make_tournament):
    t = make_tournament("football", "league", names=("Lions", "Eagles", "Sharks", "Bulls"))
    scores = iter([(2, 0), (1, 1), (0, 3), (2, 2), (4, 1), (0, 1)])
    for rnd in (1, 2, 3):
        generate_round(t, "rr")
        for g in t.games_in_round(rnd):
            assert g.stage == "league"
            a, b = next(scores)
            t.rules.record_result(g, {"score1": a, "score2": b})
        db.session.commit()
    rows = t.rules.standings(t)
    assert sum(r["played"] for r in rows) == 12
    assert sum(r["gd"] for r in rows) == 0
    for r in rows:
        assert r["points"] == 3 * r["won"] + r["drawn"]
    assert [r["points"] for r in rows] == sorted((r["points"] for r in rows), reverse=True)
    with pytest.raises(PairingError):
        generate_round(t, "rr")


def test_football_league_then_knockout_final_on_penalties(db, make_tournament):
    t = make_tournament("football", "league_knockout", names=("A", "B", "C"), ko_teams=2)
    for rnd in (1, 2, 3):
        generate_round(t, "rr")
        for g in t.games_in_round(rnd):
            if g.p2_id:
                # A always wins; otherwise the home side wins.
                win_p1 = g.p1.name == "A" or g.p2.name != "A"
                t.rules.record_result(g, {"score1": 1 if win_p1 else 0, "score2": 0 if win_p1 else 1})
        db.session.commit()
    top2 = [r.p.name for r in t.rules.standings(t)][:2]
    rnd = generate_round(t, "knockout")
    final = t.games_in_round(rnd)
    assert len(final) == 1 and final[0].stage == "knockout"
    assert {final[0].p1.name, final[0].p2.name} == set(top2)
    with pytest.raises(ValueError):
        t.rules.record_result(final[0], {"score1": 1, "score2": 1})  # level needs a shoot-out winner
    t.rules.record_result(final[0], {"score1": 1, "score2": 1, "pen_winner": "2"})
    db.session.commit()
    assert champion(t).id == final[0].p2_id
    assert knockout_rounds(t)[0][1] == "Final"
    # Knockout games don't count in the league table.
    assert sum(r["played"] for r in t.rules.standings(t)) == 6
    with pytest.raises(PairingError):
        generate_round(t, "knockout")


def test_football_knockout_cup_with_byes(db, make_tournament):
    t = make_tournament("football", "knockout", names=("A", "B", "C", "D", "E"), ratings=(50, 40, 30, 20, 10))
    generate_round(t, "knockout")
    r1 = sorted(t.games_in_round(1), key=lambda g: g.board)
    assert len(r1) == 4 and sum(1 for g in r1 if g.p2_id is None) == 3  # top three seeds get byes
    for g in r1:
        if g.p2_id:
            t.rules.record_result(g, {"score1": 0, "score2": 2})
    db.session.commit()
    generate_round(t, "knockout")
    assert len(t.games_in_round(2)) == 2
