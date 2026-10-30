from bracketeer.models import DRAW, P1, P2, Game, Tournament
from bracketeer.rankings import clubs, head_to_head, in_club, leaders, sport_records
from bracketeer.sports import SPORTS


def _clash(admin, db):
    admin.post("/admin/tournaments", data={"sport": "scrabble", "name": "Clash", "format": "swiss"})
    t = Tournament.query.filter_by(name="Clash").one()
    admin.post(f"/admin/t/{t.id}/participants/bulk",
               data={"lines": "Ama, ATU, 1300\nKofi, ATU, 1250\nEsi, antsc , 1280\nYaw, ANTSC, 1200\nAkos, ANTSC, 1150"})
    p = {x.name: x for x in t.participants}
    games = [  # (round, p1, p2, s1, s2)
        (1, "AMA", "ESI", 455, 380), (1, "KOFI", "YAW", 350, 410), (1, "AKOS", None, None, None),
        (2, "AMA", "KOFI", 400, 400), (2, "ESI", "YAW", 420, 300),
    ]
    for rnd, a, b, s1, s2 in games:
        if b is None:
            db.session.add(Game(tournament=t, round=rnd, board=3, p1=p[a], result="BYE", spread=50))
            continue
        result = P1 if s1 > s2 else P2 if s2 > s1 else DRAW
        db.session.add(Game(tournament=t, round=rnd, board=1, p1=p[a], p2=p[b], score1=s1, score2=s2,
                            spread=s1 - s2, result=result))
    db.session.commit()
    return t


def test_clubs_group_case_insensitively_and_rank_within(admin, db):
    _clash(admin, db)
    records = sport_records("scrabble")
    club_list = clubs("scrabble", records)
    assert [(c.name, len(c.members)) for c in club_list] == [("ANTSC", 3), ("ATU", 2)]
    atu = in_club(records, "atu")
    assert [r.position for r in atu] == [1, 2] and {r.player.name for r in atu} == {"AMA", "KOFI"}
    # Positions in the all-clubs list are untouched by the club view.
    assert sorted(r.position for r in records) == [1, 2, 3, 4, 5]


def test_head_to_head_counts_only_games_between_clubs(admin, db):
    _clash(admin, db)
    club_list = clubs("scrabble", sport_records("scrabble"))
    by = {c.name: c for c in club_list}
    # Cross-club games: Ama beat Esi (ATU win), Yaw beat Kofi (ANTSC win). Ama–Kofi and Esi–Yaw are intra-club.
    assert (by["ATU"].wins, by["ATU"].losses, by["ATU"].draws) == (1, 1, 0)
    assert (by["ANTSC"].wins, by["ANTSC"].losses) == (1, 1)
    [(a, b, wld)] = head_to_head(club_list)
    assert {a.name, b.name} == {"ATU", "ANTSC"} and wld[:2] == [1, 1]
    assert head_to_head(club_list)[0][2][0] >= head_to_head(club_list)[0][2][1]  # leading club listed first


def test_leaders_pick_top_performers(admin, db):
    _clash(admin, db)
    records = sport_records("scrabble")
    tops = {row["label"]: row for row in leaders(SPORTS["scrabble"], records)}
    assert tops["Top score"]["top"][0][0].player.name == "AMA" and tops["Top score"]["top"][0][1] == "455"
    assert [r.player.name for r, _ in tops["Top score"]["top"]] == ["AMA", "ESI", "YAW"]  # 455, 420, 410
    assert tops["Most wins"]["top"][0][0].player.name in ("ESI", "AMA")
    assert "Best win rate" not in tops  # nobody has 5 games yet
    atu_tops = {row["label"]: row for row in leaders(SPORTS["scrabble"], in_club(records, "atu"))}
    assert atu_tops["Top score"]["top"][0][0].player.name == "AMA"
    assert all(r.club == "atu" for row in atu_tops.values() for r, _ in row["top"])


def test_club_rankings_pages(admin, client, db):
    _clash(admin, db)
    page = client.get("/scrabble/rankings?club=atu").data
    assert b"ATU leaderboard" in page and b"AMA" in page and b"YAW" not in page
    assert b"Top performers" in page
    page = client.get("/scrabble/rankings").data
    assert b"Clubs" in page and b"All clubs" in page and b"YAW" in page
    assert b"YAW" in client.get("/scrabble/rankings?club=nowhere").data  # unknown club falls back to everyone
    assert b"By club:" in client.get("/scrabble").data
    assert client.get("/football/rankings").status_code == 200
