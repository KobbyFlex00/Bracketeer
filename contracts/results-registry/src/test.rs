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
    assert_eq!(client.publish(&slug, &hash(&env, 1)), 1);
    env.ledger().with_mut(|l| l.sequence_number = 200);
    assert_eq!(client.publish(&slug, &hash(&env, 2)), 2);

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
    client.publish(&slug, &hash(&env, 7));
    assert_eq!(
        env.auths(),
        std::vec![(
            admin.clone(),
            AuthorizedInvocation {
                function: AuthorizedFunction::Contract((
                    client.address.clone(),
                    Symbol::new(&env, "publish"),
                    (slug.clone(), hash(&env, 7)).into_val(&env),
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
    client.publish(&String::from_str(&env, "spring-open"), &hash(&env, 7));
}

#[test]
fn rejects_bad_slugs() {
    let (env, _admin, client) = setup();
    env.mock_all_auths();
    assert_eq!(client.try_publish(&String::from_str(&env, ""), &hash(&env, 1)), Err(Ok(Error::BadSlug)));
    let long = String::from_str(&env, &"x".repeat(141));
    assert_eq!(client.try_publish(&long, &hash(&env, 1)), Err(Ok(Error::BadSlug)));
    assert_eq!(client.publish(&String::from_str(&env, &"x".repeat(140)), &hash(&env, 1)), 1);
}

#[test]
fn set_admin_hands_over_control() {
    let (env, old, client) = setup();
    env.mock_all_auths();
    let new = Address::generate(&env);
    client.set_admin(&new);
    assert_eq!(env.auths()[0].0, old);  // the old admin had to approve the handover
    assert_eq!(client.admin(), new);
    client.publish(&String::from_str(&env, "after"), &hash(&env, 3));
    assert_eq!(env.auths()[0].0, new);  // and now the new admin signs publishes
}

#[test]
fn extend_is_open_to_anyone_and_changes_nothing() {
    let (env, _admin, client) = setup();
    env.mock_all_auths();
    let slug = String::from_str(&env, "keep-me");
    client.publish(&slug, &hash(&env, 9));
    client.extend(&slug);
    assert!(env.auths().is_empty());  // no signature needed
    client.extend(&String::from_str(&env, "never-published"));
    assert_eq!(client.latest(&slug).unwrap().hash, hash(&env, 9));
}
