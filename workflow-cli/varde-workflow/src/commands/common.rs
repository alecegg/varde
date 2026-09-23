//! Shared vault/bundle resolution for handlers that take the `--vault`
//! `--bundle` flag pair (`list`, `lint`, `search`).

use crate::cli::{LintArgs, ListArgs, SearchArgs, VaultArg};
use okf_core::vault::VaultSelector;
use std::path::Path;

/// Args structs carrying the `--vault`/`--bundle` flag pair, so
/// [`vault_and_bundle`] can resolve them once per handler instead of every
/// call site repeating `args.vault.map(Into::into)` +
/// `args.bundle.as_deref()`.
pub trait VaultBundleArgs {
    fn vault(&self) -> Option<VaultArg>;
    fn bundle(&self) -> Option<&Path>;
}

macro_rules! impl_vault_bundle_args {
    ($($ty:ty),+ $(,)?) => {
        $(
            impl VaultBundleArgs for $ty {
                fn vault(&self) -> Option<VaultArg> {
                    self.vault
                }
                fn bundle(&self) -> Option<&Path> {
                    self.bundle.as_deref()
                }
            }
        )+
    };
}

impl_vault_bundle_args!(ListArgs, LintArgs, SearchArgs);

/// Resolve `args`' `--vault`/`--bundle` pair into the `(VaultSelector,
/// bundle path)` shape the `okf_core::vault` query functions take.
pub fn vault_and_bundle(args: &impl VaultBundleArgs) -> (Option<VaultSelector>, Option<&Path>) {
    (args.vault().map(Into::into), args.bundle())
}
