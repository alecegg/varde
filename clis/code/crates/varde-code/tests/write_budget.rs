use rusqlite::Connection;
use std::path::{Path, PathBuf};
use tempfile::TempDir;
use varde_code::db::path::repo_db_path;
use varde_code::slice::{Scope, Slice, ensure_fresh};
use varde_core::write_meter::{WriteMeter, available, scaled};

const BUDGETS: &str = include_str!("../../../../write-budget.toml");

struct Fixture {
    _temp: TempDir,
    repo: PathBuf,
    previous_config: Option<std::ffi::OsString>,
}

impl Fixture {
    fn new(file_count: usize) -> Self {
        let temp = tempfile::tempdir().expect("temporary fixture directory");
        let repo = temp.path().join("repo");
        let config = temp.path().join("config");
        std::fs::create_dir_all(&repo).expect("repo directory");
        std::fs::create_dir_all(&config).expect("config directory");
        for i in 0..file_count {
            std::fs::write(
                repo.join(format!("module_{i}.py")),
                format!("def function_{i}():\n    return {i}\n"),
            )
            .expect("source file");
        }
        let previous_config = std::env::var_os("VARDE_CONFIG_DIR");
        unsafe { std::env::set_var("VARDE_CONFIG_DIR", &config) };
        Self {
            _temp: temp,
            repo,
            previous_config,
        }
    }

    fn db_path(&self) -> PathBuf {
        repo_db_path(&self.repo)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        match self.previous_config.clone() {
            Some(value) => unsafe { std::env::set_var("VARDE_CONFIG_DIR", value) },
            None => unsafe { std::env::remove_var("VARDE_CONFIG_DIR") },
        }
    }
}

fn budget(key: &str) -> u64 {
    BUDGETS
        .parse::<toml::Table>()
        .expect("valid write budget")
        .get(key)
        .and_then(toml::Value::as_integer)
        .unwrap_or_else(|| panic!("missing integer budget {key}")) as u64
}

fn finish_window(meter: WriteMeter, db_path: &Path) -> u64 {
    let conn = Connection::open(db_path).expect("index connection opens");
    conn.execute_batch("PRAGMA wal_checkpoint(TRUNCATE);")
        .expect("WAL checkpoint completes");
    drop(conn);
    meter.bytes()
}

fn cold_build_bytes(file_count: usize) -> u64 {
    let fixture = Fixture::new(file_count);
    let repo = fixture.repo.to_string_lossy().into_owned();
    let db_path = fixture.db_path();
    let meter = WriteMeter::start();
    varde_code::build_index_at(&repo, &db_path).expect("cold index build");
    let conn = Connection::open(&db_path).expect("index connection opens");
    let indexed_files: i64 = conn
        .query_row("SELECT COUNT(*) FROM files", [], |row| row.get(0))
        .expect("file count is available");
    assert_eq!(
        indexed_files, file_count as i64,
        "fixture files are indexed"
    );
    drop(conn);
    finish_window(meter, &db_path)
}

fn reconcile(repo: &str) {
    ensure_fresh(
        &[
            Slice::Raw,
            Slice::Churn,
            Slice::Imports,
            Slice::Edges,
            Slice::Global,
        ],
        repo,
        &Scope::Repo,
    )
    .expect("source reconcile");
}

fn one_file_bytes(file_count: usize, fixture: &Fixture) -> u64 {
    let repo = fixture.repo.to_string_lossy().into_owned();
    let db_path = fixture.db_path();

    // Prime the first incremental refresh after a cold build. It can normalize
    // cold-build state, so it is deliberately outside the measured window.
    std::fs::write(
        fixture.repo.join("module_0.py"),
        "def changed():\n    return 98\n",
    )
    .expect("prime source edit");
    reconcile(&repo);

    std::fs::write(
        fixture.repo.join("module_0.py"),
        "def changed():\n    return 99\n",
    )
    .expect("measured source edit");
    let meter = WriteMeter::start();
    reconcile(&repo);
    let measured = finish_window(meter, &db_path);
    eprintln!("one-file fixture size {file_count}: {measured} bytes");
    measured
}

