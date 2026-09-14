//! Bundle bookkeeping predicates shared by the bundle-traversal walkers
//! (`lint`, `registry`) — single-sourced so the traversal contract (which
//! files and directories are ever part of a Knowledge Bundle) cannot drift
//! between them.

/// Build/artifact directories that are never part of a Knowledge Bundle.
pub(crate) fn is_artifact_dir(name: &str) -> bool {
    matches!(name, "target" | "node_modules")
}

/// Bundle bookkeeping files, never Concepts: `index.md`/`log.md` per OKF
/// v0.2 §3.1, plus `README.md` (documentation). `crud::list` keeps the
/// strict OKF §3.1 set (`index.md`/`log.md` only) — a documented,
/// intentional divergence; the walkers that skip `README.md` too use this
/// shared predicate.
pub(crate) fn is_reserved(name: &str) -> bool {
    matches!(name, "index.md" | "log.md" | "README.md")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn artifact_dirs_are_target_and_node_modules() {
        for name in ["target", "node_modules"] {
            assert!(is_artifact_dir(name), "{name}");
        }
        for name in ["src", ".git", "docs", "targets"] {
            assert!(!is_artifact_dir(name), "{name}");
        }
    }

    #[test]
    fn reserved_files_are_index_log_and_readme() {
        for name in ["index.md", "log.md", "README.md"] {
            assert!(is_reserved(name), "{name}");
        }
        for name in ["doc.md", "INDEX.md", "index.txt", "readme.md"] {
            assert!(!is_reserved(name), "{name}");
        }
    }
}
