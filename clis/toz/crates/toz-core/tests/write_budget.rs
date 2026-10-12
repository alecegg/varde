use std::path::Path;

use tempfile::tempdir;
use toz_core::{
    capture::{self, CaptureInput, Outcome},
    chunk::{chunk_default, Chunk},
    config::{Config, Retention},
    store::{NewCapture, Store},
};
use varde_core::write_meter::{self, WriteMeter};

const BUDGET: &str = include_str!("../../../../write-budget.toml");
const CAPTURE_BYTES: usize = 64 * 1024;

fn budget(key: &str) -> u64 {
    toml::from_str::<toml::Value>(BUDGET)
        .unwrap()
        .get(key)
        .and_then(toml::Value::as_integer)
        .unwrap_or_else(|| panic!("missing integer write budget {key}")) as u64
}

fn ratio_budget(key: &str) -> f64 {
    let config = toml::from_str::<toml::Value>(BUDGET).unwrap();
    let value = config
        .get(key)
        .unwrap_or_else(|| panic!("missing write budget {key}"));
    value
        .as_float()
        .or_else(|| value.as_integer().map(|n| n as f64))
        .unwrap()
}

fn measured(path: &Path, setup_store: Store, operation: impl FnOnce(&mut Store)) -> u64 {
    setup_store
        .conn()
        .execute_batch("PRAGMA wal_checkpoint(TRUNCATE)")
        .unwrap();
    drop(setup_store);
    let mut store = Store::open(path).unwrap();
    let meter = WriteMeter::start();
    operation(&mut store);
    store
        .conn()
        .execute_batch("PRAGMA wal_checkpoint(TRUNCATE)")
        .unwrap();
    drop(store);
    meter.bytes()
}

fn capture_sample() -> u64 {
    let dir = tempdir().unwrap();
    let path = dir.path().join("store.db");
    let store = Store::open(&path).unwrap();
    let mut output = String::new();
    for i in 0.. {
        output.push_str(&format!(
            "capture record {i:04} has useful searchable words and trace data\n"
        ));
        if output.len() >= CAPTURE_BYTES {
            break;
        }
    }
    output.truncate(CAPTURE_BYTES);
    let input = CaptureInput::new(output.as_bytes(), "budget capture", "capture");
    measured(&path, store, |store| {
        let outcome = capture::run(&Config::default(), store, input, &[]).unwrap();
        assert!(matches!(outcome, Outcome::Captured(_)));
    })
}

fn retention(days: u64, max_mb: u64) -> Retention {
    Retention {
        days,
        superseded_days: days,
        max_mb,
    }
}

fn capture_row(label: &str) -> NewCapture<'_> {
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

fn tombstone_fixture(path: &Path) -> (Store, u64) {
    let mut store = Store::open(path).unwrap();
    for i in 0..24 {
        let label = format!("aged{i}");
        let body = (0..160)
            .map(|n| format!("{label} record-{n} unique-{n:04} {}\n", "x".repeat(180)))
            .collect::<String>();
        store
            .insert_capture(&capture_row(&label), &chunks(&body))
            .unwrap();
    }
    rusqlite::Connection::open(path)
        .unwrap()
        .execute(
            "UPDATE captures SET created_at = 0 WHERE label LIKE 'aged%'",
            [],
        )
        .unwrap();
    let size = store.db_size_bytes().unwrap() as u64;
    (store, size)
}

fn assert_repeat(name: &str, first: u64, second: u64) {
    let difference = first.abs_diff(second);
    assert!(
        difference * 4 <= first.max(second),
        "{name} write samples differ by more than 25%: {first} and {second}"
    );
}

fn scaled_ratio(key: &str) -> f64 {
    write_meter::scaled((ratio_budget(key) * 1000.0) as u64) as f64 / 1000.0
}

#[test]
fn toz_write_budgets() {
    assert!(write_meter::available(), "process write meter unavailable");

    let captures = [capture_sample(), capture_sample()];
    eprintln!("capture samples={captures:?}");
    assert_repeat("capture", captures[0], captures[1]);
    let capture_ratio = captures.into_iter().max().unwrap() as f64 / CAPTURE_BYTES as f64;
    assert!(
        capture_ratio <= write_meter::scaled(budget("toz_capture_ratio_x")) as f64,
        "capture ratio {capture_ratio:.2} exceeds budget"
    );

    let healthy = [healthy_prune_sample(), healthy_prune_sample()];
    assert_repeat("healthy prune", healthy[0], healthy[1]);
    for bytes in healthy {
        assert!(
            bytes <= write_meter::scaled(budget("toz_prune_healthy_bytes")),
            "healthy prune wrote {bytes} bytes"
        );
    }

    let (first_a, second_a, size_a) = tombstone_samples();
    let (first_b, second_b, size_b) = tombstone_samples();
    assert_repeat("tombstone first prune", first_a, first_b);
    assert_repeat("tombstone second prune", second_a, second_b);
    let first_ratio = (first_a as f64 / size_a as f64).max(first_b as f64 / size_b as f64);
    assert!(
        first_ratio <= scaled_ratio("toz_prune_tombstone_ratio_x"),
        "first prune ratio {first_ratio:.2} exceeds budget"
    );
    for bytes in [second_a, second_b] {
        assert!(
            bytes <= write_meter::scaled(budget("toz_prune_runaway_second_pass_bytes")),
            "second prune wrote {bytes} bytes"
        );
    }
    eprintln!("toz-core write samples capture={captures:?}, healthy={healthy:?}, tombstone_first=[{first_a},{first_b}] of [{size_a},{size_b}], tombstone_second=[{second_a},{second_b}]");
}

fn healthy_prune_sample() -> u64 {
    let dir = tempdir().unwrap();
    let path = dir.path().join("store.db");
    let store = Store::open(&path).unwrap();
    measured(&path, store, |store| {
        store.prune(&retention(36_500, 500)).unwrap();
    })
}

fn tombstone_samples() -> (u64, u64, u64) {
    let dir = tempdir().unwrap();
    let path = dir.path().join("store.db");
    let (store, before_size) = tombstone_fixture(&path);
    let first = measured(&path, store, |store| {
        assert_eq!(store.prune(&retention(0, 1)).unwrap(), 24);
        assert!(store.db_size_bytes().unwrap() <= 1024 * 1024);
    });
    let store = Store::open(&path).unwrap();
    let second = measured(&path, store, |store| {
        store.prune(&retention(36_500, 1)).unwrap();
    });
    eprintln!("tombstone pre-prune DB size={before_size}");
    (first, second, before_size)
}
