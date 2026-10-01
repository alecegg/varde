//! Project detection and the per-project store path.
//!
//! A project is the git root of the working directory, or the directory itself when not in a
//! repo. The store lives at `<config_dir>/<project_key>/toz.db` where the key is the canonical
//! project path with a readable prefix and a stable hash suffix.

use anyhow::{Context, Result};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct Project {
    pub root: PathBuf,
    pub key: String,
}

impl Project {
    /// Resolve from an explicit path or the current directory.
    pub fn resolve(explicit: Option<&Path>) -> Result<Self> {
        let start = match explicit {
            Some(p) => p.to_path_buf(),
            None => std::env::current_dir().context("reading current directory")?,
        };
        let start = start.canonicalize().unwrap_or(start);
        let root = git_root(&start).unwrap_or(start);
        let key = key_for(&root);
        Ok(Self { root, key })
    }

    pub fn store_dir(&self) -> Result<PathBuf> {
        Ok(self.store_dir_with_source()?.0)
    }

    /// Same as [`Self::store_dir`], but also reports which source chose it (`toz doctor` shows
    /// this).
    pub fn store_dir_with_source(&self) -> Result<(PathBuf, StoreDirSource)> {
        if crate::config::env_os("TOZ_CONFIG_DIR").is_none() {
            if let Some(dir) = varde_toz_dir(&self.root) {
                let path = self.store_db_in(&dir)?;
                return Ok((
                    path.parent().unwrap().to_path_buf(),
                    StoreDirSource::VardeConfig,
                ));
            }
        }
        let source = if std::env::var_os("VARDE_TOZ_CONFIG_DIR").is_some() {
            StoreDirSource::VardeTozConfigEnv
        } else if crate::config::env_os("TOZ_CONFIG_DIR").is_some() {
            StoreDirSource::TozConfigEnv
        } else {
            StoreDirSource::Default
        };
        let path = self.store_db_in(&crate::config::config_dir()?)?;
        Ok((path.parent().unwrap().to_path_buf(), source))
    }

    /// An explicitly configured fallback is tried only after primary-store access fails.
    pub fn fallback_db_path(&self) -> Option<PathBuf> {
        self.fallback_root()
            .and_then(|root| self.store_db_in(&root).ok())
    }

    fn fallback_root(&self) -> Option<PathBuf> {
        let root = PathBuf::from(crate::config::env_os("TOZ_FALLBACK_DIR")?);
        if !root.is_absolute()
            || root
                .components()
                .any(|c| matches!(c, std::path::Component::ParentDir))
        {
            return None;
        }
        // Resolve existing ancestors so symlinks cannot put the store in the repo.
        let ancestor = root.ancestors().find(|p| p.exists())?;
        let resolved = ancestor
            .canonicalize()
            .ok()?
            .join(root.strip_prefix(ancestor).ok()?);
        if resolved.starts_with(&self.root) || git_root(&resolved).is_some() {
            return None;
        }
        Some(resolved)
    }

    pub fn db_path(&self) -> Result<PathBuf> {
        Ok(self.store_dir()?.join("toz.db"))
    }

    fn store_db_in(&self, base: &Path) -> Result<PathBuf> {
        let current = base.join(&self.key).join("toz.db");
        if current.is_file() {
            return Ok(current);
        }

        let legacy_dir = base.join(legacy_key_for(&self.root));
        let legacy = legacy_dir.join("toz.db");
        if !legacy.is_file() {
            return Ok(current);
        }

        let current_dir = current.parent().expect("database path has a parent");
        std::fs::create_dir_all(base).with_context(|| format!("creating {}", base.display()))?;
        match std::fs::rename(&legacy_dir, current_dir) {
            Ok(()) => Ok(current),
            Err(_) if current.is_file() => Ok(current),
            Err(_error) if !legacy.exists() => Ok(current),
            Err(error) => Err(error).with_context(|| {
                format!(
                    "migrating legacy store {} to {}",
                    legacy_dir.display(),
                    current_dir.display()
                )
            }),
        }
    }
}

/// Which source chose the store directory, most to least specific. Exposed for `toz doctor`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StoreDirSource {
    /// `VARDE_TOZ_CONFIG_DIR` env var.
    VardeTozConfigEnv,
    /// `TOZ_CONFIG_DIR` env var.
    TozConfigEnv,
    /// The `toz` key in the varde user config (project-table or default).
    VardeConfig,
    /// `config_dir()`'s own default resolution (XDG, else `~/.config/tool-output-zone`).
    Default,
}

