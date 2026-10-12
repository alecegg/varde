use rusqlite::Connection;
use varde_core::write_meter::{WriteMeter, available, scaled};
use varde_learn_core::friction_log::{Event, EventBody, ItemAdded, OccurrenceAppended};
use varde_learn_core::{FrictionAddMode, FrictionAddRequest, Store};
use std::io::Write;

const BUDGETS: &str = include_str!("../../../../write-budget.toml");

#[test]
fn one_friction_add_stays_within_write_budget() {
    assert!(available(), "write meter is unavailable on this platform");

    let root = tempfile::tempdir().unwrap();
    let store_dir = root.path().join("store");
    let cwd = root.path().join("repo");
    std::fs::create_dir_all(&cwd).unwrap();
    std::fs::create_dir_all(&store_dir).unwrap();
    let mut log = std::fs::File::create(store_dir.join("friction.jsonl")).unwrap();
    for index in 0..150 {
        let timestamp = format!("2026-10-11T00:00:{index:03}Z");
        let item = Event::at(
            timestamp.clone(),
            None,
            EventBody::ItemAdded(ItemAdded {
                title: format!("fixture friction {index}"),
                source: "budget fixture".to_owned(),
                repo_root: None,
                target: None,
            }),
        );
        let occurrence = Event::at(
            format!("2026-10-11T00:01:{index:03}Z"),
            None,
            EventBody::OccurrenceAppended(Box::new(OccurrenceAppended {
                item: item.id.clone(),
                at: timestamp,
                cwd: cwd.display().to_string(),
                repo_root: None,
                head_sha: None,
                evidence: "fixture event".to_owned(),
                cost: None,
                provenance: None,
            })),
        );
        writeln!(log, "{}", serde_json::to_string(&item).unwrap()).unwrap();
        writeln!(log, "{}", serde_json::to_string(&occurrence).unwrap()).unwrap();
    }
    drop(log);
    let store = Store::open(&store_dir).unwrap();
    drop(store);
    let setup_connection = Connection::open(store_dir.join("learn.db")).unwrap();
    setup_connection
        .execute_batch("PRAGMA wal_checkpoint(TRUNCATE)")
        .unwrap();
    drop(setup_connection);

    let meter = WriteMeter::start();
    let mut store = Store::open(&store_dir).unwrap();
    store
        .add_friction(FrictionAddRequest {
            mode: FrictionAddMode::Create {
                source: "budget test".to_owned(),
                title: "measured friction".to_owned(),
                target: None,
                global: true,
            },
            evidence: "one measured occurrence".to_owned(),
            cwd,
        })
        .unwrap();
    drop(store);

    let connection = Connection::open(store_dir.join("learn.db")).unwrap();
    connection
        .execute_batch("PRAGMA wal_checkpoint(TRUNCATE)")
        .unwrap();
    drop(connection);
    let written = meter.bytes();
    eprintln!("friction_add_bytes measured: {written}");

    let budgets: toml::Value = toml::from_str(BUDGETS).unwrap();
    let limit = scaled(budgets["friction_add_bytes"].as_integer().unwrap() as u64);
    assert!(written <= limit, "one friction add wrote {written} bytes; budget is {limit}");
}
