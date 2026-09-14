//! CLI argument parsing (clap derive).

use clap::{Args, Parser, Subcommand};
use okf_core::vault::VaultSelector;
use std::path::PathBuf;

#[derive(Debug, Parser)]
#[command(
    name = "varde-docs",
    version,
    about = "OKF Concept/Knowledge Bundle CRUD with OCC writes"
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    /// Manage Concepts within a Knowledge Bundle
    Concept {
        #[command(subcommand)]
        command: ConceptCommand,
    },
    /// Lint a Knowledge Bundle for structural health issues
    Lint(LintArgs),
}

#[derive(Debug, Subcommand)]
pub enum ConceptCommand {
    /// Create a Concept from a complete frontmatter+body document
    Create(CreateArgs),
    /// Show a Concept's frontmatter, body, and current version
    Show(ShowArgs),
    /// Update a Concept, rejecting stale versions
    Update(UpdateArgs),
    /// List Concepts in the bundle
    List(ListArgs),
    /// Delete a Concept (hard delete)
    Delete(DeleteArgs),
    /// Set a single frontmatter field, rejecting stale versions
    SetField(SetFieldArgs),
    /// Search Concepts: `--field key=value` for exact frontmatter matches,
    /// `--text <QUERY>` for ranked lexical full-text search across bodies
    /// and frontmatter (composable: `--field` narrows first, `--text`
    /// ranks/filters the remainder)
    Search(SearchArgs),
}

