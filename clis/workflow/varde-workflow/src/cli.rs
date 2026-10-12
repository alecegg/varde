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

fn duration_seconds(value: &str) -> Result<u64, String> {
    let message = "value must be a positive duration such as 90s, 20m, or 1h";
    // Split on a char boundary: a byte-index slice panics when the last
    // character is multibyte.
    let (digits, multiplier) = if let Some(digits) = value.strip_suffix('s') {
        (digits, 1)
    } else if let Some(digits) = value.strip_suffix('m') {
        (digits, 60)
    } else if let Some(digits) = value.strip_suffix('h') {
        (digits, 3600)
    } else {
        return Err(message.to_string());
    };
    match digits.parse::<u64>() {
        Ok(count) if count > 0 => count.checked_mul(multiplier).ok_or(message.to_string()),
        _ => Err(message.to_string()),
    }
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
    #[command(after_long_help = VALIDATE_HELP)]
    Validate(ValidateArgs),
    /// Resolve one artifact dependency graph
    Graph(GraphArgs),
    /// Audit one source commit against its task ownership
    CheckTaskOwnership(CheckTaskOwnershipArgs),
    /// Select the next advisory execution wave without mutation
    ExecutionWave(ExecutionWaveArgs),
    /// Report blockers and available workflow actions
    #[command(after_long_help = READINESS_HELP)]
    Readiness(ReadinessArgs),
    /// Show compact progress for non-terminal plans
    #[command(after_long_help = STATUS_HELP)]
    Status(StatusArgs),
    /// Set or clear a plan's current progress line
    #[command(after_long_help = NOW_HELP)]
    Now(NowArgs),
    /// Set or clear the harness-neutral owner for one plan
    #[command(after_long_help = OWNER_HELP)]
    Owner(OwnerArgs),
    /// Watch plans and print one line per stale, blocked, or finished event
    #[command(after_long_help = WATCH_HELP)]
    Watch(WatchArgs),
    /// Send and read one-line inbox messages between agents
    Msg(MsgArgs),
    /// Verify the review report and mark a plan completed
    #[command(after_long_help = CONCLUDE_HELP)]
    Conclude(ConcludeArgs),
    /// Print a read-only knowledge skeleton for a plan
    Distill(DistillArgs),
    /// Manage Concepts within a Knowledge Bundle
    Concept {
        #[command(subcommand)]
        command: ConceptCommand,
    },
    /// Lint a Knowledge Bundle for structural health issues
    Lint(LintArgs),
    /// Show or configure where working, knowledge, and learn memory live
    Paths(PathsArgs),
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
    /// Maximum number of builders in flight
    #[arg(long, value_parser = positive_u32)]
    pub builders: Option<u32>,
    /// Instruction sections to include
    #[arg(long, default_value = "orchestration,toz")]
    pub sections: String,
    /// Include the optional learning guidance
    #[arg(long)]
    pub learn: bool,
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
    /// Integration commit already merged into the worker (repeatable)
    #[arg(long = "trusted-tip")]
    pub trusted_tips: Vec<String>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ExecutionWaveArgs {
    pub plan_dir: PathBuf,
    #[arg(long)]
    pub repo_root: Option<PathBuf>,
    /// Maximum parallel tasks (defaults to [orchestration] builders)
    #[arg(long)]
    pub max_workers: Option<usize>,
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
    /// Directory for working memory (plans, session notes, reviews)
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
pub struct StatusArgs {
    /// Repository whose commits and `owns` paths `reviewed_commit` refers to
    #[arg(long)]
    pub repo: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct NowArgs {
    pub plan: PathBuf,
    #[arg(
        value_name = "TEXT",
        required_unless_present_any = ["clear", "waiting"],
        conflicts_with_all = ["clear", "waiting"]
    )]
    pub text: Option<String>,
    #[arg(long, conflicts_with_all = ["text", "waiting"])]
    pub clear: bool,
    /// Store `waiting: <reason>`, which holds off stale events for a while
    #[arg(long, value_name = "REASON", conflicts_with_all = ["text", "clear"])]
    pub waiting: Option<String>,
    /// Repository whose commits and `owns` paths `reviewed_commit` refers to
    #[arg(long)]
    pub repo: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

const WATCH_HELP: &str = "\
Reports plan state as stale, blocked, needs-decision, merge-ready, or finished events; `msg` carries free text between agents, while `watch` reports plan state.\n\
Events print as `<kind> <plan-id> <detail>`: stale (idle past --stale; repeats
each further threshold), blocked, needs-decision (open questions), merge-ready
(all tasks terminal) and finished (plan terminal).

Delivery, most to least preferred:
  1. push: the user-config `orchestration.wake_command` (an argv, run without a
     shell) starts the owning session's turn after the inbox write. Its
     environment has VARDE_WAKE_EVENT, VARDE_WAKE_PLAN, VARDE_WAKE_OWNER (empty
     when the plan has no owner) and VARDE_WAKE_TEXT; values lose control
     characters and stop at 300 characters. The command is killed after
     `orchestration.wake_timeout_seconds` (default 10), its stdout is discarded,
     and a failure becomes an `info` inbox line (stderr with --no-inbox). After
     `orchestration.wake_max_failures` (default 3) consecutive failures wake
     stays off until the watcher restarts. --no-wake skips it.
  2. subscribe: the harness runs this command as a background process and turns
     stdout lines into notifications (it may have a time cap).
  3. inbox: every event is appended once to the `main` inbox as kind stale,
     blocked, merge-ready, needs-user (needs-decision) or done (finished); the
     per-prompt hook prints it on the next turn. --no-inbox turns this off and
     --once then prints all current events.

One watcher per cache key (the --notes path, else the repo): a second one on the
same key exits non-zero. A headless timer runs `--once`; see docs/automatic-wake.md
in the varde repository for timers and per-harness recipes.";

const STATUS_HELP: &str = "\
Prints a progress block for non-cancelled plans, including task progress and each plan's current `now` line. The block also surfaces blockers and available next actions.";

const READINESS_HELP: &str = "\
Reports whether plan dependencies are ready and lists blockers and available next actions. A task is ready when its status is `todo` and all dependencies are `done`.";

const VALIDATE_HELP: &str = "\
JSON failures use diagnostic code `validation_failed`; plan status values are `backlog`, `active`, `blocked`, `completed`, and `cancelled`, while task values are `todo`, `in_progress`, `blocked`, and `done`.";

const NOW_HELP: &str = "\
Sets or clears a plan's current progress line; `msg` carries free text between agents, while `watch` reports plan state.";

const CONCLUDE_HELP: &str = "\
Conclude succeeds only when the reviewed head equals the merged repository HEAD and the review verdict is approved.";

const OWNER_HELP: &str = "\
The owner is an opaque `<harness>:<id>` string. `varde plan watch` passes it to
`orchestration.wake_command` as VARDE_WAKE_OWNER so the wake can reach the
owning session. An orchestrator sets its own at start.\n\
Example: `varde plan owner plan.md agent:123`.";

const SEND_HELP: &str = "\
`msg` carries free text between agents; `watch` reports plan state. Text is one line of at most 300 characters (the encoded line must stay within
1000 bytes). `main` is the address the per-prompt hook reads. `varde plan watch`
writes its own events here as from `varde-watch`, kinds stale, blocked,
merge-ready, needs-user, done and info.";

