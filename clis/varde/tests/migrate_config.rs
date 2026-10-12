use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use tempfile::TempDir;
use varde::migrate::{MigrateEnv, Report, config_move};

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

fn run(env: &MigrateEnv, code_store_movable: bool) -> Report {
    let mut report = Report::default();
    config_move::run(env, code_store_movable, &mut report).expect("migration succeeds");
    report
}

fn config_file(env: &MigrateEnv) -> PathBuf {
    env.config_dir.join("config.toml")
}

fn toml_string(value: &Path) -> String {
    toml::Value::String(value.to_string_lossy().into_owned()).to_string()
}

fn snapshot(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    fn visit(base: &Path, path: &Path, result: &mut BTreeMap<PathBuf, Vec<u8>>) {
        let metadata = fs::symlink_metadata(path).unwrap();
        let relative = path.strip_prefix(base).unwrap().to_path_buf();
        if metadata.file_type().is_symlink() {
            result.insert(
                relative,
                fs::read_link(path)
                    .unwrap()
                    .as_os_str()
                    .to_string_lossy()
                    .as_bytes()
                    .to_vec(),
            );
        } else if metadata.is_dir() {
            result.insert(relative, b"<directory>".to_vec());
            for entry in fs::read_dir(path).unwrap() {
                visit(base, &entry.unwrap().path(), result);
            }
        } else {
            result.insert(relative, fs::read(path).unwrap());
        }
    }

    let mut result = BTreeMap::new();
    if root.exists() {
        visit(root, root, &mut result);
    }
    result
}

fn has_path(entries: &[varde::migrate::ReportEntry], path: &Path) -> bool {
    entries.iter().any(|entry| {
        entry.path == path
            || fs::canonicalize(&entry.path)
                .ok()
                .zip(fs::canonicalize(path).ok())
                .is_some_and(|(entry, requested)| entry == requested)
    })
}

#[test]
fn moves_default_stores_rewrites_saved_paths_and_is_idempotent() {
    let (temp, env) = fixture();
    let code_legacy = env.home.join(".config/varde-code");
    let toz_legacy = env.xdg_config_home.as_ref().unwrap().join("varde-toz");
    fs::create_dir_all(code_legacy.join("repos/demo")).unwrap();
    fs::write(code_legacy.join("repos/demo/index.db"), b"index").unwrap();
    let xdg_code = env.xdg_config_home.as_ref().unwrap().join("varde-code");
    fs::create_dir_all(&xdg_code).unwrap();
    fs::write(xdg_code.join("must-stay"), b"code ignores XDG").unwrap();
    fs::create_dir_all(&toz_legacy).unwrap();
    fs::write(toz_legacy.join("captures.jsonl"), b"capture").unwrap();

    let project_root = temp.path().join("project");
    let other_toz = temp.path().join("external-toz");
    fs::write(
        config_file(&env),
        format!(
            "[default]\ntoz = {}\n\n[project.{}]\ntoz = {}\n\n[project.{}]\ntoz = {}\n",
            toml_string(&toz_legacy),
            toml_string(&project_root),
            toml_string(&toz_legacy),
            toml_string(&temp.path().join("other-project")),
            toml_string(&other_toz),
        ),
    )
    .unwrap();

    let report = run(&env, true);
    let code_target = env.config_dir.join("code");
    let toz_target = env.config_dir.join("toz");
    assert!(!code_legacy.exists());
    assert_eq!(
        fs::read(xdg_code.join("must-stay")).unwrap(),
        b"code ignores XDG"
    );
    assert!(!toz_legacy.exists());
    assert_eq!(
        fs::read(code_target.join("repos/demo/index.db")).unwrap(),
        b"index"
    );
    assert_eq!(
        fs::read(toz_target.join("captures.jsonl")).unwrap(),
        b"capture"
    );
    assert!(code_target.join(".varde-migration-complete").is_file());
    assert!(toz_target.join(".varde-migration-complete").is_file());
    assert!(report.moved.iter().any(|entry| entry.path == code_target));
    assert!(report.moved.iter().any(|entry| entry.path == toz_target));
    assert!(report.data()["moved"].is_array());
    assert!(report.data()["skipped"].is_array());
    assert!(report.to_string().contains("moved:"));

    let saved: toml::Value =
        toml::from_str(&fs::read_to_string(config_file(&env)).unwrap()).unwrap();
    assert_eq!(
        saved["default"]["toz"].as_str(),
        Some(toz_target.to_str().unwrap())
    );
    assert_eq!(
        saved["project"][project_root.to_str().unwrap()]["toz"].as_str(),
        Some(toz_target.to_str().unwrap())
    );
    assert_eq!(
        saved["project"][temp.path().join("other-project").to_str().unwrap()]["toz"].as_str(),
        Some(other_toz.to_str().unwrap())
    );

    let after_first_run = snapshot(temp.path());
    let second = run(&env, true);
    assert_eq!(snapshot(temp.path()), after_first_run);
    assert!(second.moved.is_empty());
    assert_eq!(second.data()["moved"].as_array().unwrap().len(), 0);
}

