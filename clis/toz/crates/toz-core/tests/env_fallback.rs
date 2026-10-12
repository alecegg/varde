use std::fmt::Debug;

struct EnvRestore(Vec<(String, Option<std::ffi::OsString>)>);

impl EnvRestore {
    fn new(names: &[&str]) -> Self {
        Self(
            names
                .iter()
                .map(|name| (name.to_string(), std::env::var_os(name)))
                .collect(),
        )
    }
}

impl Drop for EnvRestore {
    fn drop(&mut self) {
        for (name, value) in &self.0 {
            if let Some(value) = value {
                std::env::set_var(name, value);
            } else {
                std::env::remove_var(name);
            }
        }
    }
}

fn assert_fallback<T>(
    name: &str,
    value: &str,
    canonical_value: &str,
    canonical_expected: T,
    resolve: impl Fn() -> T,
) where
    T: Debug + PartialEq,
{
    let canonical_name = format!("VARDE_{name}");
    std::env::remove_var(name);
    std::env::remove_var(&canonical_name);

    std::env::set_var(name, value);
    let legacy = resolve();

    std::env::remove_var(name);
    std::env::set_var(&canonical_name, value);
    let canonical = resolve();
    assert_eq!(
        legacy, canonical,
        "{name} and {canonical_name} should resolve equally"
    );

    std::env::set_var(name, "legacy-value");
    std::env::set_var(&canonical_name, canonical_value);
    assert_eq!(
        resolve(),
        canonical_expected,
        "{canonical_name} should take precedence over {name}"
    );

    std::env::remove_var(name);
    std::env::remove_var(&canonical_name);
}

#[test]
fn renamed_toz_environment_variables_keep_their_fallbacks() {
    let names = [
        "TOZ_CONFIG_DIR",
        "TOZ_FALLBACK_DIR",
        "TOZ_THRESHOLD",
        "TOZ_SESSION",
        "TOZ_HOOK_LOG",
        "VARDE_CONFIG_DIR",
        "VARDE_TOZ_CONFIG_DIR",
        "VARDE_TOZ_FALLBACK_DIR",
        "VARDE_TOZ_THRESHOLD",
        "VARDE_TOZ_SESSION",
        "VARDE_TOZ_HOOK_LOG",
    ];
    let _restore = EnvRestore::new(&names);
    let fixture = tempfile::tempdir().unwrap();

    let project = toz_core::project::Project {
        root: fixture.path().join("project"),
        key: "env-fallback-table".to_string(),
    };

    let same_config_dir = fixture.path().join("same-config");
    let canonical_config_dir = fixture.path().join("canonical-config");
    let expected_store_dir = canonical_config_dir.join(&project.key);
    assert_fallback(
        "TOZ_CONFIG_DIR",
        same_config_dir.to_str().unwrap(),
        canonical_config_dir.to_str().unwrap(),
        expected_store_dir,
        || project.store_dir_with_source().unwrap().0,
    );

    let same_fallback_dir = fixture.path().join("same-fallback");
    let canonical_fallback_dir = fixture
        .path()
        .canonicalize()
        .unwrap()
        .join("canonical-fallback");
    let expected_fallback_db = Some(canonical_fallback_dir.join(&project.key).join("toz.db"));
    assert_fallback(
        "TOZ_FALLBACK_DIR",
        same_fallback_dir.to_str().unwrap(),
        canonical_fallback_dir.to_str().unwrap(),
        expected_fallback_db,
        || project.fallback_db_path(),
    );

    let config_path = fixture.path().join("config.toml");
    std::fs::write(&config_path, "threshold = 3\n").unwrap();
    assert_fallback("TOZ_THRESHOLD", "17", "29", 29, || {
        toz_core::config::Config::load_from(&config_path)
            .unwrap()
            .threshold
    });

    assert_fallback(
        "TOZ_SESSION",
        "same-session",
        "canonical-session",
        "canonical-session".to_string(),
        || toz_core::config::env("TOZ_SESSION").unwrap(),
    );
    assert_fallback(
        "TOZ_HOOK_LOG",
        "same-hook-log",
        "canonical-hook-log",
        "canonical-hook-log".to_string(),
        || toz_core::config::env("TOZ_HOOK_LOG").unwrap(),
    );
}
