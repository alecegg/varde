//! Config directory resolution.

use std::path::PathBuf;

/// Root directory for varde-wide config: `$VARDE_CONFIG_DIR`, else
/// `$XDG_CONFIG_HOME/varde`, else `~/.config/varde`. With no home directory
/// at all, a relative `.config/varde`. Empty variables count as unset.
pub fn varde_config_dir() -> PathBuf {
    if let Some(dir) = std::env::var_os("VARDE_CONFIG_DIR").filter(|v| !v.is_empty()) {
        return PathBuf::from(dir);
    }
    if let Some(dir) = std::env::var_os("XDG_CONFIG_HOME").filter(|v| !v.is_empty()) {
        return PathBuf::from(dir).join("varde");
    }
    std::env::home_dir()
        .map(|home| home.join(".config"))
        .unwrap_or_else(|| PathBuf::from(".config"))
        .join("varde")
}

/// The platform data directory: `~/Library/Application Support` on macOS, else
/// `$XDG_DATA_HOME` when absolute, else `~/.local/share`.
pub fn data_dir() -> Option<PathBuf> {
    data_dir_from(std::env::var_os("XDG_DATA_HOME"), std::env::home_dir())
}

fn data_dir_from(
    xdg_data_home: Option<std::ffi::OsString>,
    home: Option<PathBuf>,
) -> Option<PathBuf> {
    if cfg!(target_os = "macos") {
        return home.map(|home| home.join("Library/Application Support"));
    }
    xdg_data_home
        .map(PathBuf::from)
        .filter(|dir| dir.is_absolute())
        .or_else(|| home.map(|home| home.join(".local/share")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn data_dir_follows_the_platform_rules() {
        let home = Some(PathBuf::from("/home/u"));
        let xdg = Some("/xdg/data".into());
        if cfg!(target_os = "macos") {
            let expected = Some(PathBuf::from("/home/u/Library/Application Support"));
            assert_eq!(data_dir_from(xdg, home.clone()), expected);
            assert_eq!(data_dir_from(None, home), expected);
        } else {
            assert_eq!(data_dir_from(xdg, home.clone()), Some("/xdg/data".into()));
            assert_eq!(
                data_dir_from(Some("relative".into()), home.clone()),
                Some("/home/u/.local/share".into())
            );
            assert_eq!(
                data_dir_from(None, home),
                Some("/home/u/.local/share".into())
            );
            assert_eq!(data_dir_from(None, None), None);
        }
    }

    #[test]
    fn home_dir_prefers_a_non_empty_home_variable() {
        // `std::env::home_dir` reads HOME first on Unix, as `dirs::home_dir` did.
        if let Some(home) = std::env::var_os("HOME").filter(|home| !home.is_empty()) {
            assert_eq!(std::env::home_dir(), Some(PathBuf::from(home)));
        }
    }
}