#[test]
fn merges_into_profiles_and_keeps_tool_output_zone_precedence() {
    let (_temp, env) = fixture();
    let base = env.xdg_config_home.as_ref().unwrap();
    let selected = base.join("tool-output-zone");
    let unselected = base.join("varde-toz");
    let target = env.config_dir.join("toz");
    fs::create_dir_all(&selected).unwrap();
    fs::create_dir_all(&unselected).unwrap();
    fs::create_dir_all(&target).unwrap();
    fs::write(selected.join("capture.jsonl"), b"selected").unwrap();
    fs::write(unselected.join("unselected.toml"), b"keep").unwrap();
    fs::write(target.join("profiles.toml"), b"profile = 'target'\n").unwrap();

    let report = run(&env, true);
    assert_eq!(
        fs::read(target.join("profiles.toml")).unwrap(),
        b"profile = 'target'\n"
    );
    assert_eq!(fs::read(target.join("capture.jsonl")).unwrap(), b"selected");
    assert!(unselected.join("unselected.toml").exists());
    assert!(has_path(&report.skipped, &unselected));
    assert!(!selected.exists());
}

#[test]
fn initial_collision_leaves_the_complete_legacy_root_and_marker_untouched() {
    let (_temp, env) = fixture();
    let legacy = env.home.join(".config/varde-code");
    let target = env.config_dir.join("code");
    fs::create_dir_all(&legacy).unwrap();
    fs::create_dir_all(&target).unwrap();
    fs::write(legacy.join("same.txt"), b"legacy").unwrap();
    fs::write(legacy.join("only-legacy.txt"), b"untouched").unwrap();
    fs::write(target.join("same.txt"), b"target").unwrap();
    let legacy_before = snapshot(&legacy);

    let report = run(&env, true);
    assert_eq!(snapshot(&legacy), legacy_before);
    assert_eq!(fs::read(target.join("same.txt")).unwrap(), b"target");
    assert!(!target.join("only-legacy.txt").exists());
    assert!(!target.join(".varde-migration-complete").exists());
    assert!(
        report
            .unrewritable
            .iter()
            .any(|entry| entry.reason.contains("collision"))
    );
}

#[test]
fn target_code_cache_wins_before_the_marker_too() {
    let (_temp, env) = fixture();
    let target = env.config_dir.join("code");
    let legacy = env.home.join(".config/varde-code");
    fs::create_dir_all(target.join("repos/demo")).unwrap();
    fs::create_dir_all(legacy.join("repos/demo")).unwrap();
    fs::write(target.join("repos/demo/index.db"), b"target cache").unwrap();
    fs::write(legacy.join("repos/demo/index.db"), b"legacy cache").unwrap();
    fs::write(legacy.join("repos/demo/metadata.toml"), b"metadata").unwrap();

    let report = run(&env, true);
    assert_eq!(
        fs::read(target.join("repos/demo/index.db")).unwrap(),
        b"target cache"
    );
    assert!(!legacy.join("repos/demo/index.db").exists());
    assert_eq!(
        fs::read(target.join("repos/demo/metadata.toml")).unwrap(),
        b"metadata"
    );
    assert!(target.join(".varde-migration-complete").is_file());
    assert!(
        !report
            .unrewritable
            .iter()
            .any(|entry| entry.path.ends_with("index.db"))
    );
}

#[test]
fn marked_code_store_merges_reappeared_files_and_preserves_conflicts() {
    let (_temp, env) = fixture();
    let target = env.config_dir.join("code");
    let legacy = env.home.join(".config/varde-code");
    fs::create_dir_all(target.join("repos/demo")).unwrap();
    fs::create_dir_all(legacy.join("repos/demo")).unwrap();
    fs::write(target.join(".varde-migration-complete"), b"").unwrap();
    fs::write(target.join("repos/demo/index.db"), b"target cache").unwrap();
    fs::write(legacy.join("repos/demo/index.db"), b"legacy cache").unwrap();
    fs::write(target.join("same.txt"), b"identical").unwrap();
    fs::write(legacy.join("same.txt"), b"identical").unwrap();
    fs::write(target.join("conflict.txt"), b"target conflict").unwrap();
    fs::write(legacy.join("conflict.txt"), b"legacy conflict").unwrap();
    fs::write(legacy.join("new.txt"), b"new").unwrap();

    let report = run(&env, true);
    assert_eq!(
        fs::read(target.join("repos/demo/index.db")).unwrap(),
        b"target cache"
    );
    assert!(!legacy.join("repos/demo/index.db").exists());
    assert!(!legacy.join("same.txt").exists());
    assert_eq!(fs::read(target.join("same.txt")).unwrap(), b"identical");
    assert_eq!(fs::read(target.join("new.txt")).unwrap(), b"new");
    assert_eq!(
        fs::read(target.join("conflict.txt")).unwrap(),
        b"target conflict"
    );
    assert_eq!(
        fs::read(legacy.join("conflict.txt")).unwrap(),
        b"legacy conflict"
    );
    assert!(
        has_path(&report.unrewritable, &legacy.join("conflict.txt")),
        "unrewritable entries: {:#?}",
        report.unrewritable
    );
}

