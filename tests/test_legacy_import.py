import json
import os

import pytest

from bracketeer.backup import import_legacy, name_from_filename

ROOT = os.path.dirname(os.path.dirname(__file__))
SNAPSHOT = json.load(open(os.path.join(ROOT, "tests", "fixtures", "legacy_standings.json")))


@pytest.mark.parametrize("key", sorted(SNAPSHOT))
def test_legacy_import_matches_old_engine(app, key):
    """Standings after import match what the old atu-scrabble-engine computed.

    SOS is not compared: the old engine counted a repeat opponent only once (a bug in double
    round robins); Bracketeer counts every game.
    """
    path = os.path.join(ROOT, "legacy_data", f"{key}.json")
    t = import_legacy(json.load(open(path)), name_from_filename(path))
    rows = t.rules.standings(t)
    got = [dict(name=r.p.name, wins=r["wins"], losses=r["losses"], spread=r["spread"], rating=r["rating"]) for r in rows]
    want = [dict(name=r["name"], wins=r["wins"], losses=r["losses"], spread=r["spread"], rating=r["rating"]) for r in SNAPSHOT[key]]
    assert sorted(got, key=lambda r: r["name"]) == sorted(want, key=lambda r: r["name"])
    assert [r["name"] for r in got] == [r["name"] for r in want]