#[test]
fn code_index_write_budgets() {
    assert!(available(), "write meter is unavailable on this platform");
    let cold_40 = cold_build_bytes(40);
    let cold_40_repeat = cold_build_bytes(40);
    let fixture_1200 = Fixture::new(1200);
    let repo_1200 = fixture_1200.repo.to_string_lossy().into_owned();
    let db_path_1200 = fixture_1200.db_path();
    let cold_1200_meter = WriteMeter::start();
    varde_code::build_index_at(&repo_1200, &db_path_1200).expect("cold 1200-file index build");
    let cold_1200 = finish_window(cold_1200_meter, &db_path_1200);
    assert_eq!(cold_40, cold_40_repeat, "cold build measurement repeats");

    let fixture = Fixture::new(40);
    let repo = fixture.repo.to_string_lossy().into_owned();
    let db_path = fixture.db_path();

    let cold_meter = WriteMeter::start();
    varde_code::build_index_at(&repo, &db_path).expect("cold index build");
    let cold = finish_window(cold_meter, &db_path);

    let clean_meter = WriteMeter::start();
    reconcile(&repo);
    let clean = finish_window(clean_meter, &db_path);

    let changed = one_file_bytes(40, &fixture);
    let changed_1200 = one_file_bytes(1200, &fixture_1200);

    let idle_meter = WriteMeter::start();
    for _ in 0..10 {
        ensure_fresh(
            &[
                Slice::Raw,
                Slice::Churn,
                Slice::Imports,
                Slice::Edges,
                Slice::Global,
            ],
            &repo,
            &Scope::Repo,
        )
        .expect("idle reconcile");
    }
    let idle = finish_window(idle_meter, &db_path);

    eprintln!(
        "code write budget measurements: cold_40={cold_40}, cold_1200={cold_1200}, cold={cold}, clean={clean}, one_file_40={changed}, one_file_1200={changed_1200}, ten_idle={idle} ({} each)",
        idle / 10
    );
    let cold_fixed_budget = budget("map_cold_fixed_bytes");
    let cold_per_file_budget = budget("map_cold_bytes_per_file");
    let cold_limit_40 = scaled(cold_fixed_budget + 40 * cold_per_file_budget);
    assert!(
        cold_40 <= cold_limit_40,
        "cold build of 40 files wrote {cold_40} bytes, limit {cold_limit_40}"
    );
    let cold_limit_1200 = scaled(cold_fixed_budget + 1200 * cold_per_file_budget);
    assert!(
        cold_1200 <= cold_limit_1200,
        "cold build of 1200 files wrote {cold_1200} bytes, limit {cold_limit_1200}"
    );
    assert!(
        cold <= cold_limit_40,
        "cold build wrote {cold} bytes, limit {cold_limit_40}"
    );
    let clean_limit = scaled(budget("map_clean_rebuild_bytes"));
    assert!(
        clean <= clean_limit,
        "clean rebuild wrote {clean} bytes, limit {clean_limit}"
    );
    let changed_per_file = budget("map_one_file_per_file_bytes");
    let changed_limit_40 = scaled(budget("map_one_file_bytes") + 40 * changed_per_file);
    assert!(
        changed <= changed_limit_40,
        "one-file reconcile at 40 files wrote {changed} bytes, limit {changed_limit_40}"
    );
    let changed_limit_1200 = scaled(budget("map_one_file_bytes") + 1200 * changed_per_file);
    assert!(
        changed_1200 <= changed_limit_1200,
        "one-file reconcile at 1200 files wrote {changed_1200} bytes, limit {changed_limit_1200}"
    );
    let idle_limit = scaled(10 * budget("watch_reconcile_idle_bytes"));
    assert!(
        idle <= idle_limit,
        "ten idle reconciles wrote {idle} bytes, limit {idle_limit}"
    );
}
