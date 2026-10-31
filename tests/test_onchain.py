import json

import pytest
from click.testing import CliRunner

from bracketeer import onchain
from bracketeer.backup import export_tournament, import_data
from bracketeer.models import P1, P2, Anchor, Game, Tournament


def export_tournament_stub():
    """A one-player chess backup, used only to push database ids forward."""
    return {"bracketeer_backup": 1, "tournament": {"name": "Stub", "sport": "chess", "format": "swiss"},
            "participants": [{"id": 1, "name": "Stub"}], "games": []}


class FakeChain:
    """In-memory stand-in for the results-registry contract, with the same version rules."""

    def __init__(self):
        self.records, self.calls, self.lose_next_response, self.race_same_hash = {}, [], False, False

    def latest(self, key):
        recs = self.records.get(key, [])
        return dict(recs[-1]) if recs else None

    def versions(self, key):
        return len(self.records.get(key, []))

    def publish(self, key, hex_hash, version):
        self.calls.append(("publish", key, version))
        recs = self.records.setdefault(key, [])
        if self.race_same_hash:  # someone else landed this exact fingerprint first
            self.race_same_hash = False
            recs.append({"version": len(recs) + 1, "hash": hex_hash, "ledger": 2000, "timestamp": 0})
        if version != len(recs) + 1:
            raise onchain.VersionConflict("Error(Contract, #2)")
        recs.append({"version": version, "hash": hex_hash, "ledger": 1000 + version, "timestamp": 0})
        if self.lose_next_response:  # landed onchain, but the response never reached us
            self.lose_next_response = False
            raise onchain.OnchainError("timeout")
        return f"tx{version:062d}", 1000 + version

    def extend(self, key, start, end):
        self.calls.append(("extend", key, start, end))
        return None, None


@pytest.fixture
def chain(app, monkeypatch):
    app.config.update(STELLAR_CONTRACT_ID="C" + "A" * 55, STELLAR_SECRET_KEY="S" + "B" * 55, STELLAR_NETWORK="testnet")
    fake = FakeChain()
    monkeypatch.setattr(onchain, "get_chain", lambda: fake)
    return fake


@pytest.fixture
def finished(admin, db):
    admin.post("/admin/tournaments", data={"sport": "scrabble", "name": "Clash", "format": "swiss", "held_on": "2026-03-14"})
    t = Tournament.query.filter_by(name="Clash").one()
    admin.post(f"/admin/t/{t.id}/participants/bulk", data={"lines": "Ama, ATU, 1300\nKofi, UG, 1250"})
    a, b = t.participants
    db.session.add(Game(tournament=t, round=1, board=1, p1=a, p2=b, score1=420, score2=380, spread=40, result=P1))
    t.status = "finished"
    db.session.commit()
    return t


def test_canonical_results_are_stable_and_leave_out_ids(finished, db):
    first = onchain.canonical_results(finished)
    assert first == onchain.canonical_results(finished)
    body = json.loads(first)
    assert body["schema"] == onchain.SCHEMA and body["tournament"]["held_on"] == "2026-03-14"
    assert body["games"][0]["p1"] == {"name": "AMA", "club": "ATU"} and "id" not in json.dumps(body["games"])
    assert body["standings"][0]["name"] == "AMA" and "rating" in body["standings"][0]["stats"]
    # Restored from a backup into a database without the original, it gets new ids but the same fingerprint.
    backup, digest, old_ids = export_tournament(finished), onchain.results_hash(finished), {p.id for p in finished.participants}
    import_data(export_tournament_stub())  # takes the next ids, so the restored copy can't reuse the old ones
    db.session.delete(finished)
    db.session.commit()
    copy = import_data(backup)
    assert not {p.id for p in copy.participants} & old_ids
    assert onchain.results_hash(copy) == digest


def test_any_result_change_changes_the_hash(finished, db):
    before = onchain.results_hash(finished)
    game = finished.games[0]
    game.score2, game.spread, game.result = 430, -10, P2
    db.session.commit()
    assert onchain.results_hash(finished) != before


def test_publish_records_versions_and_is_idempotent(chain, finished, db):
    anchor, created = onchain.publish(finished, by="td")
    assert created and (anchor.version, anchor.chain_key, anchor.published_by) == (1, finished.slug, "td")
    assert anchor.hash == onchain.results_hash(finished) and anchor.tx_hash.startswith("tx")
    # Same results again: no new transaction, no new version.
    again, created = onchain.publish(finished)
    assert not created and again.id == anchor.id and len(chain.calls) == 1
    # A correction becomes version 2; version 1 stays.
    finished.games[0].score1 = 425
    finished.games[0].spread = 45
    db.session.commit()
    v2, created = onchain.publish(finished)
    assert created and v2.version == 2 and [a.version for a in finished.anchors] == [1, 2]
    assert onchain.verify(finished)["match"]


def test_a_retry_whose_first_attempt_landed_counts_as_published(chain, finished, db):
    chain.lose_next_response = True
    with pytest.raises(onchain.OnchainError):
        onchain.publish(finished)
    assert chain.versions(finished.slug) == 1 and Anchor.query.count() == 0
    anchor, created = onchain.publish(finished)  # the chain already holds this hash: recorded, not re-sent
    assert not created and anchor.version == 1 and anchor.tx_hash is None
    assert [c for c in chain.calls if c[0] == "publish"] == [("publish", finished.slug, 1)]


def test_conflict_with_the_same_fingerprint_counts_as_up_to_date(chain, finished, db):
    chain.race_same_hash = True
    anchor, created = onchain.publish(finished)  # goes through the VersionConflict recovery branch
    assert not created and anchor.version == 1 and anchor.tx_hash is None and anchor.ledger == 2000
    assert chain.versions(finished.slug) == 1


