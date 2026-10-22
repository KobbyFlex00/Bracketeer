import pytest

from bracketeer import create_app
from bracketeer.cli import ensure_admin
from bracketeer.extensions import db as _db
from bracketeer.models import Participant, Tournament


@pytest.fixture
def app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test",
        "SESSION_COOKIE_SECURE": False,
    })
    with app.app_context():
        _db.create_all()
        ensure_admin("td", "password123")
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(client):
    resp = client.post("/admin/login", data={"username": "td", "password": "password123"})
    assert resp.status_code == 302
    return client


@pytest.fixture
def make_tournament(db):
    def make(sport="scrabble", fmt="swiss", names=("A", "B", "C", "D"), clubs=None, ratings=None, **settings):
        t = Tournament(name=f"{sport} cup", slug=f"{sport}-{fmt}-{len(names)}", sport=sport, format=fmt,
                       status="upcoming", settings=settings)
        db.session.add(t)
        for i, n in enumerate(names):
            db.session.add(Participant(tournament=t, name=n, club=(clubs[i] if clubs else ""),
                                       seed_rating=(ratings[i] if ratings else 1200)))
        db.session.commit()
        return t
    return make
