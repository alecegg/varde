//! okf-core: strictly OKF v0.2-conformant Concept/Knowledge Bundle CRUD
//! with optimistic-concurrency-controlled writes.

pub mod bundle;
pub mod concept;
pub mod crud;
pub mod frontmatter;
pub mod lint;
pub mod occ;
pub mod registry;
pub mod vault;
mod walk;

#[cfg(test)]
mod test_support;
