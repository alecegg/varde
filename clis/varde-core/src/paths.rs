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
    dirs::home_dir()
        .map(|home| home.join(".config"))
        .unwrap_or_else(|| PathBuf::from(".config"))
        .join("varde")
}