#[test]
fn dry_run_predicts_actions_without_changing_any_fixture_path() {
    let (temp, mut env) = fixture();
    let code_legacy = env.home.join(".config/varde-code");
    let toz_legacy = env.xdg_config_home.as_ref().unwrap().join("varde-toz");
    fs::create_dir_all(&code_legacy).unwrap();
    fs::create_dir_all(&toz_legacy).unwrap();
    fs::write(code_legacy.join("index.db"), b"code").unwrap();
    fs::write(toz_legacy.join("capture"), b"toz").unwrap();
    fs::write(
        config_file(&env),
        format!("[default]\ntoz = {}\n", toml_string(&toz_legacy)),
    )
    .unwrap();
    env.dry_run = true;
    let before = snapshot(temp.path());

    let report = run(&env, true);
    assert_eq!(snapshot(temp.path()), before);
    assert!(
        !env.config_dir
            .join("code/.varde-migration-complete")
            .exists()
    );
    assert!(
        !env.config_dir
            .join("toz/.varde-migration-complete")
            .exists()
    );
    assert!(
        report
            .would
            .iter()
            .any(|entry| entry.reason.starts_with("prediction:"))
    );
    assert!(
        report
            .would
            .iter()
            .any(|entry| entry.reason.contains("marker"))
    );
}

#[test]
fn explicit_toz_override_is_never_moved() {
    let (_temp, mut env) = fixture();
    let override_store = env.xdg_config_home.as_ref().unwrap().join("varde-toz");
    fs::create_dir_all(&override_store).unwrap();
    fs::write(override_store.join("capture"), b"override").unwrap();
    env.toz_config_override = Some(override_store.clone());

    let report = run(&env, true);
    assert!(
        env.config_dir
            .join("code/.varde-migration-complete")
            .is_file()
    );
    assert_eq!(
        fs::read(override_store.join("capture")).unwrap(),
        b"override"
    );
    assert!(
        !env.config_dir
            .join("toz/.varde-migration-complete")
            .exists()
    );
    assert!(has_path(&report.skipped, &override_store));
}

#[test]
fn unsafe_watcher_gate_skips_code_but_continues_toz_migration() {
    let (_temp, env) = fixture();
    let code_legacy = env.home.join(".config/varde-code");
    let toz_legacy = env.xdg_config_home.as_ref().unwrap().join("varde-toz");
    fs::create_dir_all(&code_legacy).unwrap();
    fs::create_dir_all(&toz_legacy).unwrap();
    fs::write(code_legacy.join("index.db"), b"code").unwrap();
    fs::write(toz_legacy.join("capture"), b"toz").unwrap();

    let report = run(&env, false);
    assert!(code_legacy.join("index.db").exists());
    assert!(
        !env.config_dir
            .join("code/.varde-migration-complete")
            .exists()
    );
    assert_eq!(
        fs::read(env.config_dir.join("toz/capture")).unwrap(),
        b"toz"
    );
    assert!(
        env.config_dir
            .join("toz/.varde-migration-complete")
            .is_file()
    );
    assert!(has_path(&report.skipped, &code_legacy));
}

