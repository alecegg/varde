//! okf-core: strictly OKF v0.2-conformant Concept/Knowledge Bundle CRUD
//! with optimistic-concurrency-controlled writes.
//!
//! CRUD assumes trusted ownership of bundle directories and their ancestors.
//! Slug and symlink checks reject ordinary escape attempts. They are not a
//! security boundary against concurrent hostile directory replacement.

pub mod bundle;
pub mod concept;
pub mod crud;
pub mod frontmatter;
pub mod lint;
pub mod maps;
pub mod memory;
pub mod occ;
pub mod registry;
pub mod vault;
mod walk;

#[cfg(test)]
mod test_support;
