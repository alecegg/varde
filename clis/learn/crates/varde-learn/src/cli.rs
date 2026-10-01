use std::path::PathBuf;

use clap::{Args, Parser, Subcommand, ValueEnum};
use varde_learn_core::DEFAULT_PAGE_LIMIT;

/// Trigger-accuracy and output-quality evaluation tool for varde skills.
#[derive(Debug, Parser)]
#[command(name = "varde-learn", version)]
pub struct Cli {
    #[command(subcommand)]
    pub command: TopCommand,
}

#[derive(Debug, Subcommand)]
pub enum TopCommand {
    /// Inspect bounded evidence from a local agent session.
    Diagnose {
        #[command(subcommand)]
        command: DiagnoseCommand,
    },
    /// Measure skill trigger accuracy or skill-guided output quality.
    ///
    /// Every `eval` run launches one or more billed harness sessions
    /// (Claude, Codex, or opencode); provider usage and charges scale with
    /// `--runs`. Codex has no documented skill-invocation event: `eval
    /// trigger` falls back to a substring proxy for Codex, counting a
    /// trigger only when a completed command_execution contains the
    /// absolute `--skill-path`. Do not rely on the Codex proxy for prompts
    /// that ask to inspect the skill file itself.
    Eval {
        #[command(subcommand)]
        command: EvalCommand,
    },
    /// Read and maintain the global friction store.
    Friction {
        #[command(subcommand)]
        command: FrictionCommand,
    },
    /// Record applied skill changes against friction items.
    Adopt {
        #[command(subcommand)]
        command: AdoptionCommand,
    },
}

#[derive(Debug, Subcommand)]
pub enum DiagnoseCommand {
    /// Inspect one local session or page a frozen evidence bundle.
    Inspect(DiagnoseInspectArgs),
    /// Record one verified historical incident from a frozen evidence bundle.
    Capture(DiagnoseCaptureArgs),
}

#[derive(Debug, Args)]
#[command(override_usage = "varde-learn diagnose capture [OPTIONS] --json")]
#[command(group(clap::ArgGroup::new("capture_input").required(true).multiple(false).args(["file", "snapshot"])))]
pub struct DiagnoseCaptureArgs {
    /// Strict JSON file describing one incident and its frozen source anchor.
    #[arg(long, value_name = "incident.json", conflicts_with_all = ["source_id", "record_index", "native_id", "kind", "evidence", "item_id", "item_source", "item_title", "item_target"])]
    pub file: Option<PathBuf>,

    /// Frozen evidence bundle to build the request from (use instead of --file).
    #[arg(long, requires_all = ["source_id", "record_index", "kind", "evidence"])]
    pub snapshot: Option<PathBuf>,

    /// Source ID of the record to capture.
    #[arg(long)]
    pub source_id: Option<String>,

    /// Record index of the record to capture.
    #[arg(long)]
    pub record_index: Option<u64>,

    /// Native record ID; needed when source ID and record index match several records.
    #[arg(long)]
    pub native_id: Option<String>,

    /// Incident kind: failed-tool, repeated-work, or workflow-deviation.
    #[arg(long)]
    pub kind: Option<String>,

    /// Observed evidence text (8 KiB limit).
    #[arg(long)]
    pub evidence: Option<String>,

    /// Existing friction item ID.
    #[arg(long, conflicts_with_all = ["item_source", "item_title", "item_target"])]
    pub item_id: Option<i64>,

    /// Source of a new friction item.
    #[arg(long, requires = "item_title")]
    pub item_source: Option<String>,

    /// Title of a new friction item.
    #[arg(long, requires = "item_source")]
    pub item_title: Option<String>,

    /// Target path of a new friction item.
    #[arg(long, requires = "item_source")]
    pub item_target: Option<String>,

    /// Print the shared machine-readable output envelope.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Clone, Copy, ValueEnum)]
pub enum DiagnoseHarness {
    Codex,
    Claude,
    Opencode,
}

#[derive(Debug, Args)]
pub struct DiagnoseInspectArgs {
    /// Native session format to inspect.
    #[arg(long, value_enum)]
    pub harness: Option<DiagnoseHarness>,

    /// Inspect the verified session identified by the harness environment.
    #[arg(long, conflicts_with_all = ["session", "path", "snapshot_in"])]
    pub current: bool,

    /// Canonical harness session/thread ID.
    #[arg(long, conflicts_with_all = ["current", "path", "snapshot_in"])]
    pub session: Option<String>,

