"""Publishing tournament result fingerprints to the Stellar results registry (contracts/results-registry).

A finished tournament is serialised deterministically (canonical_results) and its SHA-256 is published under a
stable key. Anyone can recompute the hash from the site's data and compare it with the chain. Ratings are part of
the fingerprint, so a later change to them (an edited earlier tournament, merged profiles) shows up as a mismatch
until a new version is published; every version stays onchain.
"""
import hashlib
import json

from flask import current_app

from .extensions import db
from .models import Anchor, Tournament
from .ratings import career_ratings

SCHEMA = "bracketeer.results/1"
EXTEND_BATCH = 50  # the contract's per-call limit for extend()
NETWORKS = {
    "testnet": ("https://soroban-testnet.stellar.org", "Test SDF Network ; September 2015"),
    "mainnet": ("", "Public Global Stellar Network ; September 2015"),  # mainnet needs a third-party RPC URL
}
EXPLORER = {"testnet": "https://stellar.expert/explorer/testnet", "mainnet": "https://stellar.expert/explorer/public"}


class OnchainError(Exception):
    pass


class VersionConflict(OnchainError):
    """The contract refused the version number: someone published in between, or a retry already landed."""


# ---------- fingerprint ----------

def _name(p):
    return {"name": p.name, "club": p.club or ""} if p else None


