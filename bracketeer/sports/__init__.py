from .chess import Chess
from .football import Football
from .scrabble import Scrabble

SPORTS = {s.key: s for s in (Scrabble(), Chess(), Football())}


def get_sport(key: str):
    try:
        return SPORTS[key]
    except KeyError:
        raise ValueError(f"Unknown sport: {key}") from None