    /// Explicit native transcript file.
    #[arg(long, conflicts_with_all = ["current", "session", "snapshot_in"])]
    pub path: Option<PathBuf>,

    /// Page a frozen normalized evidence bundle without reading live sources.
    #[arg(long, conflicts_with_all = ["harness", "current", "session", "path", "snapshot_out", "cutoff_anchor"])]
    pub snapshot_in: Option<PathBuf>,

    /// Create a bounded normalized evidence bundle without overwriting an existing path.
    #[arg(long)]
    pub snapshot_out: Option<PathBuf>,

    /// JSON file identifying a verified pre-orchestration source record.
    #[arg(long)]
    pub cutoff_anchor: Option<PathBuf>,

    /// Number of normalized evidence records to skip.
    #[arg(long, default_value_t = 0)]
    pub offset: usize,

    /// Maximum evidence records to return (1 to 1000).
    #[arg(long, default_value_t = DEFAULT_PAGE_LIMIT)]
    pub limit: usize,

    /// Print the shared machine-readable output envelope.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Subcommand)]
pub enum AdoptionCommand {
    /// Record an applied change and promote its friction items.
    Record(AdoptionRecordArgs),
    /// List recorded adoptions with a later occurrence.
    Recurrence(AdoptionRecurrenceArgs),
}

#[derive(Debug, Args)]
pub struct AdoptionRecurrenceArgs {
    /// Number of recurrence events to skip.
    #[arg(long, default_value_t = 0)]
    pub offset: usize,

    /// Maximum recurrence events to return (1 to 1000).
    #[arg(long, default_value_t = DEFAULT_PAGE_LIMIT)]
    pub limit: usize,

    /// Print the shared machine-readable output envelope.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct AdoptionRecordArgs {
    /// Comma-separated friction item IDs to promote.
    #[arg(long, value_name = "IDS", value_delimiter = ',')]
    pub items: Vec<i64>,

    /// Short summary of the applied change.
    #[arg(long)]
    pub summary: String,

    /// Comma-separated changed file paths.
    #[arg(long, value_name = "PATHS", value_delimiter = ',')]
    pub files: Vec<String>,

    /// Commit SHA for the applied change.
    #[arg(long)]
    pub commit: Option<String>,

    /// Path to the before benchmark JSON file.
    #[arg(long, value_name = "BENCHMARK_JSON")]
    pub eval_before: Option<PathBuf>,

    /// Path to the after benchmark JSON file.
    #[arg(long, value_name = "BENCHMARK_JSON")]
    pub eval_after: Option<PathBuf>,

    /// Print the shared machine-readable output envelope.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Subcommand)]
pub enum FrictionCommand {
    /// List friction items with optional filters.
    List(FrictionListArgs),
    /// Add a friction item or append an occurrence.
    Add(FrictionAddArgs),
    /// Show an item and its occurrences and status history.
    Show(FrictionShowArgs),
    /// Change an item's status and record the reason.
    SetStatus(FrictionSetStatusArgs),
    /// Export every friction item as a Markdown file in a directory.
    Export(FrictionExportArgs),
    /// Import legacy and exported friction Markdown files from a directory.
    Import(FrictionImportArgs),
}

#[derive(Debug, Args)]
pub struct FrictionListArgs {
    /// Filter by open, resolved, promoted, or archived.
    #[arg(long)]
    pub status: Option<String>,

    /// Match the exact skill or tool source value.
    #[arg(long)]
    pub source: Option<String>,

    /// Filter items scoped to this repository root.
    #[arg(long, value_name = "ROOT")]
    pub repo: Option<PathBuf>,

    /// Filter global items with no repository scope.
    #[arg(long)]
    pub global: bool,

    /// Case-insensitive literal substring of a title or occurrence evidence.
    #[arg(long)]
    pub text: Option<String>,

    /// Number of items to skip before returning a page.
    #[arg(long, default_value_t = 0)]
    pub offset: usize,

    /// Maximum number of items to return (1 to 1000).
    #[arg(long, default_value_t = DEFAULT_PAGE_LIMIT)]
    pub limit: usize,

    /// Print the shared machine-readable output envelope.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct FrictionShowArgs {
    /// Numeric item ID or safe item slug.
    pub identifier: String,

    /// Offset shared by occurrence and status-history pages.
    #[arg(long, default_value_t = 0)]
    pub offset: usize,

    /// Maximum rows from each collection (1 to 1000).
    #[arg(long, default_value_t = DEFAULT_PAGE_LIMIT)]
    pub limit: usize,

