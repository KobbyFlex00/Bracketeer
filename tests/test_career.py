from datetime import date

from bracketeer.backup import export_tournament, import_data
from bracketeer.models import P1, Game, Participant, Player, Tournament
from bracketeer.rankings import sport_records
from bracketeer.ratings import career_ratings


def _event(admin, name, lines, sport="scrabble", held_on=""):
    admin.post("/admin/tournaments", data={"sport": sport, "name": name, "format": "swiss", "held_on": held_on})
    t = Tournament.query.filter_by(name=name).one()
    admin.post(f"/admin/t/{t.id}/participants/bulk", data={"lines": "\n".join(lines)})
    return t


def _play(db, t, rnd, a, b, result=P1, **scores):
    pa = next(p for p in t.participants if p.name.casefold() == a.casefold())
    pb = next(p for p in t.participants if p.name.casefold() == b.casefold())
    db.session.add(Game(tournament=t, round=rnd, board=1, p1=pa, p2=pb, result=result, **scores))
    db.session.commit()


def test_rating_carries_into_next_tournament(admin, db):
    first = _event(admin, "Spring Open", ["Ama, ATU, 1300", "Kofi, UG, 1300"])
    _play(db, first, 1, "Ama", "Kofi", score1=420, score2=380, spread=40)
    after = career_ratings("scrabble")
    ama = Player.query.filter_by(sport="scrabble").filter(Player.name.ilike("ama")).one()
    assert int(round(after.rating[ama.id])) == 1310  # K=20, equal ratings: +10

    # Same people, different case and spacing, no rating typed: they link and start where they left off.
    second = _event(admin, "Autumn Open", ["  ama , ATU", "KOFI, UG"])
    assert {p.player_id for p in second.participants} == {p.player_id for p in first.participants}
    by_name = {p.name: p for p in second.participants}
    assert by_name["AMA"].seed_rating == 1310 and by_name["KOFI"].seed_rating == 1290
    _play(db, second, 1, "Kofi", "Ama", score1=400, score2=350, spread=50)
    rows = {r.p.name: r.stats["rating"] for r in second.rules.standings(second)}
    assert rows["KOFI"] > 1290 and rows["AMA"] < 1310  # moved from the carried rating, not from 1300


def test_dates_set_the_replay_order(admin, db):
    later = _event(admin, "Later Cup", ["Esi, , 1500", "Yaw, , 1500"], held_on="2026-05-01")
    _play(db, later, 1, "Esi", "Yaw")
    earlier = _event(admin, "Earlier Cup", ["Esi", "Yaw"], held_on="2026-01-01")
    _play(db, earlier, 1, "Yaw", "Esi")
    career = career_ratings("scrabble")
    esi_early = next(p for p in earlier.participants if p.name == "ESI")
    esi_late = next(p for p in later.participants if p.name == "ESI")
    # Earlier Cup is replayed first even though it was created second, so Later Cup starts from its result.
    assert career.end[esi_early.id] == career.start[esi_late.id]
    assert earlier.held_on == date(2026, 1, 1)


def test_merge_joins_spellings_and_is_remembered(admin, db):
    a = _event(admin, "One", ["George Osae, ATU", "Ama"])
    b = _event(admin, "Two", ["George", "Ama"])
    george = next(p for p in b.participants if p.name == "GEORGE").player
    osae = next(p for p in a.participants if p.name == "GEORGE OSAE").player
    assert george.id != osae.id
    resp = admin.post(f"/admin/players/{george.id}", data={"action": "merge", "into": osae.id}, follow_redirects=True)
    assert b"Merged" in resp.data
    assert db.session.get(Player, george.id) is None
    assert {p.tournament.name for p in osae.participants} == {"One", "Two"}
    # A later entry spelled like the merged-away name joins the merged profile.
    c = _event(admin, "Three", ["george", "Ama"])
    assert next(p for p in c.participants if p.name == "GEORGE").player_id == osae.id
    assert Player.query.filter_by(sport="scrabble").count() == 2


def test_rename_joins_on_exact_match_and_remove_cleans_up(admin, db):
    _event(admin, "One", ["Kwame Mensah", "Ama"])
    t = _event(admin, "Two", ["Kwame", "Ama", "Temp"])
    kwame = next(p for p in t.participants if p.name == "KWAME")
    lone = kwame.player_id
    admin.post(f"/admin/t/{t.id}/participants/{kwame.id}", data={"action": "edit", "name": "Kwame Mensah", "rating": "1200"})
    assert kwame.player.name.casefold() == "kwame mensah" and db.session.get(Player, lone) is None
    temp = next(p for p in t.participants if p.name == "TEMP")
    temp_player = temp.player_id
    admin.post(f"/admin/t/{t.id}/participants/{temp.id}", data={"action": "delete"})
    assert db.session.get(Player, temp_player) is None


def test_rankings_and_player_pages(admin, client, db):
    t = _event(admin, "Clash", ["Ama, ATU, 1300", "Kofi, UG, 1250", "Esi"])
    _play(db, t, 1, "Ama", "Kofi", score1=410, score2=380, spread=30)
    _play(db, t, 2, "Esi", "Ama", score1=400, score2=390, spread=10)
    t.status = "finished"
    db.session.commit()
    records = sport_records("scrabble")
    assert [r.player.name for r in records][0] in ("AMA", "ESI")
    ama = next(r for r in records if r.player.name == "AMA")
    assert (ama.wins, ama.losses, ama.played, ama.spread) == (1, 1, 2, 20)
    assert ama.provisional and ama.events[0].rating_in == 1300
    for url in ("/scrabble", "/scrabble/rankings", f"/scrabble/players/{ama.player.id}"):
        resp = client.get(url)
        assert resp.status_code == 200 and b"AMA" in resp.data, url
    page = client.get(f"/scrabble/players/{ama.player.id}").data
    assert b"rating-chart" in page and b"Rating over time" in page
    assert client.get(f"/chess/players/{ama.player.id}").status_code == 404
    assert admin.get("/admin/players?sport=scrabble").status_code == 200


def test_football_ranks_by_points(admin, client, db):
    admin.post("/admin/tournaments", data={"sport": "football", "name": "League", "format": "league"})
    t = Tournament.query.filter_by(name="League").one()
    admin.post(f"/admin/t/{t.id}/participants/bulk", data={"lines": "Lions\nEagles\nSharks"})
    db.session.add(Game(tournament=t, round=1, stage="league", board=1, p1=t.participants[0], p2=t.participants[1],
                        score1=2, score2=0, result=P1))
    db.session.commit()
    records = sport_records("football")
    assert records[0].player.name == "Lions" and records[0].points == 3 and records[0].gd == 2
    assert records[0].rating is None
    for url in ("/football", "/football/rankings", f"/football/players/{records[0].player.id}"):
        assert client.get(url).status_code == 200, url


def test_backup_keeps_date_and_links_players(admin, db):
    t = _event(admin, "Dated", ["Ama", "Kofi"], held_on="2026-02-14")
    data = export_tournament(t)
    assert data["tournament"]["held_on"] == "2026-02-14"
    copy = import_data(data)
    assert copy.held_on == date(2026, 2, 14)
    assert {p.player_id for p in copy.participants} == {p.player_id for p in t.participants}
    assert Participant.query.filter(Participant.player_id.is_(None)).count() == 0
