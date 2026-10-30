import io
import json

import pytest

from bracketeer.cli import ensure_admin
from bracketeer.models import AdminUser, Player, Tournament


def _login(client, username, password="password123"):
    client.post("/admin/logout")
    resp = client.post("/admin/login", data={"username": username, "password": password})
    assert resp.status_code == 302, username
    return client


def _make_admin(db, username, sports=(), is_super=False):
    user = AdminUser(username=username, sports=list(sports), is_super=is_super)
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def chess_t(admin):
    admin.post("/admin/tournaments", data={"sport": "chess", "name": "Chess Open", "format": "swiss"})
    t = Tournament.query.filter_by(name="Chess Open").one()
    admin.post(f"/admin/t/{t.id}/participants/bulk", data={"lines": "Ama\nKofi"})
    return t


def test_bootstrap_login_is_super(db):
    assert AdminUser.query.filter_by(username="td").one().is_super
    user = ensure_admin("boss", "password123")
    assert user.is_super and user.can_manage("football")


def test_super_admin_adds_scoped_admins(admin, db):
    resp = admin.post("/admin/admins", data={"username": "ama", "password": "password123", "sport_scrabble": "1"},
                      follow_redirects=True)
    assert b"Added ama" in resp.data
    ama = AdminUser.query.filter_by(username="ama").one()
    assert (ama.is_super, ama.sports) == (False, ["scrabble"])
    # No games and not super: refused. Short password: refused. Duplicate name: refused.
    for data, msg in (({"username": "x", "password": "password123"}, b"Tick at least one game"),
                      ({"username": "y", "password": "short", "sport_chess": "1"}, b"at least 8 characters"),
                      ({"username": "AMA", "password": "password123", "sport_chess": "1"}, b"already an admin")):
        assert msg in admin.post("/admin/admins", data=data, follow_redirects=True).data
    admin.post(f"/admin/admins/{ama.id}", data={"action": "update", "sport_scrabble": "1", "sport_chess": "1"})
    assert ama.sports == ["scrabble", "chess"]


def test_scoped_admin_only_reaches_their_games(client, db, chess_t):
    _make_admin(db, "sam", ["scrabble"])
    _login(client, "sam")
    home = client.get("/admin/").data
    assert b"Scrabble" in home and b"?sport=chess" not in home
    assert client.get("/admin/?sport=chess").status_code == 200  # falls back to their own sport
    # Everything on another sport's tournament is refused.
    assert client.get(f"/admin/t/{chess_t.id}").status_code == 403
    assert client.post(f"/admin/t/{chess_t.id}/rounds", data={"system": "swiss"}).status_code == 403
    assert client.post(f"/admin/t/{chess_t.id}/participants", data={"name": "Esi"}).status_code == 403
    assert client.get(f"/admin/t/{chess_t.id}/export.json").status_code == 403
    assert client.post("/admin/tournaments", data={"sport": "chess", "name": "X", "format": "swiss"}).status_code == 403
    chess_player = Player.query.filter_by(sport="chess").first()
    assert client.post(f"/admin/players/{chess_player.id}", data={"action": "rename", "name": "Hacked"}).status_code == 403
    # Importing another sport's backup is refused before anything is written.
    backup = {"bracketeer_backup": 1, "tournament": {"name": "Sneaky", "sport": "chess", "format": "swiss"},
              "participants": [], "games": []}
    resp = client.post("/admin/import", data={"file": (io.BytesIO(json.dumps(backup).encode()), "x.json")},
                       content_type="multipart/form-data", follow_redirects=True)
    assert b"don&#39;t manage Chess" in resp.data and Tournament.query.filter_by(name="Sneaky").count() == 0
    # Their own sport works, and they can't open the Admins page.
    resp = client.post("/admin/tournaments", data={"sport": "scrabble", "name": "Sam Cup", "format": "swiss"})
    assert resp.status_code == 302 and Tournament.query.filter_by(name="Sam Cup").count() == 1
    assert client.get("/admin/admins").status_code == 403
    assert client.post("/admin/admins", data={"username": "z", "password": "password123", "is_super": "1"}).status_code == 403


def test_admin_with_no_games_sees_notice(client, db):
    _make_admin(db, "idle", [])
    _login(client, "idle")
    assert b"No games assigned yet" in client.get("/admin/").data


def test_keeps_a_super_admin_and_own_login(admin, db):
    me = AdminUser.query.filter_by(username="td").one()
    resp = admin.post(f"/admin/admins/{me.id}", data={"action": "update", "sport_chess": "1"}, follow_redirects=True)
    assert b"Keep at least one super admin" in resp.data and me.is_super
    assert b"can&#39;t remove your own login" in admin.post(f"/admin/admins/{me.id}", data={"action": "delete"},
                                                            follow_redirects=True).data
    other = _make_admin(db, "other", is_super=True)
    admin.post(f"/admin/admins/{other.id}", data={"action": "delete"})
    assert db.session.get(AdminUser, other.id) is None


def test_change_own_password(client, db):
    _make_admin(db, "cara", ["football"])
    _login(client, "cara")
    assert b"current password is wrong" in client.post("/admin/account", data={
        "current": "nope", "new": "newpass123", "confirm": "newpass123"}, follow_redirects=True).data
    assert b"don&#39;t match" in client.post("/admin/account", data={
        "current": "password123", "new": "newpass123", "confirm": "other1234"}, follow_redirects=True).data
    assert b"Password changed" in client.post("/admin/account", data={
        "current": "password123", "new": "newpass123", "confirm": "newpass123"}, follow_redirects=True).data
    _login(client, "cara", "newpass123")
