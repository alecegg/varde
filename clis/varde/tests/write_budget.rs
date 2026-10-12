use std::ffi::OsString;
use std::fs;
use std::sync::Mutex;

use varde_contracts::Io;
use varde_core::write_meter::{WriteMeter, available, scaled};

const BUDGETS: &str = include_str!("../../write-budget.toml");
const DOCUMENTATION: &str = include_str!("../../../docs/write-budget.md");
const DAILY_CEILING: u64 = 1_000_000_000;
static ENV_LOCK: Mutex<()> = Mutex::new(());

#[test]
fn write_budgets_are_documented_and_typical_day_fits() {
    assert!(available(), "write meter is unavailable on this platform");

    let budgets: toml::Value = toml::from_str(BUDGETS).unwrap();
    let profile = budgets["typical_day"].as_table().unwrap();
    let keys = [
        "toz_capture_ratio_x",
        "toz_prune_healthy_bytes",
        "toz_prune_tombstone_ratio_x",
        "toz_prune_runaway_second_pass_bytes",
        "watch_reconcile_idle_bytes",
        "map_cold_fixed_bytes",
        "map_cold_bytes_per_file",
        "map_one_file_bytes",
        "map_clean_rebuild_bytes",
        "friction_add_bytes",
        "msg_send_bytes",
    ];
    for key in keys {
        assert!(
            budgets[key].is_integer() || budgets[key].is_float(),
            "missing numeric budget {key}"
        );
        assert!(
            DOCUMENTATION.contains(&format!("`{key}`")),
            "documentation does not mention {key}"
        );
    }
    for key in profile.keys() {
        assert!(
            DOCUMENTATION.contains(&format!("`{key}`")),
            "documentation does not mention typical_day.{key}"
        );
    }

    let value = |name: &str| -> u64 { budgets[name].as_integer().unwrap() as u64 };
    let count = |name: &str| -> u64 { profile[name].as_integer().unwrap() as u64 };
    let daily_bytes =
        count("capture_count") * count("capture_bytes_each") * value("toz_capture_ratio_x")
            + count("healthy_prune_count") * value("toz_prune_healthy_bytes")
            + count("runaway_second_pass_count") * value("toz_prune_runaway_second_pass_bytes")
            + count("idle_reconcile_count") * value("watch_reconcile_idle_bytes")
            + value("map_cold_fixed_bytes")
            + count("cold_map_file_count") * value("map_cold_bytes_per_file")
            + count("one_file_map_count") * value("map_one_file_bytes")
            + count("clean_map_rebuild_count") * value("map_clean_rebuild_bytes")
            + count("friction_add_count") * value("friction_add_bytes")
            + count("msg_send_count") * value("msg_send_bytes");
    assert_eq!(
        profile["ceiling_bytes"].as_integer(),
        Some(DAILY_CEILING as i64)
    );
    assert!(
        daily_bytes < DAILY_CEILING,
        "typical day writes {daily_bytes} bytes"
    );
    let _env_lock = ENV_LOCK.lock().unwrap();

    let root = tempfile::tempdir().unwrap();
    let working = root.path().join("working");
    let config = root.path().join("config");
    fs::create_dir_all(&working).unwrap();
    fs::create_dir_all(&config).unwrap();
    let old_cwd = std::env::current_dir().unwrap();
    let old_working = std::env::var_os("VARDE_WORKING_DIR");
    let old_config = std::env::var_os("VARDE_CONFIG_DIR");
    std::env::set_current_dir(root.path()).unwrap();
    // SAFETY: this is the only test in this target that reads these variables.
    unsafe {
        std::env::set_var("VARDE_WORKING_DIR", &working);
        std::env::set_var("VARDE_CONFIG_DIR", &config);
    }

    let meter = WriteMeter::start();
    let status = varde_workflow::run(
        [
            "varde",
            "msg",
            "send",
            "--from",
            "budget-test",
            "--to",
            "main",
            "--kind",
            "info",
            "budget check",
        ]
        .into_iter()
        .map(OsString::from)
        .collect(),
        &Io::default(),
    );
    let written = meter.bytes();

    std::env::set_current_dir(old_cwd).unwrap();
    restore_env("VARDE_WORKING_DIR", old_working);
    restore_env("VARDE_CONFIG_DIR", old_config);
    assert_eq!(status, std::process::ExitCode::SUCCESS);
    let budgets: toml::Value = toml::from_str(BUDGETS).unwrap();
    assert!(
        written <= scaled(budgets["msg_send_bytes"].as_integer().unwrap() as u64),
        "message send wrote {written} bytes; budget is {}",
        scaled(budgets["msg_send_bytes"].as_integer().unwrap() as u64)
    );
    assert!(working.join(".cache/inbox/messages.jsonl").exists());
}

fn restore_env(key: &str, value: Option<OsString>) {
    match value {
        Some(value) => unsafe { std::env::set_var(key, value) },
        None => unsafe { std::env::remove_var(key) },
    }
}