impl std::fmt::Display for StoreDirSource {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            Self::VardeTozConfigEnv => "VARDE_TOZ_CONFIG_DIR",
            Self::TozConfigEnv => "TOZ_CONFIG_DIR",
            Self::VardeConfig => "varde config",
            Self::Default => "default",
        })
    }
}

/// The `toz` key from the varde `config.toml` (or legacy `paths.toml`):
/// `[project."<canonical project root>"].toz`, else `[default].toz`. A missing or unparsable
/// file, or a file without the key, means "unset" — never an error. Parses only these two keys;
/// every other key in the file is ignored.
fn varde_toz_dir(project_root: &Path) -> Option<PathBuf> {
    let config_dir = crate::profile::varde_config_dir();
    let current = config_dir.join("config.toml");
    let path = if current.exists() {
        current
    } else {
        config_dir.join("paths.toml")
    };
    let text = std::fs::read_to_string(&path).ok()?;
    let root: toml::Value = toml::from_str(&text).ok()?;
    let table = root.as_table()?;

    let canonical_root = project_root
        .canonicalize()
        .unwrap_or_else(|_| project_root.to_path_buf());
    if let Some(projects) = table.get("project").and_then(|v| v.as_table()) {
        for (key, entry) in projects {
            let key_root = PathBuf::from(key);
            let key_root = key_root.canonicalize().unwrap_or(key_root);
            if key_root == canonical_root {
                if let Some(toz) = entry.get("toz").and_then(|v| v.as_str()) {
                    return expand_toz_dir(project_root, toz);
                }
            }
        }
    }
    let raw = table
        .get("default")
        .and_then(|v| v.get("toz"))
        .and_then(|v| v.as_str())?;
    expand_toz_dir(project_root, raw)
}

/// Expand `{project}` (the project root's directory name) and a leading `~` / `~/...` (the home
/// dir) in a configured `toz` path, mirroring md-core's `expand`
/// (`workflow-cli/md-core/src/memory.rs`). A path that is still relative after expansion is
/// treated as unset — never resolved against the current directory.
fn expand_toz_dir(project_root: &Path, value: &str) -> Option<PathBuf> {
    let project_name = project_root
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    let value = value.replace("{project}", &project_name);
    let expanded = if value == "~" || value.starts_with("~/") {
        let home = dirs::home_dir()?;
        home.join(value.trim_start_matches('~').trim_start_matches('/'))
    } else {
        PathBuf::from(value)
    };
    if expanded.is_absolute() {
        Some(expanded)
    } else {
        None
    }
}

fn git_root(start: &Path) -> Option<PathBuf> {
    let mut cur = Some(start);
    while let Some(dir) = cur {
        if dir.join(".git").exists() {
            return Some(dir.to_path_buf());
        }
        cur = dir.parent();
    }
    None
}

pub fn key_for(root: &Path) -> String {
    let readable = legacy_key_for(root);
    let readable = readable.trim_matches('-');
    let readable = if readable.is_empty() {
        "project"
    } else {
        readable
    };
    let readable = readable
        .char_indices()
        .take_while(|(index, _)| *index < 96)
        .map(|(_, ch)| ch)
        .collect::<String>();
    let hash = blake3::hash(&path_bytes(root));
    format!("{readable}-{}", &hash.to_hex()[..32])
}

fn legacy_key_for(root: &Path) -> String {
    let s = root.to_string_lossy();
    let mut out = String::with_capacity(s.len());
    for ch in s.chars() {
        match ch {
            '/' | '\\' | ':' => out.push('-'),
            c if c.is_alphanumeric() || c == '-' || c == '_' || c == '.' => out.push(c),
            _ => out.push('_'),
        }
    }
    out
}

#[cfg(unix)]
fn path_bytes(path: &Path) -> Vec<u8> {
    use std::os::unix::ffi::OsStrExt;
    path.as_os_str().as_bytes().to_vec()
}

#[cfg(windows)]
fn path_bytes(path: &Path) -> Vec<u8> {
    use std::os::windows::ffi::OsStrExt;
    path.as_os_str()
        .encode_wide()
        .flat_map(u16::to_le_bytes)
        .collect()
}

