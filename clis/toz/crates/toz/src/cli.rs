use clap::{Args, Parser, Subcommand};
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(
    name = "varde-toz",
    version,
    about = "Keep large tool output out of the LLM context window"
)]
pub struct Cli {
    #[command(flatten)]
    pub global: GlobalOpts,
    #[command(subcommand)]
    pub cmd: Command,
}

#[derive(Args, Debug, Clone)]
pub struct GlobalOpts {
    /// Harness-supplied external fallback directory (VARDE_TOZ_CONFIG_DIR takes precedence)
    #[arg(long, global = true)]
    pub fallback_dir: Option<PathBuf>,
    /// Project directory (default: git root of cwd, else cwd)
    #[arg(long, global = true)]
    pub project: Option<PathBuf>,
    /// Machine-readable JSON output
    #[arg(long, global = true)]
    pub json: bool,
    /// Print only the handle line on overflow
    #[arg(long, global = true)]
    pub quiet: bool,
}

#[derive(Subcommand, Debug)]
pub enum Command {
    /// Search or retrieve stored output
    Query(QueryArgs),
    /// Run a QuickJS script and capture its command output
    Run(RunArgs),
    /// Capture already-produced output from stdin (or a hook payload)
    #[command(hide = true)]
    Capture(CaptureArgs),
    /// Index local files or directories so they can be searched (records mtime + hash)
    Index(IndexArgs),
    /// Fetch web pages as readable text and index them (24 h disk cache)
    Fetch(FetchArgs),
    /// Bytes kept out of context, per kind (estimated tokens labelled as such)
    #[command(hide = true)]
    Stats(StatsArgs),
    /// Delete this project's store (or prune with --older-than)
    #[command(hide = true)]
    Purge(PurgeArgs),
    /// Redact legacy capture and fetch-cache metadata in place
    MigrateMetadata,
    /// Check the install: store, FTS5, cache, plugins, conflicting plugins
    Doctor,
    /// Inspect output profiles loaded from built-in, user, and project scopes
    Profile(ProfileArgs),
    /// Record a metadata-only harness outcome
    #[command(hide = true)]
    Event(EventArgs),
    /// Install (or refresh) a harness integration
    Install(InstallArgs),
    /// Remove a harness integration (reverses `install`, leaving other tools' entries alone)
    #[command(hide = true)]
    Uninstall(UninstallArgs),
    /// Print the session-start usage note (used by harness hooks)
    #[command(hide = true)]
    Note(NoteArgs),
}

#[derive(Args, Debug)]
pub struct ProfileArgs {
    #[command(subcommand)]
    pub cmd: ProfileCommand,
}

#[derive(Subcommand, Debug)]
pub enum ProfileCommand {
    /// List loaded profiles (id, scope, file, has_script) and load diagnostics
    List,
    /// Run each profile's `[[profile.test]]` cases against an in-memory store
    Test(ProfileTestArgs),
}

#[derive(Args, Debug)]
pub struct ProfileTestArgs {
    /// Load only this file's profiles (as user scope, so scripts run) instead of every scope
    #[arg(long)]
    pub file: Option<PathBuf>,
}

#[derive(Args, Debug)]
pub struct RawArgs {
    /// Opaque raw-output handle returned by `vardeToz.exec()` inside `run`
    pub handle: String,
    /// Exact stream to write to stdout
    #[arg(long, value_parser = ["stdout", "stderr"], required = true)]
    pub stream: String,
}

#[derive(Args, Debug)]
pub struct InstallArgs {
    /// Which harness: claude-code | pi | opencode | codex
    pub harness: String,
    /// Target directory (default: the harness's standard location)
    #[arg(long)]
    pub dir: Option<PathBuf>,
    /// Print the files instead of writing them
    #[arg(long)]
    pub print: bool,
    /// Install the shim for this harness version (default: probe `<harness> --version`)
    #[arg(long, value_name = "X.Y.Z")]
    pub for_version: Option<String>,
    /// Replace files even when they look hand-edited
    #[arg(long)]
    pub force: bool,
}

