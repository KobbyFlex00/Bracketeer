from datetime import UTC, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

# Game.result values. P1/P2 name the winner; for football P1 is the home team, for chess P1 has White.
P1, P2, DRAW, BYE, PENDING = "P1", "P2", "DRAW", "BYE", "PENDING"
RESULTS = (P1, P2, DRAW, BYE, PENDING)


def _now():
    return datetime.now(UTC)


class AdminUser(UserMixin, db.Model):
    __tablename__ = "admin_users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_super = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())  # manages admins and every sport
    sports = db.Column(db.JSON, nullable=False, default=list)  # sport keys a regular admin manages

    def can_manage(self, sport: str) -> bool:
        return self.is_super or sport in (self.sports or [])

    def managed(self, all_sports) -> list:
        """Sport keys this admin can see in the dashboard, in the site's order."""
        return [k for k in all_sports if self.can_manage(k)]

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Tournament(db.Model):
    __tablename__ = "tournaments"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False, index=True)
    sport = db.Column(db.String(20), nullable=False, index=True)
    format = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="upcoming")  # upcoming | live | finished
    venue = db.Column(db.String(120), default="")
    settings = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=_now)
    held_on = db.Column(db.Date)  # orders tournaments for career ratings; falls back to created_at

    participants = db.relationship(
        "Participant", backref="tournament", cascade="all, delete-orphan", order_by="Participant.id"
    )
    games = db.relationship(
        "Game", backref="tournament", cascade="all, delete-orphan", order_by="(Game.round, Game.board, Game.id)"
    )

    @property
    def rules(self):
        from .sports import get_sport

        return get_sport(self.sport)

    @property
    def max_round(self) -> int:
        return max((g.round for g in self.games), default=0)

    def games_in_round(self, round_num: int):
        return [g for g in self.games if g.round == round_num]

    def round_complete(self, round_num: int) -> bool:
        return all(g.result != PENDING for g in self.games_in_round(round_num))

    def setting(self, key, default=None):
        return (self.settings or {}).get(key, default)

    @property
    def chrono_key(self):
        created = self.created_at or _now()
        return (self.held_on or created.date(), created.replace(tzinfo=None), self.id or 0)


class Player(db.Model):
    """One person (or team) across every tournament of a sport; carries their career rating."""

    __tablename__ = "players"
    id = db.Column(db.Integer, primary_key=True)
    sport = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    club = db.Column(db.String(120), default="")
    created_at = db.Column(db.DateTime(timezone=True), default=_now)

    participants = db.relationship("Participant", backref="player", order_by="Participant.id")


class Participant(db.Model):
    __tablename__ = "participants"
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey("tournaments.id"), nullable=False, index=True)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), index=True)
    name = db.Column(db.String(120), nullable=False)
    club = db.Column(db.String(120), default="")
    seed_rating = db.Column(db.Integer, nullable=False, default=1200)
    active = db.Column(db.Boolean, nullable=False, default=True)

    def has_games(self) -> bool:
        return any(self.id in (g.p1_id, g.p2_id) for g in self.tournament.games)


class Game(db.Model):
    __tablename__ = "games"
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey("tournaments.id"), nullable=False, index=True)
    round = db.Column(db.Integer, nullable=False)
    stage = db.Column(db.String(20), nullable=False, default="main")  # main | league | knockout
    board = db.Column(db.Integer, nullable=False, default=0)
    p1_id = db.Column(db.Integer, db.ForeignKey("participants.id"), nullable=False)
    p2_id = db.Column(db.Integer, db.ForeignKey("participants.id"), nullable=True)  # NULL = bye
    score1 = db.Column(db.Integer)
    score2 = db.Column(db.Integer)
    spread = db.Column(db.Integer)  # Scrabble margin from P1's point of view
    pen_winner = db.Column(db.Integer)  # Football knockout: 1 or 2 when level after normal/extra time
    result = db.Column(db.String(10), nullable=False, default=PENDING)

    p1 = db.relationship("Participant", foreign_keys=[p1_id])
    p2 = db.relationship("Participant", foreign_keys=[p2_id])

    @property
    def is_bye(self) -> bool:
        return self.p2_id is None

    @property
    def decided(self) -> bool:
        return self.result != PENDING

    def winner_id(self):
        if self.result in (P1, BYE):
            return self.p1_id
        if self.result == P2:
            return self.p2_id
        return None
