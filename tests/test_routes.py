import io
import json

import pytest

from bracketeer import create_app
from bracketeer.extensions import db as _db
from bracketeer.models import Tournament


def test_admin_requires_login(client):
    for url in ("/admin/", "/admin/t/1", "/admin/players"):
        resp = client.get(url)
        assert resp.status_code == 302 and "/admin/login" in resp.headers["Location"]
    assert client.post("/admin/tournaments", data={"sport": "chess"}).status_code == 302
    assert client.post("/admin/players/1", data={"action": "rename", "name": "x"}).status_code == 302


def test_bad_login(client):
    resp = client.post("/admin/login", data={"username": "td", "password": "wrong"})
    assert resp.status_code == 200 and b"Wrong username or password" in resp.data


def test_login_open_redirect_blocked(client):
    resp = client.post("/admin/login?next=https://evil.example/", data={"username": "td", "password": "password123"})
    assert resp.headers["Location"].endswith("/admin/")


def test_csrf_enforced():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://", "SECRET_KEY": "x"})
    with app.app_context():
        _db.create_all()
        resp = app.test_client().post("/admin/login", data={"username": "a", "password": "b"})
        assert resp.status_code == 400


def _create(admin, sport, fmt, names):
    resp = admin.post("/admin/tournaments", data={"sport": sport, "name": f"Test {sport} {fmt}", "format": fmt})
    assert resp.status_code == 302
    t = Tournament.query.order_by(Tournament.id.desc()).first()
    admin.post(f"/admin/t/{t.id}/participants/bulk", data={"lines": "\n".join(names)})
    assert len(t.participants) == len(names)
    return t


def _all_pages_ok(client, t):
    urls = [f"/t/{t.slug}", f"/t/{t.slug}/pairings", f"/t/{t.slug}/standings.csv", f"/t/{t.slug}/results.csv",
            f"/t/{t.slug}/p/{t.participants[0].id}", f"/{t.sport}", "/"]
    if t.rules.has_crosstable:
        urls += [f"/t/{t.slug}/crosstable", f"/t/{t.slug}/scorecards"]
    if t.rules.has_clubs:
        urls.append(f"/t/{t.slug}/teams")
    if t.rules.has_bracket:
        urls.append(f"/t/{t.slug}/bracket")
    for url in urls:
        assert client.get(url).status_code == 200, url
    for tab in ("overview", "participants", "rounds", "settings", "export"):
        assert client.get(f"/admin/t/{t.id}?tab={tab}").status_code == 200, tab


@pytest.mark.parametrize("sport,fmt,system,form", [
    ("scrabble", "swiss", "swiss", {"score1": "420", "score2": "390"}),
    ("chess", "swiss", "swiss", {"result": "DRAW"}),
    ("football", "league", "rr", {"score1": "2", "score2": "1"}),
    ("football", "knockout", "knockout", {"score1": "0", "score2": "0", "pen_winner": "1"}),
])
def test_full_flow(admin, sport, fmt, system, form):
    t = _create(admin, sport, fmt, ["Ama, ATU, 1300", "Kofi, UG", "Esi, ATU", "Yaw, KNUST", "Akos"])
    _all_pages_ok(admin, t)
    resp = admin.post(f"/admin/t/{t.id}/rounds", data={"system": system}, follow_redirects=True)
    assert b"Round 1 paired" in resp.data
    for g in t.games_in_round(1):
        if g.p2_id:
            admin.post(f"/admin/t/{t.id}/games/{g.id}", data={"action": "result", **form})
    assert t.round_complete(1)
    _all_pages_ok(admin, t)
    resp = admin.post(f"/admin/t/{t.id}/rounds", data={"system": system}, follow_redirects=True)
    assert b"Round 2 paired" in resp.data
    assert t.status == "live"


def test_game_fixes_and_round_undo(admin):
    t = _create(admin, "scrabble", "swiss", ["A", "B", "C", "D"])
    admin.post(f"/admin/t/{t.id}/rounds", data={"system": "swiss"})
    g = t.games_in_round(1)[0]
    admin.post(f"/admin/t/{t.id}/games/{g.id}", data={"action": "result", "result": "P1", "spread": "40"})
    p1 = g.p1_id
    admin.post(f"/admin/t/{t.id}/games/{g.id}", data={"action": "swap"})
    assert g.p2_id == p1 and g.result == "P2" and g.spread == -40
    other = t.games_in_round(1)[1]
    resp = admin.post(f"/admin/t/{t.id}/games/{g.id}",
                      data={"action": "repair", "p1": g.p1_id, "p2": other.p1_id}, follow_redirects=True)
    assert b"already has a game" in resp.data
    admin.post(f"/admin/t/{t.id}/rounds/1/delete")
    assert t.max_round == 0


def test_participant_with_games_cannot_be_deleted(admin):
    t = _create(admin, "chess", "swiss", ["A", "B"])
    admin.post(f"/admin/t/{t.id}/rounds", data={"system": "swiss"})
    p = t.participants[0]
    resp = admin.post(f"/admin/t/{t.id}/participants/{p.id}", data={"action": "delete"}, follow_redirects=True)
    assert b"Withdraw them instead" in resp.data
    admin.post(f"/admin/t/{t.id}/participants/{p.id}", data={"action": "toggle"})
    assert p.active is False


def test_backup_roundtrip_and_legacy_upload(admin):
    t = _create(admin, "football", "league", ["Lions", "Eagles"])
    admin.post(f"/admin/t/{t.id}/rounds", data={"system": "rr"})
    backup = admin.get(f"/admin/t/{t.id}/export.json").data
    resp = admin.post("/admin/import", data={"file": (io.BytesIO(backup), "b.json")},
                      content_type="multipart/form-data", follow_redirects=True)
    assert b"Imported" in resp.data
    copy = Tournament.query.order_by(Tournament.id.desc()).first()
    assert copy.id != t.id and copy.sport == "football" and len(copy.games) == 1
    legacy = json.dumps([{"id": 1, "name": "X", "club": "ATU", "rating": 1200, "history": []}]).encode()
    admin.post("/admin/import", data={"file": (io.BytesIO(legacy), "old_cup.json")}, content_type="multipart/form-data")
    assert Tournament.query.filter_by(name="Old Cup").one().sport == "scrabble"


def test_delete_tournament_needs_name(admin):
    t = _create(admin, "chess", "round_robin", ["A", "B"])
    admin.post(f"/admin/t/{t.id}/delete", data={"confirm_name": "nope"})
    assert _db.session.get(Tournament, t.id) is not None
    admin.post(f"/admin/t/{t.id}/delete", data={"confirm_name": t.name})
    assert _db.session.get(Tournament, t.id) is None


def test_unknown_pages_404(client):
    assert client.get("/t/nope").status_code == 404
    assert client.get("/tennis").status_code == 404
    assert client.get("/healthz").json == {"ok": True}


def test_theme_toggle_on_every_page(client):
    for url in ("/", "/scrabble", "/scrabble/rankings", "/admin/login"):
        page = client.get(url).data
        assert b"data-theme-toggle" in page and b'localStorage.getItem("theme")' in page, url