def canonical_results(t: Tournament) -> bytes:
    """The tournament as bytes that only change when its results do. Internal database ids are left out, so a
    restored backup or another database produces the same bytes; so is the slug, which changes on rename."""
    rules = t.rules
    career = career_ratings(t.sport) if rules.has_ratings else None
    rows = rules.standings(t, career=career)
    games = sorted(
        ({"round": g.round, "stage": g.stage, "board": g.board, "p1": _name(g.p1), "p2": _name(g.p2),
          "score1": g.score1, "score2": g.score2, "spread": g.spread, "pen_winner": g.pen_winner, "result": g.result}
         for g in t.games),
        key=lambda g: (g["round"], g["board"], g["p1"]["name"], (g["p2"] or {}).get("name", "")),
    )
    payload = {
        "schema": SCHEMA,
        "tournament": {"name": t.name, "sport": t.sport, "format": t.format,
                       "held_on": t.held_on.isoformat() if t.held_on else None, "settings": t.settings or {}},
        "participants": sorted(({**_name(p), "seed_rating": p.seed_rating, "active": p.active} for p in t.participants),
                               key=lambda p: (p["name"], p["club"])),
        "games": games,
        "standings": [{"rank": r.rank, **_name(r.p), "stats": {k: v for k, v in r.stats.items()}} for r in rows],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def results_hash(t: Tournament) -> str:
    return hashlib.sha256(canonical_results(t)).hexdigest()


# ---------- configuration ----------

def _cfg(key):
    return current_app.config.get(key) or ""


def enabled() -> bool:
    """Onchain status is shown at all (a contract is configured)."""
    return bool(_cfg("STELLAR_CONTRACT_ID"))


def can_publish() -> bool:
    return enabled() and bool(_cfg("STELLAR_SECRET_KEY"))


def network() -> str:
    return _cfg("STELLAR_NETWORK") or "testnet"


def explorer_url(kind: str, ident: str) -> str:
    return f"{EXPLORER.get(network(), EXPLORER['testnet'])}/{kind}/{ident}"


# ---------- chain client ----------

class Chain:
    """The few contract calls Bracketeer makes, via stellar-sdk's ContractClient (simulate, sign, submit)."""

    def __init__(self, contract_id, rpc_url, passphrase, secret=""):
        from stellar_sdk import Keypair
        from stellar_sdk.contract import ContractClient

        self.client = ContractClient(contract_id, rpc_url, passphrase)
        self.keypair = Keypair.from_secret(secret) if secret else None

    @staticmethod
    def _translate(e: Exception) -> OnchainError:
        """SDK and network failures become OnchainError; the contract's VersionConflict (#2) keeps its own type,
        whether the simulation caught it or the transaction failed on submit after a publish raced ahead."""
        if "Error(Contract, #2)" in str(e):
            return VersionConflict(str(e))
        return OnchainError(f"Stellar call failed: {e}")

    def _read(self, fn, *args):
        try:
            return self.client.invoke(fn, list(args)).result()
        except OnchainError:
            raise
        except Exception as e:  # RPC/transport errors from stellar-sdk or the HTTP client
            raise self._translate(e) from e

    def _write(self, fn, *args, force=False):
        if self.keypair is None:
            raise OnchainError("No STELLAR_SECRET_KEY is configured, so nothing can be published.")
        try:
            tx = self.client.invoke(fn, list(args), source=self.keypair.public_key, signer=self.keypair)
            tx.sign_and_submit(force=force)
        except OnchainError:
            raise
        except Exception as e:
            raise self._translate(e) from e
        sent, done = tx.send_transaction_response, tx.get_transaction_response
        return getattr(sent, "hash", None), getattr(done, "ledger", None)

    def latest(self, key):
        from stellar_sdk import scval

        value = scval.to_native(self._read("latest", scval.to_string(key)))
        if not value:
            return None
        return {"version": value["version"], "hash": value["hash"].hex(), "ledger": value["ledger"],
                "timestamp": value["timestamp"]}

    def versions(self, key) -> int:
        from stellar_sdk import scval

        return scval.to_native(self._read("versions", scval.to_string(key)))

    def publish(self, key, hex_hash, version):
        from stellar_sdk import scval

        return self._write("publish", scval.to_string(key), scval.to_bytes(bytes.fromhex(hex_hash)),
                           scval.to_uint32(version))

    def extend(self, key, start, end):
        from stellar_sdk import scval

        # extend changes no data, so the SDK classes it as a read call; but the TTL bump only happens when the
        # transaction is actually submitted, so force it through.
        return self._write("extend", scval.to_string(key), scval.to_uint32(start), scval.to_uint32(end), force=True)


def get_chain() -> Chain:
    """The chain client for the configured network. Tests replace this with a fake."""
    if network() not in NETWORKS:
        raise OnchainError(f"Unknown STELLAR_NETWORK {network()!r}; use one of: {', '.join(NETWORKS)}.")
    rpc, passphrase = NETWORKS[network()]
    rpc = _cfg("STELLAR_RPC_URL") or rpc
    if not rpc:
        raise OnchainError(f"Set STELLAR_RPC_URL for the {network()} network.")
    return Chain(_cfg("STELLAR_CONTRACT_ID"), rpc, passphrase, _cfg("STELLAR_SECRET_KEY"))


# ---------- publish / verify / keep alive ----------

def chain_key(t: Tournament) -> str:
    """Where this tournament lives onchain: the slug it was first published under, so a rename doesn't lose it."""
    first = next((a for a in t.anchors if a.network == network() and a.contract_id == _cfg("STELLAR_CONTRACT_ID")), None)
    return first.chain_key if first else t.slug


def published(t: Tournament) -> list[Anchor]:
    """This tournament's versions on the configured network and contract, oldest first."""
    return [a for a in t.anchors if a.network == network() and a.contract_id == _cfg("STELLAR_CONTRACT_ID")]


def publish(t: Tournament, by: str = "") -> tuple[Anchor, bool]:
    """Publish the tournament's current fingerprint. Returns (anchor, created); created is False when the chain
    already holds this exact fingerprint as its latest version (publishing again is a no-op, not a new version)."""
    if not can_publish():
        raise OnchainError("Stellar publishing is not configured (STELLAR_CONTRACT_ID and STELLAR_SECRET_KEY).")
    if t.status != "finished":
        raise OnchainError("Only finished tournaments can be published. Set the status to Finished first.")
    chain, key, digest = get_chain(), chain_key(t), results_hash(t)
    latest = chain.latest(key)
    if latest and latest["hash"] == digest:
        return _record(t, key, latest["version"], digest, None, latest["ledger"], by), False
    version = (latest["version"] if latest else 0) + 1
    try:
        tx_hash, ledger = chain.publish(key, digest, version)
    except VersionConflict:
        # A retry whose first attempt landed, or a publish from elsewhere in between: look before deciding.
        latest = chain.latest(key)
        if not latest or latest["hash"] != digest:
            raise OnchainError("This tournament was just published from somewhere else. Reload and try again.") from None
        # This exact fingerprint is already onchain, but this call can't claim to have put it there.
        return _record(t, key, latest["version"], digest, None, latest["ledger"], by), False
    return _record(t, key, version, digest, tx_hash, ledger, by), True


def _record(t, key, version, digest, tx_hash, ledger, by) -> Anchor:
    anchor = next((a for a in published(t) if a.version == version), None)
    if anchor is None:
        anchor = Anchor(tournament=t, chain_key=key, version=version, hash=digest, network=network(),
                        contract_id=_cfg("STELLAR_CONTRACT_ID"), tx_hash=tx_hash, ledger=ledger, published_by=by or "")
        db.session.add(anchor)
    elif tx_hash and not anchor.tx_hash:
        anchor.tx_hash = tx_hash
    db.session.commit()
    return anchor


def verify(t: Tournament) -> dict:
    """Compare the fingerprint of the site's current data with the latest one onchain."""
    digest = results_hash(t)
    record = get_chain().latest(chain_key(t))
    return {"local": digest, "onchain": record, "match": bool(record) and record["hash"] == digest}


def extend_all() -> int:
    """Keep every published version alive (not archived). Returns how many extend calls were made."""
    chain, calls = get_chain(), 0
    keys = {a.chain_key for a in Anchor.query.filter_by(network=network(), contract_id=_cfg("STELLAR_CONTRACT_ID"))}
    for key in sorted(keys):
        total = chain.versions(key)
        for start in range(1, total + 1, EXTEND_BATCH):
            chain.extend(key, start, min(start + EXTEND_BATCH - 1, total))
            calls += 1
    return calls