#[derive(Args, Debug)]
pub struct NoteArgs {
    /// Emit in the hook JSON format for this harness (claude-code); plain text otherwise
    #[arg(long)]
    pub harness: Option<String>,
}

#[derive(Args, Debug)]
pub struct EventArgs {
    #[arg(long)]
    pub harness: String,
    #[arg(long, value_parser = ["captured", "skipped", "failed"])]
    pub outcome: String,
    #[arg(long)]
    pub reason: String,
    #[arg(long, default_value = "")]
    pub tool: String,
    #[arg(long, default_value_t = 0)]
    pub bytes: usize,
}

#[derive(Args, Debug)]
pub struct RunArgs {
    /// Run a QuickJS batch script from a file, or `-` for stdin.
    #[arg(long, required_unless_present = "code", conflicts_with = "code")]
    pub script: Option<String>,
    /// Run an inline QuickJS batch script.
    #[arg(long, conflicts_with = "script")]
    pub code: Option<String>,
    /// Capture to read from the script.
    #[arg(long)]
    pub handle: Option<String>,
    /// Capture stream to read (stdout | stderr).
    #[arg(long, default_value = "stdout")]
    pub stream: String,
    /// Permit computation over an unfinished capture.
    #[arg(long)]
    pub partial: bool,
    /// Script wall-clock limit in milliseconds.
    #[arg(long)]
    pub timeout_ms: Option<u64>,
    /// Script heap limit in MB.
    #[arg(long)]
    pub memory_mb: Option<usize>,
    /// Human label for the capture (also the supersession key)
    #[arg(long, short)]
    pub label: Option<String>,
}

#[derive(Args, Debug)]
pub struct SearchArgs {
    #[arg(required = true)]
    pub queries: Vec<String>,
    /// Scope to one capture
    #[arg(long, short = 'H')]
    pub handle: Option<String>,
    /// Partial match on label or source
    #[arg(long, short)]
    pub source: Option<String>,
    /// Results per query
    #[arg(long, short, default_value_t = 3)]
    pub limit: usize,
    /// Filter by content type
    #[arg(long = "type", value_parser = ["code", "prose"])]
    pub content_type: Option<String>,
    /// Include superseded captures
    #[arg(long)]
    pub all: bool,
    /// Search every project store
    #[arg(long)]
    pub global: bool,
}

#[derive(Args, Debug)]
pub struct QueryArgs {
    /// Search terms. Omit to retrieve a capture with --handle.
    pub queries: Vec<String>,
    /// Capture to search or retrieve
    #[arg(long, short = 'H', visible_alias = "id")]
    pub handle: Option<String>,
    /// Retrieve exact bytes from an opt-in raw-output handle
    #[arg(long)]
    pub raw: Option<String>,
    /// List recent captures
    #[arg(long)]
    pub list: bool,
    /// Print only this chunk (0-based)
    #[arg(long, short)]
    pub chunk: Option<usize>,
    /// Print a matched profile script's `vardeToz.record()` output of this kind, as JSONL
    #[arg(long)]
    pub records: Option<String>,
    /// Print only lines A:B (1-based, inclusive)
    #[arg(long, short)]
    pub lines: Option<String>,
    /// Output stream for capture or raw retrieval
    #[arg(long, default_value = "stdout", value_parser = ["stdout", "stderr"])]
    pub stream: String,
    /// Partial match on label or source when searching
    #[arg(long, short)]
    pub source: Option<String>,
    /// Results per search term, or number of listed captures
    #[arg(long)]
    pub limit: Option<usize>,
    /// Filter search results by content type
    #[arg(long = "type", value_parser = ["code", "prose"])]
    pub content_type: Option<String>,
    /// Include superseded captures
    #[arg(long)]
    pub all: bool,
    /// Search every project store
    #[arg(long)]
    pub global: bool,
}

