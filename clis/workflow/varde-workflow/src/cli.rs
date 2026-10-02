//! CLI argument parsing (clap derive).

use clap::{Args, Parser, Subcommand};
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

fn positive_u32(value: &str) -> Result<u32, String> {
    let parsed = value
        .parse::<u32>()
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
    about = "Concept/Knowledge Bundle CRUD with OCC writes"
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    /// Validate one workflow artifact without mutation
    Validate(ValidateArgs),
    /// Recover an interrupted staged workflow write
    Recover(RecoverArgs),
    /// Resolve one artifact dependency graph
    Graph(GraphArgs),
    /// Audit one source commit against its task ownership
    CheckTaskOwnership(CheckTaskOwnershipArgs),
    /// Select the next advisory execution wave without mutation
    ExecutionWave(ExecutionWaveArgs),
    /// Report blockers and available workflow actions
    Readiness(ReadinessArgs),
    /// Enforce one workflow state transition
    Transition(TransitionArgs),
    /// Commit contracts, promotions, and conclusion state
    Conclude(ConcludeArgs),
    /// Copy escalated findings to the standing deferred review
    EscalateDeferred(EscalateDeferredArgs),
    /// Manage independent review subjects and evidence
    Review(ReviewArgs),
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
    /// Show or configure where working, knowledge, and learn memory live
    Paths(PathsArgs),
    /// Inspect specification source inventory and its verified cache
    Spec(SpecArgs),
    /// Harness hook entry points
    Hook(HookArgs),
    /// Install or remove Varde's managed instruction block
    Instructions(InstructionsArgs),
}

#[derive(Debug, Args)]
pub struct InstructionsArgs {
    #[command(subcommand)]
    pub command: InstructionsCommand,
}

#[derive(Debug, Subcommand)]
pub enum InstructionsCommand {
    /// Install or update the managed instruction block
    Install(InstructionsInstallArgs),
    /// Remove the managed instruction block from configured targets
    Remove(InstructionsRemoveArgs),
    /// Print the configured instruction targets
    Targets,
}

#[derive(Debug, Args)]
pub struct InstructionsInstallArgs {
    /// Instruction file to update (may be repeated)
    #[arg(long = "target")]
    pub targets: Vec<PathBuf>,
    /// Maximum number of subagents in flight
    #[arg(long, value_parser = positive_u32)]
    pub max_agents: Option<u32>,
    /// Print the planned file changes without writing
    #[arg(long)]
    pub dry_run: bool,
}

#[derive(Debug, Args)]
pub struct InstructionsRemoveArgs {
    /// Print the planned file changes without writing
    #[arg(long)]
    pub dry_run: bool,
}