#[cfg(not(any(unix, windows)))]
fn path_bytes(path: &Path) -> Vec<u8> {
    path.to_string_lossy().as_bytes().to_vec()
}

/// Enumerate shared stores and every project in the varde config dir (if set) and the supplied
/// fallback root.
pub fn all_store_dbs(project: &Project) -> Result<Vec<(String, PathBuf)>> {
    let mut bases = vec![crate::config::config_dir()?];
    if let Some(dir) = varde_toz_dir(&project.root) {
        bases.push(dir);
    }
    if let Some(root) = project.fallback_root() {
        bases.push(root);
    }
    let mut out = Vec::new();
    for base in bases {
        let Ok(rd) = std::fs::read_dir(&base) else {
            continue;
        };
        for entry in rd.flatten() {
            let db = entry.path().join("toz.db");
            if db.is_file() {
                out.push((entry.file_name().to_string_lossy().into_owned(), db));
            }
        }
    }
    out.sort();
    out.dedup();
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    // Guards tests that mutate process-wide env vars this module reads (`VARDE_CONFIG_DIR`,
    // `TOZ_CONFIG_DIR`, `TOZ_FALLBACK_DIR`), since `cargo test` runs tests in parallel by default.
    static ENV_GUARD: Mutex<()> = Mutex::new(());

    fn clear_env() {
        std::env::remove_var("VARDE_CONFIG_DIR");
        std::env::remove_var("VARDE_TOZ_CONFIG_DIR");
        std::env::remove_var("TOZ_CONFIG_DIR");
        std::env::remove_var("VARDE_TOZ_FALLBACK_DIR");
        std::env::remove_var("TOZ_FALLBACK_DIR");
    }

    #[test]
    fn expand_toz_dir_expands_leading_tilde_to_home() {
        let _lock = ENV_GUARD.lock().unwrap();
        let home_dir = tempfile::tempdir().unwrap();
        let original_home = std::env::var_os("HOME");
        std::env::set_var("HOME", home_dir.path());

        assert_eq!(
            expand_toz_dir(Path::new("/any/project"), "~/x"),
            Some(home_dir.path().join("x"))
        );

        match original_home {
            Some(value) => std::env::set_var("HOME", value),
            None => std::env::remove_var("HOME"),
        }
    }

    #[test]
    fn expand_toz_dir_substitutes_project_placeholder() {
        let _lock = ENV_GUARD.lock().unwrap();
        assert_eq!(
            expand_toz_dir(Path::new("/r/myproj"), "/a/{project}/b"),
            Some(PathBuf::from("/a/myproj/b"))
        );
    }

    #[test]
    fn expand_toz_dir_treats_relative_result_as_unset() {
        let _lock = ENV_GUARD.lock().unwrap();
        assert_eq!(expand_toz_dir(Path::new("/r/myproj"), "rel/dir"), None);
    }

    #[test]
    fn varde_toz_dir_is_unset_without_a_config_file() {
        let _lock = ENV_GUARD.lock().unwrap();
        clear_env();
        let varde_dir = tempfile::tempdir().unwrap();
        std::env::set_var("VARDE_CONFIG_DIR", varde_dir.path());

        assert_eq!(varde_toz_dir(Path::new("/tmp/some-project")), None);
        clear_env();
    }

    #[test]
    fn varde_toz_dir_project_table_wins_over_default() {
        let _lock = ENV_GUARD.lock().unwrap();
        clear_env();
        let varde_dir = tempfile::tempdir().unwrap();
        let project_dir = tempfile::tempdir().unwrap();
        let project_root = project_dir.path().canonicalize().unwrap();
        std::fs::write(
            varde_dir.path().join("paths.toml"),
            format!(
                "[default]\ntoz = \"/tmp/default-store\"\n\n[project.\"{}\"]\ntoz = \"/tmp/project-store\"\n",
                project_root.display()
            ),
        )
        .unwrap();
        std::env::set_var("VARDE_CONFIG_DIR", varde_dir.path());

        assert_eq!(
            varde_toz_dir(&project_root),
            Some(PathBuf::from("/tmp/project-store"))
        );
        assert_eq!(
            varde_toz_dir(Path::new("/tmp/unrelated-project")),
            Some(PathBuf::from("/tmp/default-store"))
        );
        clear_env();
    }

    #[test]
    fn varde_toz_dir_prefers_new_config_and_falls_back_to_legacy() {
        let _lock = ENV_GUARD.lock().unwrap();
        clear_env();
        let varde_dir = tempfile::tempdir().unwrap();
        let project_root = Path::new("/tmp/config-precedence-project");
        std::fs::write(
            varde_dir.path().join("paths.toml"),
            "[default]\ntoz = '/tmp/legacy-store'\n",
        )
        .unwrap();
        std::env::set_var("VARDE_CONFIG_DIR", varde_dir.path());
        assert_eq!(
            varde_toz_dir(project_root),
            Some(PathBuf::from("/tmp/legacy-store"))
        );

        std::fs::write(
            varde_dir.path().join("config.toml"),
            "[default]\ntoz = '/tmp/new-store'\n[settings]\nusage_limit = '80%'\n",
        )
        .unwrap();
        assert_eq!(
            varde_toz_dir(project_root),
            Some(PathBuf::from("/tmp/new-store"))
        );
        clear_env();
    }

    #[test]
    fn store_dir_prefers_varde_config_over_an_existing_fallback_store() {
        let _lock = ENV_GUARD.lock().unwrap();
        clear_env();
        let varde_dir = tempfile::tempdir().unwrap();
        let store_dir = tempfile::tempdir().unwrap();
        let fallback_dir = tempfile::tempdir().unwrap();
        let root = PathBuf::from("/tmp/varde-store-project");
        std::fs::write(
            varde_dir.path().join("paths.toml"),
            format!("[default]\ntoz = \"{}\"\n", store_dir.path().display()),
        )
        .unwrap();
        // An existing fallback store, which today's behavior would otherwise prefer.
        let fallback_db = fallback_dir.path().join(key_for(&root)).join("toz.db");
        std::fs::create_dir_all(fallback_db.parent().unwrap()).unwrap();
        std::fs::write(&fallback_db, b"fallback").unwrap();

        std::env::set_var("VARDE_CONFIG_DIR", varde_dir.path());
        std::env::set_var("TOZ_FALLBACK_DIR", fallback_dir.path());
        let project = Project {
            key: key_for(&root),
            root: root.clone(),
        };

        let (dir, source) = project.store_dir_with_source().unwrap();
        assert_eq!(dir, store_dir.path().join(&project.key));
        assert_eq!(source, StoreDirSource::VardeConfig);
        clear_env();
    }

    #[test]
    fn store_dir_prefers_default_primary_over_existing_fallback() {
        let _lock = ENV_GUARD.lock().unwrap();
        clear_env();
        let xdg = tempfile::tempdir().unwrap();
        let varde_config = tempfile::tempdir().unwrap();
        let fallback = tempfile::tempdir().unwrap();
        let root = PathBuf::from("/tmp/default-primary-project");
        let project = Project {
            key: key_for(&root),
            root,
        };
        let fallback_db = fallback.path().join(&project.key).join("toz.db");
        std::fs::create_dir_all(fallback_db.parent().unwrap()).unwrap();
        std::fs::write(&fallback_db, b"old fallback").unwrap();

        let prior_xdg = std::env::var_os("XDG_CONFIG_HOME");
        std::env::set_var("XDG_CONFIG_HOME", xdg.path());
        std::env::set_var("VARDE_CONFIG_DIR", varde_config.path());
        std::env::set_var("VARDE_TOZ_FALLBACK_DIR", fallback.path());
        let (dir, source) = project.store_dir_with_source().unwrap();
        assert_eq!(dir, xdg.path().join("varde-toz").join(&project.key));
        assert_eq!(source, StoreDirSource::Default);
        match prior_xdg {
            Some(value) => std::env::set_var("XDG_CONFIG_HOME", value),
            None => std::env::remove_var("XDG_CONFIG_HOME"),
        }
        clear_env();
    }

    #[test]
    fn explicit_primary_still_allows_a_configured_fallback_on_access_failure() {
        let _lock = ENV_GUARD.lock().unwrap();
        clear_env();
        let primary = tempfile::tempdir().unwrap();
        let fallback = tempfile::tempdir().unwrap();
        let root = PathBuf::from("/tmp/explicit-primary-project");
        let project = Project {
            key: key_for(&root),
            root,
        };

        std::env::set_var("VARDE_TOZ_CONFIG_DIR", primary.path());
        std::env::set_var("VARDE_TOZ_FALLBACK_DIR", fallback.path());
        assert_eq!(
            project.fallback_db_path().unwrap(),
            fallback
                .path()
                .canonicalize()
                .unwrap()
                .join(&project.key)
                .join("toz.db")
        );
        let (dir, source) = project.store_dir_with_source().unwrap();
        assert_eq!(dir, primary.path().join(&project.key));
        assert_eq!(source, StoreDirSource::VardeTozConfigEnv);
        clear_env();
    }

    #[test]
    fn toz_config_dir_env_still_wins_over_varde_config() {
        let _lock = ENV_GUARD.lock().unwrap();
        clear_env();
        let varde_dir = tempfile::tempdir().unwrap();
        let store_dir = tempfile::tempdir().unwrap();
        let toz_config_dir = tempfile::tempdir().unwrap();
        let root = PathBuf::from("/tmp/toz-config-env-project");
        std::fs::write(
            varde_dir.path().join("paths.toml"),
            format!("[default]\ntoz = \"{}\"\n", store_dir.path().display()),
        )
        .unwrap();

        std::env::set_var("VARDE_CONFIG_DIR", varde_dir.path());
        std::env::set_var("TOZ_CONFIG_DIR", toz_config_dir.path());
        let project = Project {
            key: key_for(&root),
            root: root.clone(),
        };

        let (dir, source) = project.store_dir_with_source().unwrap();
        assert_eq!(dir, toz_config_dir.path().join(&project.key));
        assert_eq!(source, StoreDirSource::TozConfigEnv);
        clear_env();
    }

    #[test]
    fn key_keeps_a_readable_prefix_and_stable_hash() {
        let key = key_for(Path::new("/Users/alec/source/foo"));
        assert!(key.starts_with("Users-alec-source-foo-"));
        assert_eq!(key.len(), "Users-alec-source-foo-".len() + 32);
        assert_eq!(key, key_for(Path::new("/Users/alec/source/foo")));
    }

    #[test]
    fn known_legacy_collisions_have_distinct_keys() {
        let pairs = [
            ("/tmp/a-b", "/tmp/a/b"),
            ("/tmp/a b", "/tmp/a_b"),
            ("C:/work/a", "C:\\work\\a"),
        ];
        for (left, right) in pairs {
            assert_eq!(
                legacy_key_for(Path::new(left)),
                legacy_key_for(Path::new(right))
            );
            assert_ne!(key_for(Path::new(left)), key_for(Path::new(right)));
        }
    }

    #[test]
    fn legacy_store_moves_without_merging() {
        let base = tempfile::tempdir().unwrap();
        let root = PathBuf::from("/tmp/legacy-project");
        let project = Project {
            key: key_for(&root),
            root: root.clone(),
        };
        let legacy_dir = base.path().join(legacy_key_for(&root));
        std::fs::create_dir_all(&legacy_dir).unwrap();
        std::fs::write(legacy_dir.join("toz.db"), b"legacy").unwrap();

        let migrated = project.store_db_in(base.path()).unwrap();

        assert_eq!(std::fs::read(&migrated).unwrap(), b"legacy");
        assert!(!legacy_dir.exists());
    }

    #[test]
    fn existing_hashed_store_wins_over_legacy_store() {
        let base = tempfile::tempdir().unwrap();
        let root = PathBuf::from("/tmp/existing-project");
        let project = Project {
            key: key_for(&root),
            root: root.clone(),
        };
        let current = base.path().join(&project.key).join("toz.db");
        let legacy = base.path().join(legacy_key_for(&root)).join("toz.db");
        std::fs::create_dir_all(current.parent().unwrap()).unwrap();
        std::fs::create_dir_all(legacy.parent().unwrap()).unwrap();
        std::fs::write(&current, b"current").unwrap();
        std::fs::write(&legacy, b"legacy").unwrap();

        assert_eq!(project.store_db_in(base.path()).unwrap(), current);
        assert_eq!(std::fs::read(&current).unwrap(), b"current");
        assert_eq!(std::fs::read(&legacy).unwrap(), b"legacy");
    }
}