#[cfg(unix)]
#[test]
fn symlinked_legacy_roots_move_the_real_directory_and_remove_only_aliases() {
    use std::os::unix::fs::symlink;

    let (temp, env) = fixture();
    let base = env.xdg_config_home.as_ref().unwrap();
    let real = temp.path().join("real-toz-a");
    let selected = base.join("tool-output-zone");
    fs::create_dir_all(&real).unwrap();
    fs::write(real.join("capture"), b"first").unwrap();
    symlink(&real, &selected).unwrap();
    let report = run(&env, true);
    assert_eq!(
        fs::read(env.config_dir.join("toz/capture")).unwrap(),
        b"first"
    );
    assert!(!selected.exists());
    assert!(
        report
            .moved
            .iter()
            .any(|entry| entry.path == env.config_dir.join("toz"))
    );

    let (_temp2, env2) = fixture();
    let base2 = env2.xdg_config_home.as_ref().unwrap();
    let real2 = base2.join("real-toz");
    let canonical = base2.join("varde-toz");
    let alias = base2.join("tool-output-zone");
    fs::create_dir_all(&real2).unwrap();
    fs::write(real2.join("capture"), b"second").unwrap();
    symlink(&real2, &canonical).unwrap();
    symlink(&real2, &alias).unwrap();
    run(&env2, true);
    assert_eq!(
        fs::read(env2.config_dir.join("toz/capture")).unwrap(),
        b"second"
    );
    assert!(!canonical.symlink_metadata().is_ok());
    assert!(!alias.symlink_metadata().is_ok());
}

#[cfg(unix)]
#[test]
fn cross_device_move_clears_abandoned_partial_data_and_completes_from_source() {
    use std::os::unix::fs::MetadataExt;

    let Some(shm) = Path::new("/dev/shm")
        .is_dir()
        .then(|| Path::new("/dev/shm"))
    else {
        return;
    };
    let Ok(temp) = tempfile::tempdir_in(shm) else {
        return;
    };
    if fs::metadata(temp.path()).unwrap().dev() == fs::metadata(std::env::temp_dir()).unwrap().dev()
    {
        return;
    }

    let home = temp.path().join("home");
    fs::create_dir_all(home.join(".config/varde-code")).unwrap();
    let target_base = tempfile::tempdir().unwrap();
    let config_dir = target_base.path().join("config/varde");
    fs::create_dir_all(&config_dir).unwrap();
    let partial = config_dir.join("code.partial");
    fs::create_dir_all(&partial).unwrap();
    fs::write(partial.join("abandoned"), b"discard me").unwrap();
    fs::write(home.join(".config/varde-code/index.db"), b"complete source").unwrap();
    let env = MigrateEnv {
        home: home.clone(),
        config_dir: config_dir.clone(),
        xdg_config_home: Some(target_base.path().join("xdg")),
        path: std::env::var_os("PATH").unwrap_or_default(),
        cargo_install_root: target_base.path().join("cargo"),
        exe: PathBuf::from(env!("CARGO_BIN_EXE_varde")),
        toz_config_override: None,
        dry_run: false,
    };

    run(&env, true);
    assert_eq!(
        fs::read(config_dir.join("code/index.db")).unwrap(),
        b"complete source"
    );
    assert!(!partial.exists());
    assert!(!home.join(".config/varde-code").exists());

    let reappeared = home.join(".config/varde-code");
    fs::create_dir_all(&reappeared).unwrap();
    fs::write(reappeared.join("new.txt"), b"reappeared source").unwrap();
    fs::create_dir_all(&partial).unwrap();
    fs::write(partial.join("abandoned"), b"discard this retry too").unwrap();
    fs::create_dir_all(config_dir.join("code")).unwrap();
    fs::write(config_dir.join("code/preserved.txt"), b"target").unwrap();

    run(&env, true);
    assert_eq!(
        fs::read(config_dir.join("code/new.txt")).unwrap(),
        b"reappeared source"
    );
    assert_eq!(
        fs::read(config_dir.join("code/index.db")).unwrap(),
        b"complete source"
    );
    assert_eq!(
        fs::read(config_dir.join("code/preserved.txt")).unwrap(),
        b"target"
    );
    assert!(!partial.exists());
    assert!(!reappeared.exists());
}

#[test]
fn saved_toz_rewrite_keeps_user_comments_and_unknown_keys() {
    let (_temp, env) = fixture();
    let toz_legacy = env.xdg_config_home.as_ref().unwrap().join("varde-toz");
    fs::create_dir_all(&toz_legacy).unwrap();
    fs::write(
        config_file(&env),
        format!(
            "# my notes\n[default]\n# toz store\ntoz = {}\nmystery = 7\n\n[hooks.post_tool_use]\n# keep me\n",
            toml_string(&toz_legacy),
        ),
    )
    .unwrap();

    run(&env, true);

    let text = fs::read_to_string(config_file(&env)).unwrap();
    assert!(text.contains("# my notes"), "{text}");
    assert!(text.contains("# toz store"), "{text}");
    assert!(text.contains("mystery = 7"), "{text}");
    assert!(text.contains("[hooks.post_tool_use]\n# keep me"), "{text}");
    let saved: toml::Value = toml::from_str(&text).unwrap();
    assert_eq!(
        saved["default"]["toz"].as_str(),
        Some(env.config_dir.join("toz").to_str().unwrap())
    );
}
