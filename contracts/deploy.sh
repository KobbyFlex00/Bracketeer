#!/usr/bin/env bash
# Build and deploy the results registry, with ADMIN as its admin.
# Repeatable on purpose: Stellar testnet is wiped periodically (next: 16 Dec 2026) and needs a fresh deploy.
#
#   ./contracts/deploy.sh <source-identity> <admin-G-address> [network]
#
# <source-identity> is a `stellar keys` identity that pays for the deploy (e.g. created with
#   stellar keys generate deployer --network testnet --fund
# ). <admin-G-address> is the public key Bracketeer signs publishes with (its STELLAR_SECRET_KEY).
# Prints the contract id; put it in STELLAR_CONTRACT_ID.
set -euo pipefail
cd "$(dirname "$0")"
SOURCE=${1:?source identity}
ADMIN=${2:?admin G... address}
NETWORK=${3:-testnet}

stellar contract build --package results-registry >&2
stellar contract deploy \
  --wasm target/wasm32v1-none/release/results_registry.wasm \
  --source-account "$SOURCE" --network "$NETWORK" \
  -- --admin "$ADMIN"
