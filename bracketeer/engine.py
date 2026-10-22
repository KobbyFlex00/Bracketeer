"""Round generation: turns a sport's standings + a pairing system into saved PENDING games."""
import re
from collections import Counter, defaultdict

from .extensions import db
from .models import BYE, PENDING, Game, Tournament
from .pairing import knockout
from .pairing.round_robin import RoundRobinComplete, round_robin_pairs
from .pairing.sides import orient
from .pairing.swiss import koh_pairs, swiss_pairs


class PairingError(ValueError):
    pass


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "tournament"


def unique_slug(name: str, exclude_id: int | None = None) -> str:
    base = slugify(name)[:120]
    slug, n = base, 2
    while True:
        clash = Tournament.query.filter_by(slug=slug).first()
        if clash is None or clash.id == exclude_id:
            return slug
        slug, n = f"{base}-{n}", n + 1


def history(t: Tournament):
    """played pair counts, players who had a bye, side history and who was P1 at the last meeting."""
    played, had_bye = Counter(), set()
    sides, last_meeting = defaultdict(list), {}
    for g in sorted(t.games, key=lambda g: (g.round, g.board)):
        if g.p2_id is None:
            had_bye.add(g.p1_id)
            continue
        pair = frozenset((g.p1_id, g.p2_id))
        played[pair] += 1
        sides[g.p1_id].append(1)
        sides[g.p2_id].append(2)
        last_meeting[pair] = g.p1_id
    return played, had_bye, sides, last_meeting


def _two_club_teams(t, active):
    """Scrabble's team battle: with exactly two clubs, members only play the other club."""
    if not t.rules.has_clubs or not t.setting("team_battle", True):
        return None
    clubs = sorted({(p.club or "").strip() for p in active})
    if len(clubs) != 2 or "" in clubs:
        return None
    order = lambda p: (-p.seed_rating, p.id)  # noqa: E731 - stable across rounds, unlike live ratings
    return tuple([p.id for p in sorted(active, key=order) if p.club.strip() == c] for c in clubs)


def _knockout_pairs(t, active_ids, ranked_ids):
    ko_games = [g for g in t.games if g.stage == "knockout"]
    if not ko_games:
        if t.format == "league_knockout":
            size = int(t.setting("ko_teams", 4))
            seeded = [pid for pid in ranked_ids if pid in active_ids][:size]
        else:
            by_seed = sorted((p for p in t.participants if p.active), key=lambda p: (-p.seed_rating, p.id))
            seeded = [p.id for p in by_seed]
        return knockout.first_round_pairs(seeded)
    last = max(g.round for g in ko_games)
    prev = sorted((g for g in ko_games if g.round == last), key=lambda g: g.board)
    winners = [g.winner_id() for g in prev]
    if len(winners) == 1:
        raise PairingError("The knockout is finished — the final has been played.")
    return knockout.next_round_pairs(winners)


def generate_round(t: Tournament, system: str) -> int:
    rules = t.rules
    if system not in rules.pairing_systems:
        raise PairingError(f"{system!r} is not a pairing system for {rules.name}.")
    if t.max_round and not t.round_complete(t.max_round):
        raise PairingError(f"Enter all results for round {t.max_round} before pairing the next round.")
    active = [p for p in t.participants if p.active]
    if len(active) < 2:
        raise PairingError(f"Add at least two active {rules.participant_plural.lower()} first.")

    round_num = t.max_round + 1
    active_ids = {p.id for p in active}
    ranked_ids = [r.p.id for r in rules.standings(t) if r.p.id in active_ids]
    rank = {pid: i for i, pid in enumerate(ranked_ids)}
    played, had_bye, sides, last_meeting = history(t)
    stage = "league" if rules.key == "football" else "main"

    if system == "swiss":
        pairs = swiss_pairs(ranked_ids, played, had_bye)
    elif system == "koh":
        pairs = koh_pairs(ranked_ids)
    elif system in ("rr", "double_rr"):
        stable = sorted(active_ids)
        rr_round = round_num - int(t.setting("rr_offset", 0))
        try:
            pairs = round_robin_pairs(stable, rr_round, _two_club_teams(t, active), cycles=2 if system == "double_rr" else 1)
        except RoundRobinComplete as e:
            raise PairingError(str(e)) from None
    elif system == "knockout":
        stage = "knockout"
        try:
            pairs = _knockout_pairs(t, active_ids, ranked_ids)
        except PairingError:
            raise
        except ValueError as e:
            raise PairingError(str(e)) from None
    else:  # pragma: no cover - guarded above
        raise PairingError(system)

    if stage != "knockout":
        pairs = orient(pairs, sides, last_meeting, rank)
        # Byes go last on the board list; real games are ordered by the top player's rank.
        pairs.sort(key=lambda pr: (pr[1] is None, min(rank.get(pr[0], 0), rank.get(pr[1], 0) if pr[1] else 0)))

    board = 0
    for a, b in pairs:
        if a is None and b is None:
            continue
        if a is None:
            a, b = b, a
        board += 1
        game = Game(tournament=t, round=round_num, stage=stage, board=board, p1_id=a, p2_id=b, result=PENDING)
        if b is None:
            rules.bye_result(t, game)
        db.session.add(game)
    if t.status == "upcoming":
        t.status = "live"
    db.session.commit()
    return round_num


def delete_round(t: Tournament, round_num: int):
    for g in t.games_in_round(round_num):
        db.session.delete(g)
    db.session.commit()


def knockout_rounds(t: Tournament):
    """[(round_num, label, games)] for the bracket view."""
    ko = [g for g in t.games if g.stage == "knockout"]
    rounds = sorted({g.round for g in ko})
    out = []
    for r in rounds:
        games = sorted((g for g in ko if g.round == r), key=lambda g: g.board)
        out.append((r, knockout.round_name(len(games) * 2), games))
    return out


def champion(t: Tournament):
    rounds = knockout_rounds(t)
    if rounds and len(rounds[-1][2]) == 1 and rounds[-1][2][0].decided and rounds[-1][2][0].result != BYE:
        g = rounds[-1][2][0]
        return g.p1 if g.winner_id() == g.p1_id else g.p2
    return None
