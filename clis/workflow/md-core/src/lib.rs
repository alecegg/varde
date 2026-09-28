//! varde-workflow-core: Concept/Knowledge Bundle CRUD with
//! optimistic-concurrency-controlled writes.
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
mod walk;

#[cfg(test)]
mod test_support;
