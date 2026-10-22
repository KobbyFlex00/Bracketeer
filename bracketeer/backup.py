"""JSON backup/restore, plus import of files from the old atu-scrabble-engine (data/*.json)."""
import os

from .engine import unique_slug
from .extensions import db
from .models import BYE, DRAW, P1, P2, RESULTS, Game, Participant, Tournament
from .sports import SPORTS

BACKUP_VERSION = 1


def export_tournament(t: Tournament) -> dict:
    return {
        "bracketeer_backup": BACKUP_VERSION,
        "tournament": {
            "name": t.name, "sport": t.sport, "format": t.format, "status": t.status,
            "venue": t.venue or "", "settings": t.settings or {},
        },
        "participants": [
            {"id": p.id, "name": p.name, "club": p.club or "", "seed_rating": p.seed_rating, "active": p.active}
            for p in t.participants
        ],
        "games": [
            {
                "round": g.round, "stage": g.stage, "board": g.board, "p1": g.p1_id, "p2": g.p2_id,
                "score1": g.score1, "score2": g.score2, "spread": g.spread, "pen_winner": g.pen_winner,
                "result": g.result,
            }
            for g in t.games
        ],
    }


def import_data(data, fallback_name: str = "Imported Tournament") -> Tournament:
    """Accepts either a Bracketeer backup (dict) or a legacy engine file (list of players)."""
    if isinstance(data, list):
        return import_legacy(data, fallback_name)
    if not isinstance(data, dict) or "bracketeer_backup" not in data:
        raise ValueError("This is not a Bracketeer backup or a legacy tournament file.")
    info = data["tournament"]
    if info.get("sport") not in SPORTS:
        raise ValueError("The backup names an unknown sport.")
    t = Tournament(
        name=info["name"], slug=unique_slug(info["name"]), sport=info["sport"], format=info["format"],
        status=info.get("status", "upcoming"), venue=info.get("venue", ""), settings=info.get("settings") or {},
    )
    db.session.add(t)
    id_map = {}
    for p in data.get("participants", []):
        new = Participant(tournament=t, name=p["name"], club=p.get("club", ""),
                          seed_rating=int(p.get("seed_rating", 1200)), active=bool(p.get("active", True)))
        db.session.add(new)
        id_map[p["id"]] = new
    for g in data.get("games", []):
        if g.get("result") not in RESULTS or g.get("p1") not in id_map:
            raise ValueError("The backup contains an invalid game.")
        db.session.add(Game(
            tournament=t, round=int(g["round"]), stage=g.get("stage", "main"), board=int(g.get("board", 0)),
            p1=id_map[g["p1"]], p2=id_map.get(g.get("p2")), score1=g.get("score1"), score2=g.get("score2"),
            spread=g.get("spread"), pen_winner=g.get("pen_winner"), result=g["result"],
        ))
    db.session.commit()
    return t


def import_legacy(players: list, name: str) -> Tournament:
    """Legacy files store a per-player `history` list: opp_id -1 = empty slot, 0 = bye."""
    t = Tournament(name=name, slug=unique_slug(name), sport="scrabble", format="swiss", status="upcoming", settings={})
    db.session.add(t)
    by_old_id = {}
    for p in players:
        new = Participant(tournament=t, name=p["name"], club=p.get("club", "") or "", seed_rating=int(p.get("rating", 1200)))
        db.session.add(new)
        by_old_id[p["id"]] = new
    max_round = max((len(p.get("history", [])) for p in players), default=0)
    for r in range(max_round):
        busy, board = set(), 0
        for p in players:
            hist = p.get("history", [])
            if r >= len(hist) or p["id"] in busy:
                continue
            m = hist[r]
            opp = m["opp_id"]
            if opp == -1:
                continue
            board += 1
            if opp == 0:
                db.session.add(Game(tournament=t, round=r + 1, board=board, p1=by_old_id[p["id"]],
                                    result=BYE, spread=m.get("spread", 0)))
                busy.add(p["id"])
                continue
            if opp in busy or opp not in by_old_id:
                continue
            result = {"W": P1, "L": P2, "D": DRAW}[m["result"]]
            db.session.add(Game(tournament=t, round=r + 1, board=board, p1=by_old_id[p["id"]],
                                p2=by_old_id[opp], result=result, spread=m.get("spread", 0)))
            busy.update((p["id"], opp))
    if max_round:
        t.status = "finished"
    db.session.commit()
    return t


def name_from_filename(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0].replace("_", " ").title()
