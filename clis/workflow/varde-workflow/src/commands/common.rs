//! Shared bundle resolution for handlers that take the `--bundle` flag
//! (`list`, `lint`, `search`).

use std::path::{Path, PathBuf};
use varde_workflow_core::memory::{self, MemoryPaths};

/// Resolve `bundle` to a bundle root: the explicit `--bundle` path when
/// given, else the project's resolved `<knowledge>` directory — the same
/// resolution `varde-workflow paths` reports (env override → configured
/// project → default → the project tree's `memory-bank/knowledge`).
pub fn resolve_bundle(bundle: Option<&Path>) -> anyhow::Result<PathBuf> {
    if let Some(bundle) = bundle {
        return Ok(bundle.to_path_buf());
    }
    let cwd = std::env::current_dir()?;
    let root = memory::find_root(&cwd).unwrap_or(cwd);
    let root = memory::canonical_or_lexical(&root);
    Ok(MemoryPaths::resolve(&root)?.knowledge.path)
}
