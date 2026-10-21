from ..models import BYE, DRAW, P1, P2
from .base import Row, Sport, _int


class Football(Sport):
    key = "football"
    name = "Football"
    icon = "⚽"
    participant_label = "Team"
    participant_plural = "Teams"
    side_labels = ("Home", "Away")
    formats = {
        "league": "League (single round robin)",
        "double_league": "League (home & away)",
        "knockout": "Knockout cup",
        "league_knockout": "League, then knockout play-offs",
    }
    pairing_systems = {"rr": "League round", "double_rr": "League round (home & away)", "knockout": "Knockout round"}
    has_clubs = False
    has_crosstable = False
    has_bracket = True
    columns = [
        ("played", "P", "num"),
        ("won", "W", "num"),
        ("drawn", "D", "num"),
        ("lost", "L", "num"),
        ("gf", "GF", "num"),
        ("ga", "GA", "num"),
        ("gd", "GD", "num signed"),
        ("points", "Pts", "num strong"),
    ]

    def record_result(self, game, form):
        s1 = _int(form.get("score1"), "Goals")
        s2 = _int(form.get("score2"), "Goals")
        if s1 is None or s2 is None or s1 < 0 or s2 < 0:
            raise ValueError("Enter the goals for both teams.")
        game.score1, game.score2, game.spread = s1, s2, None
        game.pen_winner = None
        if s1 != s2:
            game.result = P1 if s1 > s2 else P2
            return
        if game.stage == "knockout":
            pen = form.get("pen_winner")
            if pen not in ("1", "2"):
                raise ValueError("Knockout games need a winner — pick who won on penalties.")
            game.pen_winner = int(pen)
            game.result = P1 if pen == "1" else P2
        else:
            game.result = DRAW

    def score_text(self, game, pid=None):
        if game.result == BYE:
            return "bye" if game.stage != "knockout" else "walkover"
        if not game.decided:
            return "vs"
        a, b = game.score1, game.score2
        pens = ""
        if game.pen_winner:
            pens = f" ({'H' if game.pen_winner == 1 else 'A'} on pens)"
        if pid is not None and pid == game.p2_id:
            a, b = b, a
        return f"{a}–{b}{pens}"

    def standings(self, t):
        entries = self.entries(t, stages=("league",))
        rows = []
        for p in t.participants:
            es = [e for e in entries[p.id] if e.outcome != "B"]
            won = sum(1 for e in es if e.outcome == "W")
            drawn = sum(1 for e in es if e.outcome == "D")
            gf, ga = sum(e.gf for e in es), sum(e.ga for e in es)
            rows.append(Row(p, entries=es, stats={
                "played": len(es), "won": won, "drawn": drawn, "lost": len(es) - won - drawn,
                "gf": gf, "ga": ga, "gd": gf - ga,
                "points": won * int(t.setting("win_points", 3)) + drawn,
                "rating": p.seed_rating,
            }))
        return self.ranked(rows, key=lambda r: (r["points"], r["gd"], r["gf"], -r.p.id))
