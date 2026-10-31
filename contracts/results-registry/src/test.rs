extern crate std;

use super::{Error, Record, ResultsRegistry, ResultsRegistryClient};
use soroban_sdk::testutils::{Address as _, AuthorizedFunction, AuthorizedInvocation, Ledger};
use soroban_sdk::{Address, BytesN, Env, IntoVal, String, Symbol};

fn setup() -> (Env, Address, ResultsRegistryClient<'static>) {
    let env = Env::default();
    let admin = Address::generate(&env);
    let id = env.register(ResultsRegistry, (&admin,));
    let client = ResultsRegistryClient::new(&env, &id);
    (env, admin, client)
}

fn hash(env: &Env, byte: u8) -> BytesN<32> {
    BytesN::from_array(env, &[byte; 32])
}

#[test]
fn constructor_sets_admin() {
    let (_env, admin, client) = setup();
    assert_eq!(client.admin(), admin);
}

#[test]
fn publish_appends_versions_and_keeps_history() {
    let (env, _admin, client) = setup();
    env.mock_all_auths();
    let slug = String::from_str(&env, "the-clash-of-the-word-wizards");
    assert_eq!(client.latest(&slug), None);
    assert_eq!(client.versions(&slug), 0);

    env.ledger().with_mut(|l| {
        l.sequence_number = 100;
        l.timestamp = 1_700_000_000;
    });
    assert_eq!(client.publish(&slug, &hash(&env, 1), &1), 1);
    env.ledger().with_mut(|l| l.sequence_number = 200);
    assert_eq!(client.publish(&slug, &hash(&env, 2), &2), 2);

    let first = Record { version: 1, hash: hash(&env, 1), ledger: 100, timestamp: 1_700_000_000 };
    assert_eq!(client.get(&slug, &1), Some(first));
    let latest = client.latest(&slug).unwrap();
    assert_eq!((latest.version, latest.hash, latest.ledger), (2, hash(&env, 2), 200));
    assert_eq!(client.versions(&slug), 2);
    assert_eq!(client.get(&slug, &3), None);
    // Other tournaments are independent.
    assert_eq!(client.latest(&String::from_str(&env, "other")), None);
}

#[test]
fn publish_requires_the_admin() {
    let (env, admin, client) = setup();
    env.mock_all_auths();
    let slug = String::from_str(&env, "spring-open");
    client.publish(&slug, &hash(&env, 7), &1);
    assert_eq!(
        env.auths(),
        std::vec![(
            admin.clone(),
            AuthorizedInvocation {
                function: AuthorizedFunction::Contract((
                    client.address.clone(),
                    Symbol::new(&env, "publish"),
                    (slug.clone(), hash(&env, 7), 1u32).into_val(&env),
                )),
                sub_invocations: std::vec![],
            }
        )]
    );
}

#[test]
#[should_panic]
fn publish_without_admin_auth_fails() {
    let (env, _admin, client) = setup();
    client.publish(&String::from_str(&env, "spring-open"), &hash(&env, 7), &1);
}

#[test]
fn rejects_bad_slugs() {
    let (env, _admin, client) = setup();
    env.mock_all_auths();
    assert_eq!(client.try_publish(&String::from_str(&env, ""), &hash(&env, 1), &1), Err(Ok(Error::BadSlug)));
    let long = String::from_str(&env, &"x".repeat(141));
    assert_eq!(client.try_publish(&long, &hash(&env, 1), &1), Err(Ok(Error::BadSlug)));
    assert_eq!(client.publish(&String::from_str(&env, &"x".repeat(140)), &hash(&env, 1), &1), 1);
}

#[test]
fn set_admin_hands_over_control() {
    let (env, old, client) = setup();
    env.mock_all_auths();
    let new = Address::generate(&env);
    client.set_admin(&new);
    assert_eq!(env.auths()[0].0, old);  // the old admin had to approve the handover
    assert_eq!(client.admin(), new);
    client.publish(&String::from_str(&env, "after"), &hash(&env, 3), &1);
    assert_eq!(env.auths()[0].0, new);  // and now the new admin signs publishes
}

#[test]
fn extend_is_open_to_anyone_and_changes_nothing() {
    let (env, _admin, client) = setup();
    env.mock_all_auths();
    let slug = String::from_str(&env, "keep-me");
    client.publish(&slug, &hash(&env, 9), &1);
    client.publish(&slug, &hash(&env, 10), &2);
    client.extend(&slug, &1, &2);
    assert!(env.auths().is_empty());  // no signature needed
    assert_eq!(client.latest(&slug).unwrap().hash, hash(&env, 10));
    assert_eq!(client.get(&slug, &1).unwrap().hash, hash(&env, 9));
}

#[test]
fn extend_checks_its_range() {
    let (env, _admin, client) = setup();
    env.mock_all_auths();
    let slug = String::from_str(&env, "ranges");
    for v in 1..=60u32 {
        client.publish(&slug, &hash(&env, v as u8), &v);
    }
    let bad = Err(Ok(Error::BadRange));
    assert_eq!(client.try_extend(&slug, &0, &1), bad);    // versions start at 1
    assert_eq!(client.try_extend(&slug, &3, &2), bad);    // from after to
    assert_eq!(client.try_extend(&slug, &59, &61), bad);  // past the latest
    assert_eq!(client.try_extend(&slug, &1, &51), bad);   // more than 50 at once
    assert_eq!(client.try_extend(&String::from_str(&env, "none"), &1, &1), bad);
    client.extend(&slug, &1, &50);
    client.extend(&slug, &51, &60);
}

#[test]
fn publish_must_name_the_next_version() {
    let (env, _admin, client) = setup();
    env.mock_all_auths();
    let slug = String::from_str(&env, "retry");
    let conflict = Err(Ok(Error::VersionConflict));
    assert_eq!(client.try_publish(&slug, &hash(&env, 1), &2), conflict);  // can't skip ahead
    assert_eq!(client.publish(&slug, &hash(&env, 1), &1), 1);
    // A retry of the same publish (or a delayed, older snapshot) still says version 1: rejected, nothing added.
    assert_eq!(client.try_publish(&slug, &hash(&env, 1), &1), conflict);
    assert_eq!(client.try_publish(&slug, &hash(&env, 0), &1), conflict);
    assert_eq!(client.versions(&slug), 1);
    assert_eq!(client.latest(&slug).unwrap().hash, hash(&env, 1));
}
