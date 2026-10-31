//! Bracketeer results registry.
//!
//! When a tournament finishes, the Bracketeer backend publishes the SHA-256 of the tournament's canonical
//! results (games, standings and ratings, serialised deterministically by the app) under its slug. Records
//! are append-only: a correction is published as a new version and every earlier version stays readable, so
//! anyone can check the results shown on the site against what was published, and see if they ever changed.
#![no_std]

use soroban_sdk::{contract, contracterror, contractevent, contractimpl, contracttype, Address, BytesN, Env, String};

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Record {
    pub version: u32,
    pub hash: BytesN<32>,
    pub ledger: u32,
    pub timestamp: u64,
}

#[contracttype]
enum DataKey {
    Admin,
    Latest(String),
    Record(String, u32),
}

#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
#[repr(u32)]
pub enum Error {
    /// Slugs are 1..=140 bytes, matching Bracketeer's tournaments.slug column.
    BadSlug = 1,
    /// `version` must be exactly latest + 1, so a retried or reordered publish can't add a stray version.
    VersionConflict = 2,
    /// `extend` takes 1 <= from <= to <= latest, at most MAX_EXTEND versions per call.
    BadRange = 3,
}

/// Emitted on every publish so indexers and explorers can follow new results.
#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Published {
    #[topic]
    pub slug: String,
    pub version: u32,
    pub hash: BytesN<32>,
}

/// Emitted when control passes to a new admin key (e.g. from a deploy key to the club's own key).
#[contractevent]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdminChanged {
    pub admin: Address,
}

const MAX_SLUG: u32 = 140;
const MAX_EXTEND: u32 = 50;

#[contract]
pub struct ResultsRegistry;

#[contractimpl]
impl ResultsRegistry {
    /// The admin is fixed at deploy time, so there is no window in which someone else could claim the contract.
    pub fn __constructor(env: Env, admin: Address) {
        env.storage().instance().set(&DataKey::Admin, &admin);
    }

    pub fn admin(env: Env) -> Address {
        Self::stored_admin(&env)
    }

    /// Hand control to another key. Only the current admin can do this.
    pub fn set_admin(env: Env, new_admin: Address) {
        Self::stored_admin(&env).require_auth();
        env.storage().instance().set(&DataKey::Admin, &new_admin);
        Self::bump_instance(&env);
        AdminChanged { admin: new_admin }.publish(&env);
    }

    /// Append version `version` of a tournament's results hash; it must be exactly latest + 1 (1 for the first).
    /// The caller names the version it means to create, so a retry after an uncertain result, or a delayed
    /// transaction, fails with VersionConflict instead of appending a duplicate or a stale snapshot.
    pub fn publish(env: Env, slug: String, hash: BytesN<32>, version: u32) -> Result<u32, Error> {
        Self::stored_admin(&env).require_auth();
        if slug.len() == 0 || slug.len() > MAX_SLUG {
            return Err(Error::BadSlug);
        }
        if version != Self::latest_version(&env, &slug) + 1 {
            return Err(Error::VersionConflict);
        }
        let record = Record { version, hash: hash.clone(), ledger: env.ledger().sequence(), timestamp: env.ledger().timestamp() };
        let store = env.storage().persistent();
        store.set(&DataKey::Record(slug.clone(), version), &record);
        store.set(&DataKey::Latest(slug.clone()), &version);
        Self::bump(&env, &DataKey::Record(slug.clone(), version));
        Self::bump(&env, &DataKey::Latest(slug.clone()));
        Self::bump_instance(&env);
        Published { slug, version, hash }.publish(&env);
        Ok(version)
    }

    /// The most recent record for a tournament, if it has ever been published.
    pub fn latest(env: Env, slug: String) -> Option<Record> {
        let version = Self::latest_version(&env, &slug);
        if version == 0 {
            return None;
        }
        env.storage().persistent().get(&DataKey::Record(slug, version))
    }

    /// A specific earlier version, so corrections can be audited.
    pub fn get(env: Env, slug: String, version: u32) -> Option<Record> {
        env.storage().persistent().get(&DataKey::Record(slug, version))
    }

    /// How many versions a tournament has (0 if never published).
    pub fn versions(env: Env, slug: String) -> u32 {
        Self::latest_version(&env, &slug)
    }

    /// Keep versions `from..=to` of a tournament (and its latest pointer) live, not archived. Anyone may pay
    /// for this; it changes no data. Bounded per call so long histories can be refreshed in batches.
    pub fn extend(env: Env, slug: String, from: u32, to: u32) -> Result<(), Error> {
        let latest = Self::latest_version(&env, &slug);
        if from == 0 || from > to || to > latest || to - from >= MAX_EXTEND {
            return Err(Error::BadRange);
        }
        Self::bump(&env, &DataKey::Latest(slug.clone()));
        for version in from..=to {
            Self::bump(&env, &DataKey::Record(slug.clone(), version));
        }
        Self::bump_instance(&env);
        Ok(())
    }

    fn stored_admin(env: &Env) -> Address {
        env.storage().instance().get(&DataKey::Admin).expect("constructed with an admin")
    }

    fn latest_version(env: &Env, slug: &String) -> u32 {
        env.storage().persistent().get(&DataKey::Latest(slug.clone())).unwrap_or(0)
    }

    fn bump(env: &Env, key: &DataKey) {
        let max = env.storage().max_ttl();
        env.storage().persistent().extend_ttl(key, max, max);
    }

    fn bump_instance(env: &Env) {
        let max = env.storage().max_ttl();
        env.storage().instance().extend_ttl(max, max);
    }
}

#[cfg(test)]
mod test;