#[derive(Debug, Args)]
pub struct OwnerArgs {
    /// Plan path or identifier
    pub plan: PathBuf,
    /// Owner identifier in opaque `<harness>:<id>` form
    #[arg(
        value_name = "HARNESS:ID",
        required_unless_present = "clear",
        conflicts_with = "clear"
    )]
    pub owner: Option<String>,
    /// Remove the plan owner
    #[arg(long, conflicts_with = "owner")]
    pub clear: bool,
}

#[derive(Debug, Args)]
pub struct MsgArgs {
    #[command(subcommand)]
    pub command: MsgCommand,
}

#[derive(Debug, Subcommand)]
pub enum MsgCommand {
    /// Append one message line to the inbox store
    #[command(after_long_help = SEND_HELP)]
    Send(SendArgs),
    /// Print a reader's unread messages and advance its cursor
    Read(ReadArgs),
}

#[derive(Debug, Args)]
pub struct SendArgs {
    /// Sender name
    #[arg(long)]
    pub from: String,
    /// Recipient address: `main`, an agent name, or a plan id
    #[arg(long)]
    pub to: String,
    /// Message kind: blocked, needs-user, done, info, stale, or merge-ready
    #[arg(long)]
    pub kind: String,
    /// Optional absolute path to a longer note
    #[arg(long)]
    pub notes: Option<PathBuf>,
    /// One-line message text
    #[arg(value_name = "TEXT")]
    pub text: String,
}

#[derive(Debug, Args)]
pub struct ReadArgs {
    /// Address to read as
    #[arg(long = "as", default_value = "main")]
    pub address: String,
    /// Print every message without moving the cursor
    #[arg(long)]
    pub all: bool,
    /// Print the messages as one JSON document
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct WatchArgs {
    /// Do not append events to the main inbox (and print all current events once)
    #[arg(long)]
    pub no_inbox: bool,
    /// Do not run the configured wake command
    #[arg(long)]
    pub no_wake: bool,
    /// Idle time that makes a plan stale, such as 20m (default: orchestration.stall_minutes)
    #[arg(long, value_name = "DURATION", value_parser = duration_seconds)]
    pub stale: Option<u64>,
    /// Time between checks, such as 60s
    #[arg(
        long,
        value_name = "DURATION",
        value_parser = duration_seconds,
        default_value = "60s"
    )]
    pub interval: u64,
    /// Check once, record and wake, then exit (with --no-inbox, print all current events)
    #[arg(long)]
    pub once: bool,
    /// Repository whose branches and worktrees show plan activity
    #[arg(long)]
    pub repo: Option<PathBuf>,
    /// Session notes file whose plan-status block is kept current
    #[arg(long = "notes", alias = "handoff", value_name = "PATH")]
    pub notes: Option<PathBuf>,
    /// Print each event as one JSON line
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct ConcludeArgs {
    pub plan: PathBuf,
    /// Commit the reviewed work is merged as (defaults to the repository HEAD)
    #[arg(long)]
    pub merged: Option<String>,
    /// Repository holding the reviewed and merged commits
    #[arg(long)]
    pub repo: Option<PathBuf>,
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct DistillArgs {
    pub plan_dir: PathBuf,
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
    /// resolution as `varde setup paths`) when omitted.
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
    /// resolution as `varde setup paths`) when omitted.
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
    /// resolution as `varde setup paths`) when omitted.
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

    #[test]
    fn duration_seconds_parses_units_and_rejects_bad_suffixes() {
        assert_eq!(duration_seconds("90s"), Ok(90));
        assert_eq!(duration_seconds("20m"), Ok(1200));
        assert_eq!(duration_seconds("1h"), Ok(3600));
        // A multibyte last character must return the usual error, not panic.
        assert!(duration_seconds("5é").is_err());
        assert!(duration_seconds("").is_err());
        assert!(duration_seconds("0m").is_err());
    }
}
