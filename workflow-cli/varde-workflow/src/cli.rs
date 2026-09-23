//! CLI argument parsing (clap derive).

use clap::{Args, Parser, Subcommand};
use okf_core::vault::VaultSelector;
use std::path::PathBuf;

pub const DEFAULT_OUTPUT_LIMIT: usize = 100;

fn positive_usize(value: &str) -> Result<usize, String> {
    let parsed = value
        .parse::<usize>()
        .map_err(|_| "value must be a positive integer".to_string())?;
    if parsed == 0 {
        return Err("value must be greater than zero".to_string());
    }
    Ok(parsed)
}

#[derive(Debug, Args)]
pub struct OutputPageArgs {
    /// Maximum records returned per collection
    #[arg(
        long,
        default_value_t = DEFAULT_OUTPUT_LIMIT,
        value_parser = positive_usize,
        conflicts_with = "all"
    )]
    pub limit: usize,
    /// Records skipped before returning results
    #[arg(long, default_value_t = 0, conflicts_with = "all")]
    pub offset: usize,
    /// Return every record without pagination
    #[arg(long, conflicts_with = "limit")]
    pub all: bool,
}

#[derive(Debug, Parser)]
#[command(
    name = "varde-workflow",
    version,
    about = "OKF Concept/Knowledge Bundle CRUD with OCC writes"
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    /// Inspect one workflow artifact envelope
    Inspect(InspectArgs),
    /// Validate one workflow artifact without mutation
    Validate(ValidateArgs),
    /// Preview or apply one explicit artifact migration
    Migrate(MigrateArgs),
    /// Recover an interrupted staged workflow write
    Recover(RecoverArgs),
    /// Resolve one artifact dependency graph
    Graph(GraphArgs),
    /// Report blockers and available workflow actions
    Readiness(ReadinessArgs),
    /// Enforce one workflow state transition
    Transition(TransitionArgs),
    /// Commit contracts, promotions, and conclusion state
    Conclude(ConcludeArgs),
    /// Show retryable post-conclusion action state
    ConclusionStatus(ConclusionStatusArgs),
    /// Reset failed post-conclusion actions for retry
    ConclusionRetry(ConclusionRetryArgs),
    /// Record one qualitative post-conclusion action
    ConclusionAction(ConclusionActionArgs),
    /// Manage Concepts within a Knowledge Bundle
    Concept {
        #[command(subcommand)]
        command: ConceptCommand,
    },
    /// Lint a Knowledge Bundle for structural health issues
    Lint(LintArgs),
    /// Show or configure where working and knowledge memory live
    Paths(PathsArgs),
}

#[derive(Debug, Args)]
pub struct PathsArgs {
    #[command(subcommand)]
    pub command: Option<PathsCommand>,
    /// Project root to resolve for (default: nearest `memory-bank/` ancestor of cwd, else cwd)
    #[arg(long)]
    pub project: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Subcommand)]
pub enum PathsCommand {
    /// Record a working and/or knowledge directory in the user config
    Set(PathsSetArgs),
    /// Remove a working and/or knowledge directory from the user config
    Unset(PathsUnsetArgs),
}

#[derive(Debug, Args)]
pub struct PathsSetArgs {
    /// Directory for working memory (plans, handoffs, reviews)
    #[arg(long)]
    pub working: Option<String>,
    /// Directory for knowledge memory (durable notes, specs, contracts)
    #[arg(long)]
    pub knowledge: Option<String>,
    /// Apply to every project (`[default]`) instead of one project root
    #[arg(long, conflicts_with = "project")]
    pub default: bool,
    /// Project root the setting applies to (default: nearest `memory-bank/` ancestor of cwd, else cwd)
    #[arg(long)]
    pub project: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct PathsUnsetArgs {
    /// Forget the working directory setting
    #[arg(long)]
    pub working: bool,
    /// Forget the knowledge directory setting
    #[arg(long)]
    pub knowledge: bool,
    /// Apply to `[default]` instead of one project root
    #[arg(long, conflicts_with = "project")]
    pub default: bool,
    /// Project root the setting applies to (default: nearest `memory-bank/` ancestor of cwd, else cwd)
    #[arg(long)]
    pub project: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct InspectArgs {
    pub artifact: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ValidateArgs {
    pub artifact: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct MigrateArgs {
    pub artifact: PathBuf,
    #[arg(long)]
    pub apply: bool,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct RecoverArgs {
    #[arg(long, default_value = ".")]
    pub root: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct GraphArgs {
    pub plan: PathBuf,
    #[command(flatten)]
    pub page: OutputPageArgs,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ReadinessArgs {
    pub plan: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct TransitionArgs {
    pub artifact: PathBuf,
    pub state: String,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ConcludeArgs {
    pub plan: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ConclusionStatusArgs {
    pub plan: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ConclusionRetryArgs {
    pub plan: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ConclusionActionArgs {
    pub plan: PathBuf,
    pub action: String,
    #[arg(long)]
    pub failed: bool,
    #[arg(long)]
    pub output: Option<String>,
    #[arg(long)]
    pub json: bool,
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
    /// Generate deterministic root and type discovery maps
    Map(MapArgs),
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
    #[command(flatten)]
    pub page: OutputPageArgs,
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
    #[command(flatten)]
    pub page: OutputPageArgs,
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
pub struct MapArgs {
    /// Knowledge Bundle root directory (holds the Concept `.md` files)
    #[arg(long)]
    pub bundle: PathBuf,
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
    /// The Personal Vault at `~/.varde-workflow/`
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
            "varde-workflow",
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
            "varde-workflow",
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
        let args = list_args(parse_cli(&["varde-workflow", "concept", "list"]));
        assert!(args.vault.is_none());
        assert!(args.bundle.is_none());
    }

    #[test]
    fn lint_vault_project_without_bundle_parses() {
        let args = lint_args(parse_cli(&["varde-workflow", "lint", "--vault", "project"]));
        assert_eq!(args.vault, Some(VaultArg::Project));
        assert!(args.bundle.is_none());
    }

    #[test]
    fn lint_neither_flag_parses_both_none() {
        let args = lint_args(parse_cli(&["varde-workflow", "lint"]));
        assert!(args.vault.is_none());
        assert!(args.bundle.is_none());
    }

    #[test]
    fn set_field_parses_positionals_and_flags() {
        let args = set_field_args(parse_cli(&[
            "varde-workflow",
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
            "varde-workflow",
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
            "varde-workflow",
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
            "varde-workflow",
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
        let args = search_args(parse_cli(&["varde-workflow", "concept", "search"]));
        assert!(args.field.is_empty());
        assert!(args.bundle.is_none());
        assert!(args.vault.is_none());
    }

    #[test]
    fn set_field_without_expected_version_is_rejected() {
        let err = Cli::try_parse_from([
            "varde-workflow",
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
            "varde-workflow",
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