#[derive(Debug, Args)]
pub struct CheckTaskOwnershipArgs {
    #[arg(long)]
    pub task: PathBuf,
    #[arg(long)]
    pub commit: String,
    #[arg(long, default_value = ".")]
    pub repo_root: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ExecutionWaveArgs {
    pub plan_dir: PathBuf,
    #[arg(long)]
    pub repo_root: Option<PathBuf>,
    /// Maximum parallel tasks (1..3)
    #[arg(long, default_value_t = 3)]
    pub max_workers: usize,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct EscalateDeferredArgs {
    /// Absolute plan directory under configured working/plans
    #[arg(long)]
    pub plan_dir: PathBuf,
    /// Absolute, disjoint deferred review directory under working memory
    #[arg(long)]
    pub deferred_dir: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct HookArgs {
    #[command(subcommand)]
    pub command: HookCommand,
}

#[derive(Debug, Subcommand)]
pub enum HookCommand {
    /// Print session-start context from the configured providers
    SessionStart(SessionStartArgs),
    /// Add the unified SessionStart hook for a harness
    Install(HookInstallArgs),
    /// Remove the unified SessionStart hook for a harness
    Remove(HookInstallArgs),
}

#[derive(Debug, Args)]
pub struct HookInstallArgs {
    #[arg(long, value_enum)]
    pub harness: Harness,
    /// Print planned changes without writing
    #[arg(long)]
    pub dry_run: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, clap::ValueEnum)]
pub enum Harness {
    Claude,
    Codex,
    Opencode,
    Pi,
}

#[derive(Debug, Args)]
pub struct SessionStartArgs {
    #[arg(long, value_enum)]
    pub harness: Harness,
}

#[derive(Debug, Args)]
pub struct SpecArgs {
    #[command(subcommand)]
    pub command: SpecCommand,
}

#[derive(Debug, Subcommand)]
pub enum SpecCommand {
    /// Classify domain specifications against current repository sources
    Inventory(SpecInventoryArgs),
}

#[derive(Debug, Args)]
pub struct SpecInventoryArgs {
    #[arg(long)]
    pub repository: PathBuf,
    #[arg(long)]
    pub knowledge: PathBuf,
    #[arg(long)]
    pub working: PathBuf,
    /// Force full source and provenance validation
    #[arg(long)]
    pub refresh: bool,
    /// Record inspected paths as non-architecture inputs at their current content hash
    #[arg(long = "acknowledge-architecture-path")]
    pub acknowledge_architecture_paths: Vec<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct PathsArgs {
    #[command(subcommand)]
    pub command: Option<PathsCommand>,
    /// Project root to resolve for (default: git worktree root, then configured project or `memory-bank/` ancestor, else cwd)
    #[arg(long)]
    pub project: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Subcommand)]
pub enum PathsCommand {
    /// Record working, knowledge, toz, and/or global learn directories
    Set(PathsSetArgs),
    /// Remove working, knowledge, toz, and/or global learn directories from the user config
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
    /// Directory for the toz output-capture store
    #[arg(long)]
    pub toz: Option<String>,
    /// Global friction store directory (always writes `[default]`)
    #[arg(long, conflicts_with = "project")]
    pub learn: Option<String>,
    /// Apply to every project (`[default]`) instead of one project root
    #[arg(long, conflicts_with = "project")]
    pub default: bool,
    /// Project root the setting applies to (default: git worktree root, then configured project or `memory-bank/` ancestor, else cwd)
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
    /// Forget the toz output-capture store setting
    #[arg(long)]
    pub toz: bool,
    /// Forget the global friction store setting
    #[arg(long, conflicts_with = "project")]
    pub learn: bool,
    /// Apply to `[default]` instead of one project root
    #[arg(long, conflicts_with = "project")]
    pub default: bool,
    /// Project root the setting applies to (default: git worktree root, then configured project or `memory-bank/` ancestor, else cwd)
    #[arg(long)]
    pub project: Option<PathBuf>,
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
pub struct ReviewArgs {
    #[command(subcommand)]
    pub command: ReviewCommand,
}

#[derive(Debug, Subcommand)]
pub enum ReviewCommand {
    /// Capture an immutable baseline and create a review subject
    Init(ReviewInitArgs),
    /// Authorize a scoped linked worktree using current parent approval
    BindWorktree(ReviewBindWorktreeArgs),
    /// Inspect separate worktree baseline and current evidence
    InspectWorktree(ReviewWorktreeArgs),
    /// Archive verified integrated worktree evidence before cleanup
    ReleaseWorktree(ReviewReleaseWorktreeArgs),
    /// Archive abandoned authorization without deleting source or recovery refs
    AbandonWorktree(ReviewAbandonWorktreeArgs),
    /// Replace a bounded-work contract using an inspected revision
    Contract(ReviewContractArgs),
    /// Extend a subject's coverage without replacing its baseline
    Expand(ReviewExpandArgs),
    /// Show contract, record, baseline, and current change evidence
    Inspect(ReviewInspectArgs),
    /// Record reviewer-authored evidence against an inspected revision
    Record(ReviewRecordArgs),
    /// Check evidence for a supported workflow checkpoint
    Check(ReviewCheckArgs),
}

#[derive(Debug, Args)]
pub struct ReviewInitArgs {
    /// Persisted plan path (use this or --subject with --contract)
    #[arg(long, conflicts_with_all = ["subject", "contract"])]
    pub plan: Option<PathBuf>,
    /// Safe identifier for a bounded change (requires --contract)
    #[arg(long, requires = "contract")]
    pub subject: Option<String>,
    /// JSON contract for bounded work (use with --subject)
    #[arg(long, requires = "subject")]
    pub contract: Option<PathBuf>,
    /// Repository root whose paths and plan identity the subject binds
    #[arg(long)]
    pub repository: PathBuf,
    /// Repository-relative file or directory to include (repeatable)
    #[arg(long = "scope", required_unless_present = "artifact")]
    pub scope: Vec<String>,
    /// Absolute external file to include explicitly (repeatable; no directories or aliases)
    #[arg(long, required_unless_present = "scope")]
    pub artifact: Vec<PathBuf>,
    /// Repository-relative path to exclude from coverage (repeatable)
    #[arg(long = "exclude")]
    pub exclude: Vec<String>,
    /// `scripts/risk-tier.py` output JSON; missing or unreadable defaults to high tier
    #[arg(long = "tier-evidence")]
    pub tier_evidence: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ReviewContractArgs {
    #[arg(long)]
    pub subject: String,
    /// Version returned by `review inspect`
    #[arg(long)]
    pub expected_version: String,
    /// Contract JSON (contract command only)
    #[arg(long)]
    pub file: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ReviewExpandArgs {
    #[arg(long)]
    pub subject: String,
    /// Version returned by `review inspect`
    #[arg(long)]
    pub expected_version: String,
    /// Additional repository-relative paths
    #[arg(long = "scope")]
    pub scope: Vec<String>,
    /// Additional absolute external files
    #[arg(long)]
    pub artifact: Vec<PathBuf>,
    /// Fresh `scripts/risk-tier.py` output JSON; omit to revert a low-tier subject to high
    #[arg(long = "tier-evidence")]
    pub tier_evidence: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ReviewInspectArgs {
    #[arg(long)]
    pub subject: String,
    #[arg(long, value_parser = ["pre-edit", "implementation"])]
    pub phase: String,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ReviewRecordArgs {
    #[arg(long)]
    pub subject: String,
    /// Version returned by `review inspect`
    #[arg(long)]
    pub expected_version: String,
    /// Reviewer-authored JSON evidence record
    #[arg(long)]
    pub file: PathBuf,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ReviewCheckArgs {
    #[arg(long, requires_all = ["worktree", "binding"])]
    pub repository: Option<PathBuf>,
    #[arg(long, requires_all = ["repository", "binding"])]
    pub worktree: Option<PathBuf>,
    #[arg(long, requires_all = ["repository", "worktree"])]
    pub binding: Option<String>,
    #[arg(long)]
    pub subject: String,
    #[arg(long, value_parser = ["start", "resume", "complete"])]
    pub checkpoint: String,
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
    /// Defaults to the project's resolved `<knowledge>` directory (same
    /// resolution as `varde-workflow paths`) when omitted.
    #[arg(long)]
    pub bundle: Option<PathBuf>,
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
    /// Defaults to the project's resolved `<knowledge>` directory (same
    /// resolution as `varde-workflow paths`) when omitted.
    #[arg(long)]
    pub bundle: Option<PathBuf>,
    /// Also report directories with Concept files but no `index.md`
    #[arg(long)]
    pub require_index: bool,
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
    #[arg(long, default_value_t = varde_workflow_core::crud::search::DEFAULT_LIMIT)]
    pub limit: usize,
    /// Knowledge Bundle root directory (holds the Concept `.md` files).
    /// Defaults to the project's resolved `<knowledge>` directory (same
    /// resolution as `varde-workflow paths`) when omitted.
    #[arg(long)]
    pub bundle: Option<PathBuf>,
    /// Machine-readable JSON output
    #[arg(long)]
    pub json: bool,
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
    fn list_bundle_flag_parses() {
        let args = list_args(parse_cli(&[
            "varde-workflow",
            "concept",
            "list",
            "--bundle",
            "/tmp/bundle",
        ]));
        assert_eq!(args.bundle, Some(PathBuf::from("/tmp/bundle")));
    }

    #[test]
    fn list_no_bundle_flag_parses_none() {
        let args = list_args(parse_cli(&["varde-workflow", "concept", "list"]));
        assert!(args.bundle.is_none());
    }

    #[test]
    fn lint_no_bundle_flag_parses_none() {
        let args = lint_args(parse_cli(&["varde-workflow", "lint"]));
        assert!(args.bundle.is_none());
        assert!(!args.require_index);
    }

    #[test]
    fn lint_require_index_flag_parses() {
        let args = lint_args(parse_cli(&["varde-workflow", "lint", "--require-index"]));
        assert!(args.require_index);
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
        assert!(!args.json);
    }

    #[test]
    fn search_bundle_json_parse_composable() {
        let args = search_args(parse_cli(&[
            "varde-workflow",
            "concept",
            "search",
            "--field",
            "type=decision",
            "--bundle",
            "/tmp/bundle",
            "--json",
        ]));
        assert_eq!(args.field, vec!["type=decision"]);
        assert_eq!(args.bundle, Some(PathBuf::from("/tmp/bundle")));
        assert!(args.json);
    }

    #[test]
    fn search_without_flags_parses() {
        let args = search_args(parse_cli(&["varde-workflow", "concept", "search"]));
        assert!(args.field.is_empty());
        assert!(args.bundle.is_none());
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
    fn lint_bundle_flag_parses() {
        let args = lint_args(parse_cli(&[
            "varde-workflow",
            "lint",
            "--bundle",
            "sub/dir",
        ]));
        assert_eq!(args.bundle, Some(PathBuf::from("sub/dir")));
    }
}

#[derive(Debug, Args)]
pub struct ReviewBindWorktreeArgs {
    #[arg(long)]
    pub subject: String,
    #[arg(long)]
    pub binding: String,
    #[arg(long)]
    pub expected_version: String,
    #[arg(long)]
    pub worktree: PathBuf,
    #[arg(long = "scope", required = true)]
    pub scope: Vec<String>,
    #[arg(long)]
    pub task: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}
#[derive(Debug, Args)]
pub struct ReviewWorktreeArgs {
    #[arg(long)]
    pub subject: String,
    #[arg(long)]
    pub binding: String,
    #[arg(long)]
    pub json: bool,
}
#[derive(Debug, Args)]
pub struct ReviewReleaseWorktreeArgs {
    #[arg(long)]
    pub subject: String,
    #[arg(long)]
    pub binding: String,
    #[arg(long)]
    pub expected_version: String,
    #[arg(long)]
    pub commit: String,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ReviewAbandonWorktreeArgs {
    #[arg(long)]
    pub subject: String,
    #[arg(long)]
    pub binding: String,
    #[arg(long)]
    pub expected_version: String,
    #[arg(long)]
    pub reason: String,
    #[arg(long)]
    pub json: bool,
}
