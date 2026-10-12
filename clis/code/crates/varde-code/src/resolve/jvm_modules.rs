//! JVM (Java, Kotlin, Scala) import resolution; filled by the owning task.
//!
//! Mirrors `rust_modules::resolve`: `Some(target)` is authoritative
//! (`Some(None)` means "this is a module path with no file in the index");
//! `None` means this resolver does not apply and the generic matcher runs.

use super::ImportIndexes;

pub(super) fn resolve(
    _spec: &str,
    _from_file: &str,
    _idx: &ImportIndexes<'_>,
) -> Option<Option<u32>> {
    None
}