    /// Print the shared machine-readable output envelope.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct FrictionSetStatusArgs {
    /// Numeric friction item ID.
    pub id: i64,

    /// New status: open, resolved, promoted, or archived.
    pub status: String,

    /// Reason recorded with the status transition.
    #[arg(long)]
    pub reason: String,

    /// Print the shared machine-readable output envelope.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct FrictionExportArgs {
    /// Directory that will receive one Markdown file per friction item.
    pub directory: PathBuf,

    /// Print the shared machine-readable output envelope.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct FrictionImportArgs {
    /// Directory containing friction Markdown files.
    pub directory: PathBuf,

    /// Repository root to associate with imported legacy occurrences.
    #[arg(long, value_name = "ROOT")]
    pub repo: PathBuf,

    /// Validate and report without creating or changing the friction store.
    #[arg(long)]
    pub dry_run: bool,

    /// Number of file results to skip in the report.
    #[arg(long, default_value_t = 0)]
    pub offset: usize,

    /// Maximum file results to return (1 to 1000).
    #[arg(long, default_value_t = DEFAULT_PAGE_LIMIT)]
    pub limit: usize,

    /// Print the shared machine-readable output envelope.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct FrictionAddArgs {
    /// Append an occurrence to an existing item ID.
    #[arg(long)]
    pub item: Option<i64>,

    /// Skill or tool that exposed the friction.
    #[arg(long)]
    pub source: Option<String>,

    /// Short friction item title (required when creating an item).
    #[arg(long)]
    pub title: Option<String>,

    /// Keep the item global instead of scoping it to the current repository.
    #[arg(long)]
    pub global: bool,

    /// File or symbol associated with the friction.
    #[arg(long)]
    pub target: Option<String>,

    /// Print the shared machine-readable output envelope.
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Subcommand)]
pub enum EvalCommand {
    /// Measure a skill description's trigger accuracy against queries.
    Trigger(TriggerArgs),
    /// Measure skill-guided output quality against baseline runs.
    Output(OutputArgs),
}

#[derive(Debug, Clone, Copy, ValueEnum)]
pub enum Harness {
    Claude,
    Codex,
    Opencode,
}

#[derive(Debug, Args)]
pub struct TriggerArgs {
    /// Name of the skill being evaluated.
    pub skill_name: String,

    /// Path to a JSON file of `{"query": string, "should_trigger": bool}` queries.
    pub queries: PathBuf,

    /// Harness to run the eval against.
    #[arg(long)]
    pub harness: Harness,

    /// Number of runs per query.
    #[arg(long, default_value_t = 3)]
    pub runs: u32,

    /// Per-harness timeout in seconds.
    #[arg(long, default_value_t = 300)]
    pub timeout_seconds: u64,

    /// Absolute path to the skill file, used by the Codex substring proxy.
    #[arg(long)]
    pub skill_path: Option<PathBuf>,
}

#[derive(Debug, Clone, Copy, ValueEnum)]
pub enum OutputHarness {
    Codex,
    Claude,
}

#[derive(Debug, Args)]
pub struct OutputArgs {
    /// Directory containing the skill under evaluation.
    pub skill_dir: PathBuf,

    /// Official client used for evaluated sessions and judging; no fallback.
    #[arg(long, value_enum, default_value = "codex")]
    pub harness: OutputHarness,

    /// Model for evaluated sessions (Codex defaults to gpt-6-luna; Claude uses its default).
    #[arg(long)]
    pub model: Option<String>,

    /// Judge model override; defaults to the evaluated model.
    #[arg(long)]
    pub judge_model: Option<String>,

    /// Number of runs per eval.
    #[arg(long, default_value_t = 1)]
    pub runs: u32,

    /// Iteration number, recorded alongside results.
    #[arg(long, default_value_t = 1)]
    pub iteration: u32,

    /// Workspace directory the harness session runs in.
    #[arg(long)]
    pub workspace: Option<PathBuf>,

    /// Eval ID to run; repeat to select several. Defaults to all evals.
    #[arg(long = "eval")]
    pub eval: Vec<String>,

    /// Per-run timeout in seconds.
    #[arg(long, default_value_t = 300)]
    pub timeout_seconds: u64,

    /// Directory to sandbox the harness session in.
    #[arg(long)]
    pub sandbox_dir: Option<PathBuf>,

    /// Skip the baseline (no-skill) comparison run.
    #[arg(long)]
    pub no_baseline: bool,
}
