from ..models import BYE, DRAW, P1, P2
from ..ratings import career_ratings
from .base import Row, Sport, _int

BYE_SPREAD = 50


class Scrabble(Sport):
    key = "scrabble"
    name = "Scrabble"
    icon = "🔤"
    side_labels = ("First", "Second")
    formats = {"swiss": "Swiss", "round_robin": "Round Robin", "double_round_robin": "Double Round Robin"}
    pairing_systems = {
        "swiss": "Swiss (no repeats)",
        "rr": "Round Robin",
        "double_rr": "Double Round Robin",
        "koh": "King of the Hill (1v2, 3v4…)",
    }
    columns = [
        ("wins", "W", "num"),
        ("losses", "L", "num"),
        ("spread", "Spread", "num signed"),
        ("sos", "SOS", "num"),
        ("rating", "Rating", "num hide-sm"),
    ]

    def record_result(self, game, form):
        s1 = _int(form.get("score1"), "Score")
        s2 = _int(form.get("score2"), "Score")
        if s1 is not None and s2 is not None:
            if s1 < 0 or s2 < 0:
                raise ValueError("Scores cannot be negative.")
            game.score1, game.score2, game.spread = s1, s2, s1 - s2
            game.result = P1 if s1 > s2 else P2 if s2 > s1 else DRAW
            return
        result = form.get("result")
        if result not in (P1, P2, DRAW):
            raise ValueError("Enter both scores, or choose a winner and a spread.")
        margin = abs(_int(form.get("spread"), "Spread") or 0)
        if result == DRAW:
            margin = 0
        elif margin == 0:
            raise ValueError("A win needs a spread greater than 0 (or mark it as a draw).")
        game.score1 = game.score2 = None
        game.result = result
        game.spread = margin if result == P1 else -margin if result == P2 else 0

    def bye_result(self, tournament, game):
        game.result = BYE
        game.spread = int(tournament.setting("bye_spread", BYE_SPREAD))

    def score_text(self, game, pid=None):
        if game.result == BYE:
            return f"BYE +{game.spread or 0}"
        if not game.decided:
            return "vs"
        flip = pid is not None and pid == game.p2_id
        if game.score1 is not None and game.score2 is not None:
            a, b = (game.score2, game.score1) if flip else (game.score1, game.score2)
            return f"{a}–{b}"
        spread = -(game.spread or 0) if flip else (game.spread or 0)
        return f"{spread:+d}"

    def standings(self, t, career=None):
        entries = self.entries(t)
        career = career or career_ratings(t.sport)  # ratings carried over from earlier tournaments
        rows = {}
        for p in t.participants:
            es = entries[p.id]
            wins = sum(1 if e.outcome in "WB" else 0.5 if e.outcome == "D" else 0 for e in es)
            rows[p.id] = Row(p, entries=es, stats={
                "played": len(es),
                "wins": wins,
                "losses": len(es) - wins,
                "spread": sum(e.margin for e in es),
                "rating": career.rating_of(p),
            })
        for r in rows.values():
            # SOS = sum of opponents' wins, counted once per game played against them.
            r.stats["sos"] = sum(rows[e.opp_id].stats["wins"] for e in r.entries if e.opp_id in rows)
        return self.ranked(
            list(rows.values()),
            key=lambda r: (r["wins"], r["spread"], r["sos"], r["rating"]),
        )
