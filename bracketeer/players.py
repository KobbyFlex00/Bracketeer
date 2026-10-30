"""Career identity: link each tournament entry to one Player per sport, so ratings and records carry over."""
from sqlalchemy import func

from .extensions import db
from .models import Participant, Player, Tournament


def name_key(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def find_player(sport: str, name: str, exclude_id: int | None = None) -> Player | None:
    """Match a name to an existing player: any earlier entry with that name (so merged spellings stick), else a player name."""
    key = name_key(name)
    q = (Participant.query.join(Tournament).filter(Tournament.sport == sport, Participant.player_id.isnot(None))
         .filter(func.lower(Participant.name) == key))
    if exclude_id:
        q = q.filter(Participant.id != exclude_id)
    hit = q.order_by(Participant.id.desc()).first()
    if hit:
        return hit.player
    return Player.query.filter(Player.sport == sport, func.lower(Player.name) == key).order_by(Player.id).first()


def link(p: Participant, sport: str) -> Player:
    """Attach p to the matching player, creating one on first appearance."""
    player = find_player(sport, p.name, exclude_id=p.id)
    if player is None:
        player = Player(sport=sport, name=p.name, club=p.club or "")
        db.session.add(player)
    p.player = player
    if p.club:
        player.club = p.club
    return player


def relink_on_rename(p: Participant, sport: str) -> None:
    """A renamed entry joins another player only on an exact match; renaming never splits a merged profile."""
    other = find_player(sport, p.name, exclude_id=p.id)
    if other is not None and other is not p.player:
        old = p.player
        p.player = other
        drop_if_empty(old)
    elif p.player is None:
        link(p, sport)


def merge(source: Player, target: Player) -> int:
    """Move every entry of source onto target and delete source. Returns how many entries moved."""
    if source.id == target.id or source.sport != target.sport:
        raise ValueError("Pick two different players from the same sport.")
    moved = Participant.query.filter_by(player_id=source.id).update({"player_id": target.id})
    db.session.expire(source, ["participants"])  # a stale loaded list would null the moved entries on delete
    db.session.delete(source)
    return moved


def drop_if_empty(player: Player | None) -> None:
    if player is not None and player.id and not Participant.query.filter_by(player_id=player.id).count():
        db.session.delete(player)
