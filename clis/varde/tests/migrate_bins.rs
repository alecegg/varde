#![cfg(unix)]

use std::env;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use tempfile::TempDir;
use varde::migrate::{MigrateEnv, Report, ReportEntry, legacy_bins};

const LEGACY_NAMES: [(&str, &str); 5] = [
    ("varde-code", "varde-code 1.2.3"),
    ("varde-workflow", "varde-workflow 1.2.3"),
    ("varde-toz", "varde-toz 1.2.3"),
    ("toz", "varde-toz 1.2.3"),
    ("varde-learn", "varde-learn 1.2.3"),
];

fn fixture() -> (TempDir, MigrateEnv) {
    let temp = tempfile::tempdir().expect("temporary root");
    let home = temp.path().join("home");
    let xdg = temp.path().join("xdg-config");
    let config_dir = xdg.join("varde");
    fs::create_dir_all(&home).unwrap();
    fs::create_dir_all(&config_dir).unwrap();
    let env = MigrateEnv {
        home,
        config_dir,
        xdg_config_home: Some(xdg),
        path: std::env::var_os("PATH").unwrap_or_default(),
        cargo_install_root: temp.path().join("cargo"),
        exe: PathBuf::from(env!("CARGO_BIN_EXE_varde")),
        toz_config_override: None,
        dry_run: false,
    };
    (temp, env)
}

fn executable(path: &Path, version: &str) {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, format!("#!/bin/sh\nprintf '%s\\n' '{version}'\n")).unwrap();
    let mut permissions = fs::metadata(path).unwrap().permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(path, permissions).unwrap();
}

fn run(env: &MigrateEnv, report: &mut Report) {
    legacy_bins::run(env, report).expect("legacy binary migration succeeds");
}

#[test]
fn removes_varde_legacy_binaries_and_keeps_varde() {
    let (_temp, env) = fixture();
    let bin = env.cargo_install_root.join("bin");
    for (name, version) in LEGACY_NAMES {
        executable(&bin.join(name), version);
    }
    executable(&bin.join("varde"), "varde 1.2.3");

    let mut report = Report::default();
    run(&env, &mut report);

    for (name, _) in LEGACY_NAMES {
        assert!(!bin.join(name).exists(), "{name} should be removed");
    }
    assert!(bin.join("varde").exists(), "the varde binary must remain");
    let removed = report
        .moved
        .iter()
        .map(|entry| entry.path.clone())
        .collect::<Vec<_>>();
    assert_eq!(
        removed,
        LEGACY_NAMES
            .iter()
            .map(|(name, _)| bin.join(name))
            .collect::<Vec<_>>()
    );
}

#[test]
fn keeps_and_reports_foreign_toz() {
    let (_temp, env) = fixture();
    let path = env.cargo_install_root.join("bin/toz");
    executable(&path, "toz 9.9.9");

    let mut report = Report::default();
    run(&env, &mut report);

    assert!(path.exists());
    let kept = report
        .skipped
        .iter()
        .find(|entry| entry.path == path)
        .expect("foreign toz is reported");
    assert!(kept.reason.contains("version"));
    assert!(kept.command.as_deref().unwrap().contains("toz --version"));
}

#[test]
fn keeps_a_varde_named_binary_without_a_version_number() {
    let (_temp, env) = fixture();
    let path = env.cargo_install_root.join("bin/varde-code");
    executable(&path, "varde-code unknown");

    let mut report = Report::default();
    run(&env, &mut report);

    assert!(path.exists());
    assert!(
        report
            .skipped
            .iter()
            .any(|entry| { entry.path == path && entry.reason.contains("version line") })
    );
}

#[test]
fn keeps_and_reports_a_non_executable_file() {
    let (_temp, env) = fixture();
    let path = env.cargo_install_root.join("bin/varde-code");
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(&path, "not executable").unwrap();

    let mut report = Report::default();
    run(&env, &mut report);

    assert!(path.exists());
    assert!(
        report
            .skipped
            .iter()
            .any(|entry| { entry.path == path && entry.reason.contains("executable") })
    );
}