def test_version_conflict_from_elsewhere_is_reported(chain, finished, db, monkeypatch):
    real_publish = chain.publish

    def raced(key, hex_hash, version):  # another publisher's v1 lands just before ours
        chain.records.setdefault(key, []).append({"version": 1, "hash": "f" * 64, "ledger": 5, "timestamp": 0})
        return real_publish(key, hex_hash, version)

    monkeypatch.setattr(chain, "publish", raced)
    with pytest.raises(onchain.OnchainError, match="published from somewhere else"):
        onchain.publish(finished)
    assert Anchor.query.count() == 0 and chain.versions(finished.slug) == 1


def test_rename_keeps_the_onchain_key(chain, admin, finished, db):
    onchain.publish(finished)
    old_slug = finished.slug
    admin.post(f"/admin/t/{finished.id}/settings", data={"name": "Clash Renamed", "status": "finished"})
    assert finished.slug != old_slug and onchain.chain_key(finished) == old_slug
    _, created = onchain.publish(finished)  # the name is part of the fingerprint, so this is v2 under the old key
    assert created and chain.versions(old_slug) == 2 and chain.versions(finished.slug) == 0


def test_only_finished_tournaments_publish_and_config_is_required(app, chain, finished, db):
    finished.status = "live"
    db.session.commit()
    with pytest.raises(onchain.OnchainError, match="Only finished"):
        onchain.publish(finished)
    finished.status = "finished"
    db.session.commit()
    app.config["STELLAR_SECRET_KEY"] = ""
    assert onchain.enabled() and not onchain.can_publish()
    with pytest.raises(onchain.OnchainError, match="not configured"):
        onchain.publish(finished)
    app.config["STELLAR_CONTRACT_ID"] = ""
    assert not onchain.enabled()
    with pytest.raises(onchain.OnchainError, match="not configured"):
        onchain.publish(finished)
    assert chain.calls == []


def test_extend_all_walks_versions_in_batches(chain, finished, db):
    onchain.publish(finished)
    key = finished.slug
    chain.records[key] += [{"version": v, "hash": "a" * 64, "ledger": v, "timestamp": 0} for v in range(2, 121)]
    assert onchain.extend_all() == 3
    assert [c[2:] for c in chain.calls if c[0] == "extend"] == [(1, 50), (51, 100), (101, 120)]


def test_cli_publish_and_verify(app, chain, finished, db):
    runner = app.test_cli_runner()
    out = runner.invoke(args=["onchain-publish", finished.slug])
    assert out.exit_code == 0 and "v1 published" in out.output and "stellar.expert" in out.output
    out = runner.invoke(args=["onchain-verify", finished.slug])
    assert out.exit_code == 0 and out.output.splitlines()[-1] == "MATCH"
    finished.games[0].score2 = 300
    db.session.commit()
    out = runner.invoke(args=["onchain-verify", finished.slug])
    assert out.exit_code == 1 and out.output.splitlines()[-1] == "MISMATCH"
    assert runner.invoke(args=["onchain-publish"]).exit_code != 0  # needs a slug or --all-finished
    assert isinstance(runner, CliRunner)


def test_chain_forces_extend_but_not_publish(monkeypatch):
    """extend changes no data, so the SDK treats it as read-only; it must still be submitted, or no TTL bump happens."""
    from stellar_sdk import Keypair

    submitted = []

    class Tx:
        send_transaction_response = type("R", (), {"hash": "ab" * 32})()
        get_transaction_response = type("R", (), {"ledger": 7})()

        def __init__(self, fn):
            self.fn = fn

        def sign_and_submit(self, force=False):
            submitted.append((self.fn, force))

    chain = onchain.Chain.__new__(onchain.Chain)
    chain.keypair = Keypair.random()
    chain.client = type("C", (), {"invoke": lambda self, fn, args, **kw: Tx(fn)})()
    assert chain.extend("slug", 1, 2) == ("ab" * 32, 7)
    chain.publish("slug", "00" * 32, 1)
    assert submitted == [("extend", True), ("publish", False)]


def test_unknown_network_is_rejected(app):
    app.config.update(STELLAR_CONTRACT_ID="C" + "A" * 55, STELLAR_NETWORK="futurenet-typo")
    with pytest.raises(onchain.OnchainError, match="Unknown STELLAR_NETWORK"):
        onchain.get_chain()


def test_sdk_and_network_errors_become_onchain_errors():
    from stellar_sdk import Keypair

    class Boom(Exception):
        pass

    def tx_failing(message):
        class Tx:
            def sign_and_submit(self, force=False):
                raise Boom(message)
        return Tx()

    chain = onchain.Chain.__new__(onchain.Chain)
    chain.keypair = Keypair.random()
    chain.client = type("C", (), {"invoke": lambda self, fn, args, **kw: tx_failing("connection reset")})()
    with pytest.raises(onchain.OnchainError, match="connection reset") as err:
        chain.publish("slug", "00" * 32, 1)
    assert not isinstance(err.value, onchain.VersionConflict)
    # A conflict that only shows up when the transaction fails on submit is still a VersionConflict.
    chain.client = type("C", (), {"invoke": lambda self, fn, args, **kw: tx_failing("HostError: Error(Contract, #2)")})()
    with pytest.raises(onchain.VersionConflict):
        chain.publish("slug", "00" * 32, 1)
    chain.client = type("C", (), {"invoke": lambda self, fn, args, **kw: (_ for _ in ()).throw(Boom("rpc down"))})()
    with pytest.raises(onchain.OnchainError, match="rpc down"):
        chain.versions("slug")