#[derive(Args, Debug)]
pub struct CaptureArgs {
    /// Human label for the capture
    #[arg(long, short)]
    pub label: Option<String>,
    /// Origin string (command, path, URL) used for the supersession key
    #[arg(long, short)]
    pub source: Option<String>,
    /// Kind tag stored with the capture (e.g. hook:Bash)
    #[arg(long, default_value = "capture")]
    pub kind: String,
    /// Byte threshold override
    #[arg(long, short)]
    pub threshold: Option<usize>,
    /// Exit code to record
    #[arg(long)]
    pub exit_code: Option<i32>,
    /// Read a hook JSON payload ({tool_name, tool_input, tool_response, session_id}) from stdin
    #[arg(long)]
    pub hook: bool,
    /// Which harness sent the hook payload: claude-code | pi | opencode | codex
    #[arg(long, default_value = "claude-code", requires = "hook")]
    pub harness: String,
    /// Treat stdin as stderr rather than stdout
    #[arg(long)]
    pub stderr: bool,
    /// Store even if under threshold
    #[arg(long)]
    pub force: bool,
    /// Defer full-text indexing until the first term search
    #[arg(long, conflicts_with = "hook")]
    pub defer_index: bool,
}

#[derive(Args, Debug)]
pub struct ShowArgs {
    pub handle: String,
    /// Print only this chunk (0-based index as listed in the preview)
    #[arg(long, short)]
    pub chunk: Option<usize>,
    /// Print a matched profile script's `vardeToz.record()` output of this kind, as JSONL
    #[arg(long)]
    pub records: Option<String>,
    /// Print only lines A:B (1-based, inclusive)
    #[arg(long, short)]
    pub lines: Option<String>,
    /// Which stream (stdout | stderr)
    #[arg(long, default_value = "stdout")]
    pub stream: String,
}

#[derive(Args, Debug)]
pub struct ListArgs {
    #[arg(long, short, default_value_t = 20)]
    pub limit: usize,
    /// Include superseded captures
    #[arg(long)]
    pub all: bool,
}

#[derive(Args, Debug)]
pub struct IndexArgs {
    /// Files or directories; `-` reads stdin
    #[arg(required = true)]
    pub paths: Vec<PathBuf>,
    /// Human label (single path only; also the supersession key)
    #[arg(long, short)]
    pub label: Option<String>,
    /// Descend into subdirectories
    #[arg(long, short)]
    pub recursive: bool,
    /// Only files whose name matches this glob (e.g. "*.md", "*.{rs,toml}")
    #[arg(long, short)]
    pub glob: Option<String>,
}

#[derive(Args, Debug)]
pub struct FetchArgs {
    #[arg(required = true)]
    pub urls: Vec<String>,
    /// Human label (single URL only; also the supersession key)
    #[arg(long, short)]
    pub label: Option<String>,
    /// Cache TTL in seconds (default 86400); 0 always refetches
    #[arg(long)]
    pub ttl: Option<u64>,
    /// Ignore the cache
    #[arg(long)]
    pub force: bool,
    /// Parallel fetches
    #[arg(long, short, default_value_t = 4)]
    pub concurrency: usize,
}

#[derive(Args, Debug)]
pub struct StatsArgs {
    /// Only this session (VARDE_TOZ_SESSION if set, else the last 8 hours)
    #[arg(long)]
    pub session: bool,
    /// Every project store
    #[arg(long)]
    pub global: bool,
}

#[derive(Args, Debug)]
pub struct PurgeArgs {
    /// Skip the confirmation prompt (required when stdin is not a terminal)
    #[arg(long, short)]
    pub yes: bool,
    /// Every project store (and the fetch cache)
    #[arg(long)]
    pub global: bool,
    /// Prune captures older than this (e.g. 30m, 12h, 7d) instead of wiping
    #[arg(long)]
    pub older_than: Option<String>,
}

#[derive(Args, Debug)]
pub struct UninstallArgs {
    /// Which harness: claude-code | pi | opencode | codex
    pub harness: String,
    /// Directory it was installed into (default: the harness's standard location)
    #[arg(long)]
    pub dir: Option<PathBuf>,
}
