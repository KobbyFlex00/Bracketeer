from ..models import BYE, DRAW, P1, P2
from ..ratings import career_ratings
from .base import Row, Sport


def _half(x: float) -> str:
    whole = int(x)
    if not x - whole:
        return str(whole)
    return f"{whole}½" if whole else "½"


class Chess(Sport):
    key = "chess"
    name = "Chess"
    icon = "♟️"
    side_labels = ("White", "Black")
    formats = {"swiss": "Swiss", "round_robin": "Round Robin", "double_round_robin": "Double Round Robin"}
    pairing_systems = {"swiss": "Swiss (Dutch-style, colour balanced)", "rr": "Round Robin", "double_rr": "Double Round Robin"}
    columns = [
        ("points", "Pts", "num"),
        ("buchholz", "Buch", "num"),
        ("sb", "SB", "num"),
        ("wins", "W", "num"),
        ("rating", "Rating", "num hide-sm"),
    ]

    RESULT_CHOICES = {P1: "1–0", DRAW: "½–½", P2: "0–1"}

    def record_result(self, game, form):
        result = form.get("result")
        if result not in self.RESULT_CHOICES:
            raise ValueError("Choose 1–0, ½–½ or 0–1.")
        game.result = result
        game.score1 = game.score2 = game.spread = None

    def score_text(self, game, pid=None):
        if game.result == BYE:
            return f"BYE ({_half(game.tournament.setting('bye_points', 1))})"
        if not game.decided:
            return "vs"
        text = self.RESULT_CHOICES[game.result]
        if pid is not None and pid == game.p2_id:
            text = "–".join(reversed(text.split("–")))
        return text

    def standings(self, t, career=None):
        entries = self.entries(t)
        bye_points = float(t.setting("bye_points", 1))
        career = career or career_ratings(t.sport)  # ratings carried over from earlier tournaments
        rows = {}
        for p in t.participants:
            es = entries[p.id]
            pts = sum(1 if e.outcome == "W" else 0.5 if e.outcome == "D" else bye_points if e.outcome == "B" else 0 for e in es)
            rows[p.id] = Row(p, entries=es, stats={
                "played": len(es),
                "points": pts,
                "wins": sum(1 for e in es if e.outcome == "W"),
                "whites": sum(1 for e in es if e.opp_id and e.side == 1),
                "rating": career.rating_of(p),
            })
        for r in rows.values():
            opp = [(e, rows[e.opp_id]) for e in r.entries if e.opp_id in rows]
            r.stats["buchholz"] = sum(o["points"] for _, o in opp)
            r.stats["sb"] = sum(o["points"] * (1 if e.outcome == "W" else 0.5) for e, o in opp if e.outcome in "WD")
        return self.ranked(
            list(rows.values()),
            key=lambda r: (r["points"], r["buchholz"], r["sb"], r["wins"], r["rating"]),
        )

    def fmt(self, key, value):
        return _half(value) if key in ("points", "buchholz", "sb") else value