#[test]
fn cargo_install_root_overrides_cargo_home() {
    let _guard = crate::process_env_guard();
    let (temp, _env) = fixture();
    let install_root = temp.path().join("install-root");
    let cargo_home = temp.path().join("cargo-home");
    let home = temp.path().join("isolated-home");
    let xdg = temp.path().join("isolated-xdg");
    let config_dir = xdg.join("varde");
    let install_binary = install_root.join("bin/varde-code");
    let cargo_home_binary = cargo_home.join("bin/varde-code");
    executable(&install_binary, "varde-code 1.2.3");
    executable(&cargo_home_binary, "varde-code 1.2.3");
    fs::create_dir_all(&home).unwrap();
    fs::create_dir_all(&config_dir).unwrap();

    let output = Command::new(env::current_exe().unwrap())
        .args([
            "--exact",
            "migrate_bins::cargo_install_root_precedence_child",
            "--nocapture",
        ])
        .env("MIGRATE_BINS_ROOT_PRECEDENCE_CHILD", "1")
        .env("CARGO_INSTALL_ROOT", &install_root)
        .env("CARGO_HOME", &cargo_home)
        .env("HOME", &home)
        .env("XDG_CONFIG_HOME", &xdg)
        .env("VARDE_CONFIG_DIR", &config_dir)
        .output()
        .expect("run isolated precedence check");
    assert!(
        output.status.success(),
        "child test failed: {}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(!install_binary.exists(), "CARGO_INSTALL_ROOT is selected");
    assert!(cargo_home_binary.exists(), "CARGO_HOME is not selected");
}

#[test]
fn cargo_install_root_precedence_child() {
    if env::var_os("MIGRATE_BINS_ROOT_PRECEDENCE_CHILD").is_none() {
        return;
    }
    let env = MigrateEnv::current(false);
    let expected = PathBuf::from(env::var_os("CARGO_INSTALL_ROOT").unwrap());
    assert_eq!(env.cargo_install_root, expected);

    let mut report = Report::default();
    run(&env, &mut report);
}

#[test]
fn keeps_binaries_referenced_by_reported_commands() {
    let (temp, env) = fixture();
    let bin = env.cargo_install_root.join("bin");
    let code = bin.join("varde-code");
    let toz = bin.join("varde-toz");
    executable(&code, "varde-code 1.2.3");
    executable(&toz, "varde-toz 1.2.3");
    let original_code_command = "/opt/old/bin/varde-code hook session-start";
    let original_toz_command = "/opt/old/bin/varde-toz run --fallback-dir /tmp/out";
    let mut report = Report::default();
    report.skipped.push(
        ReportEntry::new(temp.path().join("hooks.json"), "hook was not rewritten")
            .with_command(original_code_command),
    );
    report.unrewritable.push(
        ReportEntry::new(
            temp.path().join("service.unit"),
            "unit could not be rewritten",
        )
        .with_command(original_toz_command),
    );

    run(&env, &mut report);

    assert!(code.exists(), "reported hook still needs varde-code");
    assert!(toz.exists(), "reported unit still needs varde-toz");
    assert!(report.skipped.iter().any(|entry| {
        entry.path == code && entry.command.as_deref() == Some(original_code_command)
    }));
    assert!(report.skipped.iter().any(|entry| {
        entry.path == toz && entry.command.as_deref() == Some(original_toz_command)
    }));
}

#[test]
fn dry_run_reports_would_remove_without_changing_binaries() {
    let (_temp, mut env) = fixture();
    let bin = env.cargo_install_root.join("bin");
    for (name, version) in LEGACY_NAMES {
        executable(&bin.join(name), version);
    }
    executable(&bin.join("varde"), "varde 1.2.3");
    let before = LEGACY_NAMES
        .iter()
        .map(|(name, _)| {
            let path = bin.join(name);
            (path.clone(), fs::read(path).unwrap())
        })
        .collect::<Vec<_>>();
    env.dry_run = true;

    let mut report = Report::default();
    run(&env, &mut report);

    assert!(report.moved.is_empty());
    assert_eq!(report.would.len(), LEGACY_NAMES.len());
    for (path, contents) in before {
        assert!(path.exists());
        assert_eq!(fs::read(path).unwrap(), contents);
    }
    assert!(bin.join("varde").exists());
}
