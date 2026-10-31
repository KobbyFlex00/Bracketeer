# Bracketeer on Stellar: results registry

A Soroban smart contract that keeps an **append-only record of tournament result hashes**. When a tournament
finishes, Bracketeer serialises its games, standings and ratings deterministically and publishes the SHA-256
under the tournament's slug. Anyone can then recompute the hash from the site's data and compare it with the
chain. A correction is published as a new version; earlier versions stay readable.

## Deployed

| Network | Contract id |
|---|---|
| testnet | [`CAM3C37JBBCXWWKQRSTGAC36OFB54KBKMPYGJMAQRRCBFSQLC2NOGAYP`](https://stellar.expert/explorer/testnet/contract/CAM3C37JBBCXWWKQRSTGAC36OFB54KBKMPYGJMAQRRCBFSQLC2NOGAYP) |

Admin is currently a temporary deploy key; it moves to the club's own key with `set_admin`.

## Interface

| Function | Who | What |
|---|---|---|
| `__constructor(admin)` | deploy | sets the admin key (no separate init, so no front-running window) |
| `publish(slug, hash, version) -> u32` | admin | appends `version`, which must be latest + 1 (so a retry or delayed tx can't add a stray version: `VersionConflict`); emits `Published { slug, version, hash }` |
| `latest(slug) -> Option<Record>` | anyone | newest `{ version, hash, ledger, timestamp }` |
| `get(slug, version) -> Option<Record>` | anyone | a specific earlier version |
| `versions(slug) -> u32` | anyone | how many versions exist |
| `set_admin(new_admin)` | admin | hand control to another key, emits `AdminChanged` |
| `admin() -> Address` | anyone | current admin |
| `extend(slug, from, to)` | anyone | refresh versions `from..=to` (≤ 50 per call) and the latest pointer so they aren't archived; changes no data |

Records live in persistent storage. A publish extends the new record's TTL to the network maximum (about six
months on current limits); older versions are kept alive by calling `extend` periodically (Bracketeer will run
this as a keeper). Even if a record is archived it is not lost: persistent entries can be restored.

## Develop

```bash
rustup target add wasm32v1-none
cargo install --locked stellar-cli      # needs libdbus-1-dev + pkg-config on Linux, ~6 GB RAM to compile
cd contracts
cargo test                              # unit tests (soroban-sdk testutils)
stellar contract build                  # -> target/wasm32v1-none/release/results_registry.wasm
```

## Deploy (testnet)

```bash
stellar keys generate deployer --network testnet --fund
./contracts/deploy.sh deployer <ADMIN_G_ADDRESS> testnet   # prints the contract id (C...)
```

Read it back:

```bash
stellar contract invoke --id <C...> --network testnet --source-account deployer -- latest --slug the-clash-of-the-word-wizards
```

Testnet is reset periodically (next: 16 Dec 2026). After a reset, redeploy and republish.
