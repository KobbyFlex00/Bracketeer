from dataclasses import dataclass, field

from ..models import BYE, DRAW, P1, P2, PENDING


@dataclass
class Entry:
    """One decided game from a single participant's point of view."""

    game: object
    opp_id: int | None  # None for a bye
    outcome: str  # W, D, L or B (bye)
    side: int  # 1 or 2
    gf: int = 0  # points/goals for
    ga: int = 0
    margin: int = 0  # Scrabble spread from this participant's view


@dataclass
class Row:
    p: object
    rank: int = 0
    entries: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def __getitem__(self, key):
        return self.stats[key]


def _int(value, label):
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        raise ValueError(f"{label} must be a whole number.") from None


class Sport:
    key = ""
    name = ""
    icon = ""
    participant_label = "Player"
    participant_plural = "Players"
    side_labels = ("Player 1", "Player 2")
    formats: dict = {}
    pairing_systems: dict = {}
    has_clubs = True
    has_crosstable = True
    has_bracket = False
    default_rating = 1200
    columns: list = []  # (stat key, label, css class)

    # ----- results -----
    def record_result(self, game, form) -> None:
        raise NotImplementedError

    def bye_result(self, tournament, game) -> None:
        game.result = BYE

    def score_text(self, game, pid=None) -> str:
        """Short result text; from pid's perspective when given."""
        raise NotImplementedError

    @staticmethod
    def flip(result):
        return {P1: P2, P2: P1}.get(result, result)

    # ----- standings -----
    def entries(self, tournament, stages=None) -> dict:
        by_pid = {p.id: [] for p in tournament.participants}
        for g in tournament.games:
            if g.result == PENDING or (stages and g.stage not in stages):
                continue
            if g.p2_id is None:
                if g.result == BYE and g.p1_id in by_pid:
                    by_pid[g.p1_id].append(Entry(g, None, "B", 1, margin=g.spread or 0))
                continue
            for pid, opp, side in ((g.p1_id, g.p2_id, 1), (g.p2_id, g.p1_id, 2)):
                if pid not in by_pid:
                    continue
                if g.result == DRAW:
                    outcome = "D"
                elif (g.result == P1) == (side == 1):
                    outcome = "W"
                else:
                    outcome = "L"
                gf, ga = (g.score1, g.score2) if side == 1 else (g.score2, g.score1)
                margin = (g.spread or 0) if side == 1 else -(g.spread or 0)
                by_pid[pid].append(Entry(g, opp, outcome, side, gf or 0, ga or 0, margin))
        return by_pid

    def standings(self, tournament) -> list[Row]:
        raise NotImplementedError

    def ranked(self, rows: list[Row], key) -> list[Row]:
        rows = sorted(rows, key=key, reverse=True)
        for i, r in enumerate(rows, 1):
            r.rank = i
        return rows

    def fmt(self, key, value):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    def outcome_for(self, game, pid):
        if game.result == PENDING:
            return None
        if game.p2_id is None:
            return "B"
        if game.result == DRAW:
            return "D"
        return "W" if game.winner_id() == pid else "L"