#[derive(Debug, Args)]
pub struct CreateArgs {
    /// Knowledge Bundle root directory (holds the Concept `.md` files)
    #[arg(long)]
    pub bundle: PathBuf,
    /// Read the concept document from this file; the slug derives from its
    /// `<slug>.md` filename
    #[arg(long, conflicts_with = "slug")]
    pub file: Option<PathBuf>,
    /// Concept slug, e.g. `my-concept` or `pattern/my-concept`; the document is read from stdin
    pub slug: Option<String>,
    /// Machine-readable JSON output
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ShowArgs {
    /// Knowledge Bundle root directory (holds the Concept `.md` files)
    #[arg(long)]
    pub bundle: PathBuf,
    /// Concept slug, e.g. `my-concept` or `pattern/my-concept`
    pub slug: String,
    /// Print only the parsed frontmatter as structured JSON, omitting the
    /// body entirely (takes precedence over `--json`)
    #[arg(long)]
    pub frontmatter_only: bool,
    /// Machine-readable JSON output
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct UpdateArgs {
    /// Knowledge Bundle root directory (holds the Concept `.md` files)
    #[arg(long)]
    pub bundle: PathBuf,
    /// Concept slug, e.g. `my-concept` or `pattern/my-concept`
    pub slug: String,
    /// OCC version hash last read; a mismatch is rejected as a conflict
    #[arg(long)]
    pub expected_version: String,
    /// Read the new document from this file; the slug stays the same
    #[arg(long)]
    pub file: Option<PathBuf>,
    /// Machine-readable JSON output
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ListArgs {
    /// Knowledge Bundle root directory (holds the Concept `.md` files).
    /// Without `--vault`, the listing merges this Project Vault with the
    /// Personal Vault by default; optional so `--vault` alone works.
    #[arg(long)]
    pub bundle: Option<PathBuf>,
    /// Narrow the listing to one vault: `personal` or `project`. Vault
    /// selection happens first; without it the default merges both vaults.
    /// With `--vault project`, a `--bundle` path is scanned as the project
    /// root (typically a subdirectory of it); with `--vault personal` a
    /// relative `--bundle` path filters within the fixed Personal Vault
    /// root (an absolute path has no additional effect).
    #[arg(long)]
    pub vault: Option<VaultArg>,
    /// Include `status: deprecated` Concepts in the listing
    #[arg(long)]
    pub include_deprecated: bool,
    /// Machine-readable JSON output
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct LintArgs {
    /// Knowledge Bundle root directory (holds the Concept `.md` files).
    /// Without `--vault`, the lint scans this Project Vault merged with
    /// the Personal Vault by default; optional so `--vault` alone works.
    #[arg(long)]
    pub bundle: Option<PathBuf>,
    /// Narrow the lint to one vault: `personal` or `project`. Vault
    /// selection happens first; without it the default lints both vaults.
    /// With `--vault project`, a `--bundle` path is scanned as the project
    /// root (typically a subdirectory of it); with `--vault personal` a
    /// relative `--bundle` path filters within the fixed Personal Vault
    /// root (an absolute path has no additional effect).
    #[arg(long)]
    pub vault: Option<VaultArg>,
    /// Opt into OKF v0.2 spec checks (required `type` field, the §5.4
    /// `status` enum, §5/§10 structured-field shape, and reserved bundle
    /// filenames masking an accidental Concept) in addition to the default
    /// structural checks. Without this flag, only the spec-agnostic
    /// structural checks run.
    #[arg(long)]
    pub okf: bool,
    /// Machine-readable JSON output
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct DeleteArgs {
    /// Knowledge Bundle root directory (holds the Concept `.md` files)
    #[arg(long)]
    pub bundle: PathBuf,
    /// Concept slug, e.g. `my-concept` or `pattern/my-concept`
    pub slug: String,
    /// Machine-readable JSON output
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct SetFieldArgs {
    /// Knowledge Bundle root directory (holds the Concept `.md` files)
    #[arg(long)]
    pub bundle: PathBuf,
    /// Concept slug, e.g. `my-concept` or `pattern/my-concept`
    pub slug: String,
    /// Frontmatter key to set, e.g. `status`, `type`, or any extension key
    pub key: String,
    /// New value; `status` is validated against `draft|stable|deprecated`
    /// and the structured §5/§10 fields reject bare-scalar writes
    pub value: String,
    /// OCC version hash last read; a mismatch is rejected as a conflict
    #[arg(long)]
    pub expected_version: String,
    /// Machine-readable JSON output
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct SearchArgs {
    /// Exact-value frontmatter filter `key=value`, repeatable; results
    /// must match every filter (AND semantics). Values match strings,
    /// the canonical form of other scalars, or any element of a sequence
    /// (e.g. `tags`)
    #[arg(long = "field", value_name = "KEY=VALUE")]
    pub field: Vec<String>,
    /// Ranked lexical full-text search across Concept bodies and
    /// frontmatter values (substring matching, not fuzzy). Composes with
    /// `--field`: when both are given, `--field` narrows to exact matches
    /// first and `--text` ranks/filters the remainder.
    #[arg(long, value_name = "QUERY")]
    pub text: Option<String>,
    /// Maximum number of results `--text` returns, ranked highest-score
    /// first (ties broken alphabetically by slug). Ignored for a
    /// `--field`-only search.
    #[arg(long, default_value_t = okf_core::crud::search::DEFAULT_LIMIT)]
    pub limit: usize,
    /// Knowledge Bundle root directory (holds the Concept `.md` files).
    /// Without `--vault`, the search covers this Project Vault merged with
    /// the Personal Vault by default; optional so `--vault` alone works.
    #[arg(long)]
    pub bundle: Option<PathBuf>,
    /// Narrow the search to one vault: `personal` or `project`. Vault
    /// selection happens first; without it the default merges both vaults.
    /// With `--vault project`, a `--bundle` path is scanned as the project
    /// root (typically a subdirectory of it); with `--vault personal` a
    /// relative `--bundle` path filters within the fixed Personal Vault
    /// root (an absolute path has no additional effect).
    #[arg(long)]
    pub vault: Option<VaultArg>,
    /// Machine-readable JSON output
    #[arg(long)]
    pub json: bool,
}

/// Which vault a `--vault` flag narrows to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, clap::ValueEnum)]
pub enum VaultArg {
    /// The Personal Vault at `~/.varde-docs/`
    Personal,
    /// The Project Vault (the `--bundle` path, or the current directory)
    Project,
}

impl From<VaultArg> for VaultSelector {
    fn from(vault: VaultArg) -> Self {
        match vault {
            VaultArg::Personal => VaultSelector::Personal,
            VaultArg::Project => VaultSelector::Project,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;

    fn parse_cli(args: &[&str]) -> Cli {
        Cli::try_parse_from(args).unwrap()
    }

    fn list_args(cli: Cli) -> ListArgs {
        let Command::Concept {
            command: ConceptCommand::List(args),
        } = cli.command
        else {
            panic!("expected concept list");
        };
        args
    }

    fn lint_args(cli: Cli) -> LintArgs {
        let Command::Lint(args) = cli.command else {
            panic!("expected lint");
        };
        args
    }

    fn set_field_args(cli: Cli) -> SetFieldArgs {
        let Command::Concept {
            command: ConceptCommand::SetField(args),
        } = cli.command
        else {
            panic!("expected concept set-field");
        };
        args
    }

    fn search_args(cli: Cli) -> SearchArgs {
        let Command::Concept {
            command: ConceptCommand::Search(args),
        } = cli.command
        else {
            panic!("expected concept search");
        };
        args
    }

    #[test]
    fn list_bundle_only_keeps_vault_none() {
        let args = list_args(parse_cli(&[
            "varde-docs",
            "concept",
            "list",
            "--bundle",
            "/tmp/bundle",
        ]));
        assert!(args.vault.is_none());
        assert_eq!(args.bundle, Some(PathBuf::from("/tmp/bundle")));
    }

    #[test]
    fn list_vault_personal_without_bundle_parses() {
        let args = list_args(parse_cli(&[
            "varde-docs",
            "concept",
            "list",
            "--vault",
            "personal",
        ]));
        assert_eq!(args.vault, Some(VaultArg::Personal));
        assert!(args.bundle.is_none());
    }

    #[test]
    fn list_neither_flag_parses_both_none() {
        let args = list_args(parse_cli(&["varde-docs", "concept", "list"]));
        assert!(args.vault.is_none());
        assert!(args.bundle.is_none());
    }

    #[test]
    fn lint_vault_project_without_bundle_parses() {
        let args = lint_args(parse_cli(&[
            "varde-docs",
            "lint",
            "--vault",
            "project",
        ]));
        assert_eq!(args.vault, Some(VaultArg::Project));
        assert!(args.bundle.is_none());
    }

    #[test]
    fn lint_neither_flag_parses_both_none() {
        let args = lint_args(parse_cli(&["varde-docs", "lint"]));
        assert!(args.vault.is_none());
        assert!(args.bundle.is_none());
    }

    #[test]
    fn set_field_parses_positionals_and_flags() {
        let args = set_field_args(parse_cli(&[
            "varde-docs",
            "concept",
            "set-field",
            "use-rust",
            "status",
            "deprecated",
            "--bundle",
            "/tmp/bundle",
            "--expected-version",
            "deadbeef",
        ]));
        assert_eq!(args.slug, "use-rust");
        assert_eq!(args.key, "status");
        assert_eq!(args.value, "deprecated");
        assert_eq!(args.bundle, PathBuf::from("/tmp/bundle"));
        assert_eq!(args.expected_version, "deadbeef");
        assert!(!args.json);
    }

    #[test]
    fn set_field_json_flag_parses() {
        let args = set_field_args(parse_cli(&[
            "varde-docs",
            "concept",
            "set-field",
            "use-rust",
            "status",
            "deprecated",
            "--bundle",
            "/tmp/bundle",
            "--expected-version",
            "deadbeef",
            "--json",
        ]));
        assert!(args.json);
    }

    #[test]
    fn search_repeatable_field_flags_parse_as_vector() {
        let args = search_args(parse_cli(&[
            "varde-docs",
            "concept",
            "search",
            "--field",
            "type=decision",
            "--field",
            "status=deprecated",
        ]));
        assert_eq!(args.field, vec!["type=decision", "status=deprecated"]);
        assert!(args.bundle.is_none());
        assert!(args.vault.is_none());
        assert!(!args.json);
    }

    #[test]
    fn search_bundle_vault_json_parse_composable() {
        let args = search_args(parse_cli(&[
            "varde-docs",
            "concept",
            "search",
            "--field",
            "type=decision",
            "--bundle",
            "/tmp/bundle",
            "--vault",
            "project",
            "--json",
        ]));
        assert_eq!(args.field, vec!["type=decision"]);
        assert_eq!(args.bundle, Some(PathBuf::from("/tmp/bundle")));
        assert_eq!(args.vault, Some(VaultArg::Project));
        assert!(args.json);
    }

    #[test]
    fn search_without_flags_parses() {
        let args = search_args(parse_cli(&["varde-docs", "concept", "search"]));
        assert!(args.field.is_empty());
        assert!(args.bundle.is_none());
        assert!(args.vault.is_none());
    }

    #[test]
    fn set_field_without_expected_version_is_rejected() {
        let err = Cli::try_parse_from([
            "varde-docs",
            "concept",
            "set-field",
            "use-rust",
            "status",
            "deprecated",
            "--bundle",
            "/tmp/bundle",
        ])
        .unwrap_err();
        assert!(
            err.to_string().contains("expected-version"),
            "expected-version must be required: {err}"
        );
    }

    #[test]
    fn lint_both_flags_parse_composable() {
        let args = lint_args(parse_cli(&[
            "varde-docs",
            "lint",
            "--vault",
            "personal",
            "--bundle",
            "sub/dir",
        ]));
        assert_eq!(args.vault, Some(VaultArg::Personal));
        assert_eq!(args.bundle, Some(PathBuf::from("sub/dir")));
    }
}
