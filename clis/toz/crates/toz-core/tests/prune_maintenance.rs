use std::{fs, path::Path};

use tempfile::tempdir;
use toz_core::{
    chunk::{Chunk, chunk_default},
    config::Retention,
    search::{self, SearchOpts},
    store::{NewCapture, Store},
};

fn capture(label: &str) -> NewCapture<'_> {
    NewCapture {
        label,
        kind: "run",
        source: label,
        source_key: "",
        legacy_source_key: None,
        bytes: 32_000,
        exit_code: Some(0),
        session: None,
        redactions: 0,
        binary: false,
        file_mtime: None,
        file_hash: None,
    }
}

fn chunks(body: &str) -> Vec<(String, Chunk)> {
    chunk_default(body)
        .into_iter()
        .map(|chunk| ("stdout".to_string(), chunk))
        .collect()
}

fn open(path: &Path) -> Store {
    Store::open(path).unwrap()
}

fn store_bytes(store: &Store) -> i64 {
    store.db_size_bytes().unwrap()
}

fn page_count(path: &Path) -> i64 {
    rusqlite::Connection::open(path)
        .unwrap()
        .query_row("PRAGMA page_count", [], |row| row.get(0))
        .unwrap()
}

fn retention(days: u64, max_mb: u64) -> Retention {
    Retention {
        days,
        superseded_days: days,
        max_mb,
    }
}

fn payload(tag: &str) -> String {
    (0..160)
        .map(|i| format!("{tag} record-{i} unique-{:04} {}\n", i, "x".repeat(180)))
        .collect()
}

#[test]
fn prune_recovers_tombstone_heavy_store() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("store.db");
    let mut store = open(&path);
    for i in 0..24 {
        let body = payload(&format!("aged{i}"));
        store
            .insert_capture(&capture(&format!("aged{i}")), &chunks(&body))
            .unwrap();
    }
    rusqlite::Connection::open(&path)
        .unwrap()
        .execute(
            "UPDATE captures SET created_at = 0 WHERE label LIKE 'aged%'",
            [],
        )
        .unwrap();
    let survivor_body = "survivor retained text\n".repeat(100);
    let survivor = store
        .insert_capture(&capture("survivor"), &chunks(&survivor_body))
        .unwrap();
    let before = store_bytes(&store);
    let removed = store.prune(&retention(0, 1)).unwrap();
    let after = store_bytes(&store);

    assert_eq!(removed, 24);
    assert!(
        before > after * 4,
        "file size {before} did not shrink 4x to {after}"
    );
    assert!(after <= 1024 * 1024, "file remains over cap: {after}");
    assert!(store.get_by_handle(&survivor).unwrap().is_some());
}

#[test]
fn prune_steady_state_at_cap_is_cheap() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("store.db");
    let mut store = open(&path);
    let cap_bytes = 2 * 1024 * 1024;
    let policy = retention(36_500, 2);
    let mut seeded = 0;
    while store_bytes(&store) < cap_bytes * 9 / 10 {
        let label = format!("steady{seeded}");
        let body = format!("{label} {}\n", "steady text ".repeat(32));
        store
            .insert_capture(&capture(&label), &chunks(&body))
            .unwrap();
        seeded += 1;
    }
    let seeded_bytes = store_bytes(&store);
    assert!(
        seeded_bytes <= cap_bytes,
        "seed exceeded cap: {seeded_bytes}"
    );
    assert!(
        seeded_bytes >= cap_bytes * 9 / 10,
        "seed below cap: {seeded_bytes}"
    );
    // The initial prune can reclaim pages left by seeding; measure steady state afterward.
    store.prune(&policy).unwrap();
    for i in 0..3 {
        // Page-count bytes measure allocated database pages, not OS write I/O.
        let before = store_bytes(&store);
        let pages_before = page_count(&path);
        store.prune(&policy).unwrap();
        let maintained = store_bytes(&store);
        assert!(
            (maintained - before).abs() <= 16 * 4096,
            "maintenance changed allocated page bytes by {}",
            maintained - before
        );
        assert!((page_count(&path) - pages_before).abs() <= 16);
        assert!(
            maintained <= cap_bytes,
            "maintenance exceeded cap: {maintained}"
        );
        let body = format!("small insert {i} {}\n", "x".repeat(128));
        store
            .insert_capture(&capture(&format!("small{i}")), &chunks(&body))
            .unwrap();
    }
}

#[test]
fn prune_second_pass_is_cheap() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("store.db");
    let mut store = open(&path);
    for i in 0..36 {
        let body = payload(&format!("second{i}"));
        store
            .insert_capture(&capture(&format!("second{i}")), &chunks(&body))
            .unwrap();
    }
    rusqlite::Connection::open(&path)
        .unwrap()
        .execute(
            "UPDATE captures SET created_at = 0 WHERE label LIKE 'second%'",
            [],
        )
        .unwrap();
    for i in 0..2 {
        let body = format!("live {i} retained content\n").repeat(10);
        store
            .insert_capture(&capture(&format!("live{i}")), &chunks(&body))
            .unwrap();
    }
    let before = store_bytes(&store);
    assert_eq!(store.prune(&retention(0, 1)).unwrap(), 36);
    let first_size = store_bytes(&store);
    let first_pages = page_count(&path);
    let first_file_size = fs::metadata(&path).unwrap().len();
    assert!(
        first_size < before,
        "first pass did not shrink file: {before} to {first_size}"
    );
    store.prune(&retention(36_500, 1)).unwrap();
    assert_eq!(store_bytes(&store), first_size);
    assert_eq!(page_count(&path), first_pages);
    assert_eq!(fs::metadata(&path).unwrap().len(), first_file_size);
}

#[test]
fn search_unchanged_after_optimize() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("store.db");
    let mut store = open(&path);
    store
        .insert_capture(
            &capture("expired"),
            &chunks("expiredonly marker for old capture\n"),
        )
        .unwrap();
    rusqlite::Connection::open(&path)
        .unwrap()
        .execute(
            "UPDATE captures SET created_at = 0 WHERE label = 'expired'",
            [],
        )
        .unwrap();
    for (label, body) in [
        ("porter", "running runners searched the meadow\n"),
        ("trigram", "quartzneedle is a distinctive substring\n"),
        ("prefix", "prefixable prefixes prefixing\n"),
        ("tie-a", "sharedneedle appears in tied result\n"),
        ("tie-b", "sharedneedle appears in tied result\n"),
        ("delete", "quartzneedle deleted result\n"),
    ] {
        store
            .insert_capture(&capture(label), &chunks(body))
            .unwrap();
    }
    let queries = [
        "run".into(),
        "needle".into(),
        "pre".into(),
        "nomatchzz".into(),
        "sharedneedle".into(),
    ];
    let opts = SearchOpts {
        limit: 20,
        ..SearchOpts::default()
    };
    let before = search::search(&store, &queries, &opts).unwrap();
    assert_eq!(store.prune(&retention(0, 500)).unwrap(), 1);
    let after = search::search(&store, &queries, &opts).unwrap();
    assert_eq!(before[4].hits.len(), 2, "expected both tied-rank captures");
    assert_eq!(
        serde_json::to_value(before).unwrap(),
        serde_json::to_value(after).unwrap()
    );
}
