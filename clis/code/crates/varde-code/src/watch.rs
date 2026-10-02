//! `varde-code watch`: a long-lived, foreground background watcher that
//! proactively keeps configured repos' indexes warm.
//!
//! This is the index writer for query-serving slices. It reads and writes
//! the same freshness truth in SQLite
//! (`slice_state.built_through_rev`, `files.rev`); the watcher holds no
//! freshness state of its own in memory, so a killed-and-restarted watcher
//! resumes purely by re-reading DB state, with no burst-fire or
//! double-work risk on restart. Queries validate freshness without writing.

use anyhow::{Context, Result, bail};
use notify::{Event, RecursiveMode, Watcher};
use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::{Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{RecvTimeoutError, SyncSender, TrySendError, sync_channel};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::slice::{Scope, Slice, ensure_fresh};

/// The five slices a "keep everything warm" watcher freshens per repo —
/// mirrors what a repo-wide query already reads; the watcher does not
/// introduce a new rebuild target, it drives the existing full slice set
/// proactively.
const ALL_SLICES: [Slice; 5] = [
    Slice::Raw,
    Slice::Churn,
    Slice::Imports,
    Slice::Edges,
    Slice::Global,
];

/// Keep filesystem ingestion bounded while preserving a dirty-repository bit.
/// The reconciler refreshes the whole repository, so diagnostic paths can be
/// sampled without losing correctness when a producer outruns the consumer.
const EVENT_SIGNAL_CAPACITY: usize = 1;
const MAX_DIAGNOSTIC_PATHS: usize = 256;
const MAX_RECONCILE_DELAY: Duration = Duration::from_secs(30);

#[derive(Debug)]
struct PendingRepo {
    first_event: Instant,
    last_event: Instant,
    changed_paths: HashSet<PathBuf>,
}

impl PendingRepo {
    fn new(now: Instant) -> Self {
        Self {
            first_event: now,
            last_event: now,
            changed_paths: HashSet::new(),
        }
    }

    fn record_path(&mut self, path: &Path) {
        if self.changed_paths.len() < MAX_DIAGNOSTIC_PATHS {
            self.changed_paths.insert(path.to_path_buf());
        }
    }

    fn merge(&mut self, other: Self) {
        if other.first_event < self.first_event {
            self.first_event = other.first_event;
        }
        if other.last_event > self.last_event {
            self.last_event = other.last_event;
        }
        for path in other.changed_paths {
            if self.changed_paths.len() >= MAX_DIAGNOSTIC_PATHS {
                break;
            }
            self.changed_paths.insert(path);
        }
    }

    fn is_due_at(&self, now: Instant, debounce: Duration) -> bool {
        now.duration_since(self.last_event) >= debounce
            || now.duration_since(self.first_event) >= MAX_RECONCILE_DELAY
    }
}

/// Filesystem callbacks only enqueue one dirty bit per repository. The
/// channel is a wakeup hint; the mutex owns the durable pending state when
/// that bounded channel is already full.
struct PendingEvents {
    repos: Mutex<HashMap<PathBuf, PendingRepo>>,
    wake: SyncSender<()>,
}

impl PendingEvents {
    fn new(wake: SyncSender<()>) -> Self {
        Self {
            repos: Mutex::new(HashMap::new()),
            wake,
        }
    }

    fn push(&self, repo: &Path, path: &Path) -> bool {
        let now = Instant::now();
        let Ok(mut repos) = self.repos.lock() else {
            return false;
        };
        let pending = repos
            .entry(repo.to_path_buf())
            .or_insert_with(|| PendingRepo::new(now));
        pending.last_event = now;
        pending.record_path(path);
        drop(repos);

        match self.wake.try_send(()) {
            Ok(()) | Err(TrySendError::Full(())) => true,
            Err(TrySendError::Disconnected(())) => false,
        }
    }

    fn drain_into(&self, pending: &mut HashMap<PathBuf, PendingRepo>) {
        let Ok(mut repos) = self.repos.lock() else {
            return;
        };
        for (repo, state) in repos.drain() {
            match pending.entry(repo) {
                std::collections::hash_map::Entry::Occupied(mut entry) => {
                    entry.get_mut().merge(state);
                }
                std::collections::hash_map::Entry::Vacant(entry) => {
                    entry.insert(state);
                }
            }
        }
    }
}

/// Watch-list config: `~/.config/varde-code/watch.toml` by convention.
/// Discovery (`parent_dirs` → `.git` dirs) happens once at watcher startup,
/// not live — changing the watch list means restarting the process.
#[derive(Debug, Default, serde::Deserialize)]
pub struct WatchConfig {
    #[serde(default)]
    pub repos: Vec<String>,
    #[serde(default)]
    pub parent_dirs: Vec<String>,
}

impl WatchConfig {
    pub fn load(path: &Path) -> Result<Self> {
        let contents = std::fs::read_to_string(path)
            .with_context(|| format!("reading watch config {}", path.display()))?;
        toml::from_str(&contents)
            .with_context(|| format!("parsing watch config {} as TOML", path.display()))
    }

    pub fn default_path() -> PathBuf {
        crate::db::path::config_dir().join("watch.toml")
    }
}

/// Resolve `explicit` repo paths plus a config's `repos`/`parent_dirs` into
/// a deduplicated, canonicalized list of repo roots (a "repo root" is any
/// directory containing a `.git` entry). `parent_dirs` are scanned
/// one level for immediate `.git` children — not recursively walked — so
/// discovery stays cheap and predictable at startup.
pub fn resolve_repos(explicit: &[String], config: Option<&WatchConfig>) -> Result<Vec<PathBuf>> {
    let mut seen: HashSet<PathBuf> = HashSet::new();
    let mut repos: Vec<PathBuf> = Vec::new();

    let mut add = |path: &Path| -> Result<()> {
        let canon = std::fs::canonicalize(path)
            .with_context(|| format!("resolving watch path {}", path.display()))?;
        if !canon.join(".git").exists() {
            bail!("{} is not a git repo root (no .git entry)", canon.display());
        }
        if seen.insert(canon.clone()) {
            repos.push(canon);
        }
        Ok(())
    };

    for path in explicit {
        add(Path::new(path))?;
    }
    if let Some(config) = config {
        for path in &config.repos {
            add(Path::new(path))?;
        }
        for parent in &config.parent_dirs {
            let entries = std::fs::read_dir(parent)
                .with_context(|| format!("reading parent dir {parent}"))?;
            for entry in entries {
                let entry = entry?;
                if entry.path().join(".git").exists() {
                    add(&entry.path())?;
                }
            }
        }
    }

    if repos.is_empty() {
        bail!("no repos to watch: pass --repo or configure repos/parent_dirs");
    }
    Ok(repos)
}

/// Run the watcher: process-lifetime exclusive coverage locks for every repo,
/// one `notify` watcher per repo, one shared debounce loop that reconciles whichever
/// repos have pending events once `debounce` has elapsed with no further
/// events for that repo. Continuous activity still reconciles after the
/// maximum batch age, so pending diagnostics cannot grow forever.
pub fn run(repos: &[PathBuf], debounce: Duration) -> Result<()> {
    let instance_lock = acquire_instance_lock(repos)?;

    let (wake_tx, wake_rx) = sync_channel(EVENT_SIGNAL_CAPACITY);
    let pending_events = Arc::new(PendingEvents::new(wake_tx));
    // Keep each repo's `notify::Watcher` alive for the process lifetime —
    // dropping it stops that repo's events.
    let mut watchers = Vec::with_capacity(repos.len());
    for repo in repos {
        watchers.push(create_watcher(repo, Arc::clone(&pending_events))?);
        eprintln!("varde-code watch: watching {}", repo.display());
    }

    // Subscribe before reconciling so edits during the first walk are not
    // lost. The initial pass makes a restarted service useful without waiting
    // for an unrelated file event.
    for repo in repos {
        reconcile_and_mark_ready(repo, &HashSet::new(), &instance_lock)?;
    }

    // Per-repo event timestamps plus bounded diagnostic paths. The full
    // repository is reconciled, even when the path sample reaches its cap.
    let mut pending: HashMap<PathBuf, PendingRepo> = HashMap::new();
    let mut last_periodic = Instant::now();

    loop {
        let wait = next_wait(&pending, debounce)
            .min(Duration::from_secs(30).saturating_sub(last_periodic.elapsed()));
        match wake_rx.recv_timeout(wait) {
            Ok(()) => pending_events.drain_into(&mut pending),
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => {
                pending_events.drain_into(&mut pending);
                break;
            }
        }
        // Pick up events that raced with the wakeup before checking due work.
        pending_events.drain_into(&mut pending);

        reconcile_due(&mut pending, debounce, &instance_lock)?;
        // Periodic reconciliation repairs missed filesystem events and
        // retries an initial failure even on an otherwise quiet repository.
        if last_periodic.elapsed() >= Duration::from_secs(30) {
            for repo in repos {
                reconcile_and_mark_ready(repo, &HashSet::new(), &instance_lock)?;
            }
            last_periodic = Instant::now();
        }
    }
    Ok(())
}

fn create_watcher(repo: &Path, pending: Arc<PendingEvents>) -> Result<notify::RecommendedWatcher> {
    let repo_for_events = repo.to_path_buf();
    let ignore_matcher = build_ignore_matcher(repo)?;
    let mut watcher = notify::recommended_watcher(move |result: notify::Result<Event>| {
        let Ok(event) = result else { return };
        for path in event
            .paths
            .iter()
            .filter(|path| !is_ignored(&ignore_matcher, path))
        {
            if !pending.push(&repo_for_events, path) {
                eprintln!(
                    "varde-code watch: dropped change event for {} (reconcile loop gone)",
                    path.display()
                );
            }
        }
    })
    .context("creating fs watcher")?;
    watcher
        .watch(repo, RecursiveMode::Recursive)
        .with_context(|| format!("watching {}", repo.display()))?;
    Ok(watcher)
}

fn reconcile_due(
    pending: &mut HashMap<PathBuf, PendingRepo>,
    debounce: Duration,
    instance_lock: &InstanceLock,
) -> Result<()> {
    let now = Instant::now();
    let due: Vec<PathBuf> = pending
        .iter()
        .filter(|(_, state)| state.is_due_at(now, debounce))
        .map(|(repo, _)| repo.clone())
        .collect();
    for repo in due {
        if let Some(state) = pending.remove(&repo) {
            reconcile_and_mark_ready(&repo, &state.changed_paths, instance_lock)?;
        }
    }
    Ok(())
}

fn reconcile_and_mark_ready(
    repo: &Path,
    changed_paths: &HashSet<PathBuf>,
    instance_lock: &InstanceLock,
) -> Result<()> {
    let reconciled = run_guarded(repo, || reconcile(repo, changed_paths)).unwrap_or(false);
    if reconciled && index_ready(repo) {
        instance_lock.mark_ready(repo)?;
    }
    Ok(())
}

/// How long to block on the next event before re-checking which pending
/// repos have crossed the debounce window. `None` pending → block
/// indefinitely (any duration works since `recv_timeout` only needs a
/// value); otherwise wake up right when the earliest pending repo becomes
/// due.
fn next_wait(pending: &HashMap<PathBuf, PendingRepo>, debounce: Duration) -> Duration {
    next_wait_at(pending, debounce, Instant::now())
}

fn next_wait_at(
    pending: &HashMap<PathBuf, PendingRepo>,
    debounce: Duration,
    now: Instant,
) -> Duration {
    pending
        .values()
        .map(|state| {
            let quiet_wait = debounce.saturating_sub(now.duration_since(state.last_event));
            let age_wait =
                MAX_RECONCILE_DELAY.saturating_sub(now.duration_since(state.first_event));
            quiet_wait.min(age_wait)
        })
        .min()
        .unwrap_or(Duration::from_secs(3600))
        .max(Duration::from_millis(1))
}

/// Build a `.gitignore`-aware matcher for `repo` (also honoring `.ignore`
/// files, same as `ignore::WalkBuilder`'s default config used by the
/// fallback walk elsewhere in this crate).
fn build_ignore_matcher(repo: &Path) -> Result<ignore::gitignore::Gitignore> {
    let mut builder = ignore::gitignore::GitignoreBuilder::new(repo);
    for candidate in [".gitignore", ".ignore"] {
        let path = repo.join(candidate);
        if path.exists()
            && let Some(err) = builder.add(&path)
        {
            eprintln!("varde-code watch: warning: failed to read {candidate}: {err}");
        }
    }
    builder
        .build()
        .with_context(|| format!("building ignore matcher for {}", repo.display()))
}

/// Is `path` excluded from consideration — either inside a `.git/`
/// directory anywhere in its ancestry (never a meaningful source change;
/// checked by component rather than by stripping `repo`'s prefix, since
/// `notify` and `std::fs::canonicalize` can disagree on `/var` vs
/// `/private/var`-style symlink resolution on macOS) or matched by the
/// repo's own ignore rules?
fn is_ignored(matcher: &ignore::gitignore::Gitignore, path: &Path) -> bool {
    if path.components().any(|c| c.as_os_str() == ".git") {
        return true;
    }
    let is_dir = path.is_dir();
    matcher.matched(path, is_dir).is_ignore()
}

/// Reconcile one repo: drive the existing incremental `ensure_fresh` path
/// over every slice, going through the same per-repo advisory lock any
/// other caller (a concurrent CLI query) would — see `repo_lock`. Errors
/// are logged, not fatal: one repo's transient failure (e.g. a mid-rebase
/// working tree) must not take down the watcher for every other repo.
/// Run one repo's reconcile under a panic guard. A panic in a single repo's
/// reconcile (a corrupt index, a tree-sitter edge case) must not unwind the
/// whole watch loop and silently stop watching every *other* repo — catch it,
/// log, and carry on. The repo lock (released on unwind via RAII) and the
/// MEMORY-journal rollback leave that repo's index consistent.
fn run_guarded<T>(repo: &Path, task: impl FnOnce() -> T) -> Option<T> {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(task)) {
        Ok(result) => Some(result),
        Err(panic) => {
            let msg = panic
                .downcast_ref::<&str>()
                .map(|s| (*s).to_string())
                .or_else(|| panic.downcast_ref::<String>().cloned())
                .unwrap_or_else(|| "unknown cause".to_string());
            eprintln!(
                "varde-code watch: {}: reconcile panicked ({msg}); continuing",
                repo.display()
            );
            None
        }
    }
}

fn reconcile(repo: &Path, changed_paths: &HashSet<PathBuf>) -> bool {
    let repo_root = repo.to_string_lossy().into_owned();
    let reconciled = match ensure_fresh(&ALL_SLICES, &repo_root, &Scope::Repo) {
        Ok(()) => true,
        Err(err) => {
            eprintln!("varde-code watch: {repo_root}: reconcile failed: {err:#}");
            false
        }
    };
    write_last_changed(repo, changed_paths);
    reconciled
}

/// Persist the paths that triggered the most recent reconcile for `repo`,
/// so `watch --list` can surface them as a drill-down handle instead of
/// only the repo root — an agent can feed these straight into
/// `symbols_in_file`/`map_file` without having to guess what changed.
fn write_last_changed(repo: &Path, changed_paths: &HashSet<PathBuf>) {
    let dir = crate::db::path::config_dir().join("watch-locks");
    if let Err(err) = std::fs::create_dir_all(&dir) {
        eprintln!(
            "varde-code watch: cannot create {} to record changed paths for {}: {err}",
            dir.display(),
            repo.display()
        );
        return;
    }
    let path = last_changed_path_for(repo, &dir);
    let mut paths: Vec<String> = changed_paths
        .iter()
        .take(MAX_DIAGNOSTIC_PATHS)
        .map(|p| p.to_string_lossy().into_owned())
        .collect();
    paths.sort();
    let payload = serde_json::json!({ "changed_paths": paths });
    if let Err(err) = std::fs::write(&path, payload.to_string()) {
        eprintln!(
            "varde-code watch: failed to write changed-paths file {} for {}: {err}",
            path.display(),
            repo.display()
        );
    }
}

fn last_changed_path_for(repo: &Path, dir: &Path) -> PathBuf {
    dir.join(format!(
        "{}.changed",
        watch_set_id(std::slice::from_ref(&repo.to_path_buf()))
    ))
}

/// Process identity written under a held kernel lock. The generation prevents
/// stale sidecars from being mistaken for a replacement process; the kernel
/// lock itself distinguishes a live watcher from a reused PID.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
struct InstanceOwner {
    pid: u32,
    generation: String,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
struct InstanceMeta {
    repos: Vec<String>,
    owner: InstanceOwner,
    ready_repos: Vec<String>,
    #[serde(default)]
    stopped: bool,
}

/// Kernel locks enforce per-repository exclusivity. The set-level lock groups
/// those locks for `watch --list` and `watch --stop`; none of the lock files is
/// removed, so a late Drop can never unlink a replacement owner's marker.
struct InstanceLock {
    meta_path: PathBuf,
    owner: InstanceOwner,
    _set_file: File,
    _repo_files: Vec<File>,
}

impl InstanceLock {
    fn mark_ready(&self, repo: &Path) -> Result<()> {
        let repo = std::fs::canonicalize(repo)?;
        let repo = repo.to_string_lossy().into_owned();
        let mut meta = read_instance_meta(&self.meta_path)?;
        if meta.owner.generation != self.owner.generation {
            bail!("watcher ownership changed while marking {repo} ready");
        }
        if !meta.ready_repos.contains(&repo) {
            meta.ready_repos.push(repo);
            write_instance_meta(&self.meta_path, &meta)?;
        }
        Ok(())
    }
}

impl Drop for InstanceLock {
    fn drop(&mut self) {
        // Clear readiness while the set lock is still held. The stable lock
        // files remain in place; closing their descriptors releases ownership
        // atomically through the kernel.
        if let Ok(mut meta) = read_instance_meta(&self.meta_path)
            && meta.owner.generation == self.owner.generation
        {
            meta.ready_repos.clear();
            meta.stopped = true;
            if let Err(err) = write_instance_meta(&self.meta_path, &meta) {
                eprintln!("varde-code watch: failed to clear readiness: {err}");
            }
        }
    }
}

/// Sidecar of `<hash>.lock`: which repos the process covers and which have
/// completed initial reconciliation. The generation must match the locked
/// owner file before any readiness is trusted.
fn meta_path_for(lock_path: &Path) -> PathBuf {
    lock_path.with_extension("meta")
}

fn repo_coverage_path(dir: &Path, repo: &Path) -> PathBuf {
    dir.join("coverage")
        .join(format!("{}.lock", watch_set_id(&[repo.to_path_buf()])))
}

fn read_instance_meta(path: &Path) -> Result<InstanceMeta> {
    let contents = std::fs::read_to_string(path)
        .with_context(|| format!("reading watcher metadata {}", path.display()))?;
    serde_json::from_str(&contents)
        .with_context(|| format!("parsing watcher metadata {}", path.display()))
}

fn write_instance_meta(path: &Path, meta: &InstanceMeta) -> Result<()> {
    std::fs::write(path, serde_json::to_vec(meta)?)
        .with_context(|| format!("writing watcher metadata {}", path.display()))
}

fn write_instance_owner(file: &mut File, owner: &InstanceOwner) -> Result<()> {
    file.set_len(0)?;
    file.seek(SeekFrom::Start(0))?;
    serde_json::to_writer(&mut *file, owner)?;
    file.sync_data()?;
    Ok(())
}

fn open_lock_file(path: &Path) -> Result<File> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("creating watcher lock directory {}", parent.display()))?;
    }
    std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
        .with_context(|| format!("opening watcher lock {}", path.display()))
}

fn acquire_instance_lock(repos: &[PathBuf]) -> Result<InstanceLock> {
    let dir = crate::db::path::config_dir().join("watch-locks");
    std::fs::create_dir_all(&dir)
        .with_context(|| format!("creating watch lock dir {}", dir.display()))?;
    let mut canonical_repos = repos
        .iter()
        .map(|repo| {
            std::fs::canonicalize(repo).with_context(|| format!("resolving {}", repo.display()))
        })
        .collect::<Result<Vec<_>>>()?;
    canonical_repos.sort();
    canonical_repos.dedup();

    let pid = std::process::id();
    let generation = format!(
        "{pid}-{}",
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos()
    );
    let owner = InstanceOwner { pid, generation };

    // Acquire each repo in stable order so overlapping sets cannot deadlock.
    let mut repo_files = Vec::with_capacity(canonical_repos.len());
    for repo in &canonical_repos {
        let lock_path = repo_coverage_path(&dir, repo);
        let mut file = open_lock_file(&lock_path)?;
        if !try_lock_file(&file)? {
            bail!(
                "a watcher already owns repository coverage for {} (lock {}); use `varde-code watch --list` and `--stop`",
                repo.display(),
                lock_path.display()
            );
        }
        write_instance_owner(&mut file, &owner)?;
        repo_files.push(file);
    }

    let path = dir.join(format!("{}.lock", watch_set_id(&canonical_repos)));
    let mut set_file = open_lock_file(&path)?;
    if !try_lock_file(&set_file)? {
        bail!("a watcher already owns this repo set ({})", path.display());
    }
    write_instance_owner(&mut set_file, &owner)?;
    let meta_path = meta_path_for(&path);
    let meta = InstanceMeta {
        repos: canonical_repos
            .iter()
            .map(|repo| repo.to_string_lossy().into_owned())
            .collect(),
        owner: owner.clone(),
        ready_repos: Vec::new(),
        stopped: false,
    };
    write_instance_meta(&meta_path, &meta)?;

    Ok(InstanceLock {
        meta_path,
        owner,
        _set_file: set_file,
        _repo_files: repo_files,
    })
}

#[cfg(unix)]
const WATCH_LOCK_EX: i32 = 2;
#[cfg(unix)]
const WATCH_LOCK_NB: i32 = 4;
#[cfg(unix)]
const WATCH_LOCK_UN: i32 = 8;

#[cfg(unix)]
unsafe extern "C" {
    #[link_name = "flock"]
    fn watcher_flock(fd: i32, operation: i32) -> i32;
}

#[cfg(unix)]
fn try_lock_file(file: &File) -> std::io::Result<bool> {
    use std::os::unix::io::AsRawFd;
    // SAFETY: the descriptor is valid for the lifetime of `file`; flock only
    // changes the kernel advisory-lock state for this open file description.
    let result = unsafe { watcher_flock(file.as_raw_fd(), WATCH_LOCK_EX | WATCH_LOCK_NB) };
    if result == 0 {
        Ok(true)
    } else {
        let error = std::io::Error::last_os_error();
        if error.kind() == std::io::ErrorKind::WouldBlock {
            Ok(false)
        } else {
            Err(error)
        }
    }
}

#[cfg(not(unix))]
fn try_lock_file(file: &File) -> std::io::Result<bool> {
    use std::io::Read;
    let mut contents = String::new();
    (&*file).read_to_string(&mut contents)?;
    let pid = serde_json::from_str::<InstanceOwner>(&contents)
        .map(|owner| owner.pid)
        .unwrap_or_default();
    Ok(pid == 0 || !crate::repo_lock::pid_is_alive(pid))
}

fn lock_is_held(path: &Path) -> Result<bool> {
    let file = match std::fs::File::open(path) {
        Ok(file) => file,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(err) => {
            return Err(err)
                .with_context(|| format!("opening read-only lock probe {}", path.display()));
        }
    };
    match try_lock_file(&file)? {
        false => Ok(true),
        true => {
            #[cfg(unix)]
            {
                use std::os::unix::io::AsRawFd;
                // SAFETY: `file` remains open for this unlock call.
                let result = unsafe { watcher_flock(file.as_raw_fd(), WATCH_LOCK_UN) };
                if result != 0 {
                    return Err(std::io::Error::last_os_error()).with_context(|| {
                        format!("releasing watcher status probe lock {}", path.display())
                    });
                }
            }
            Ok(false)
        }
    }
}

/// One running (or recently-running) watcher instance, as reported by
/// `watch --list` — derived from a `<hash>.lock` file plus its `.meta`
/// sidecar (see `write_instance_meta`).
#[derive(Debug, Clone, serde::Serialize)]
pub struct WatchInstance {
    pub pid: u32,
    pub registered: bool,
    pub alive: Option<bool>,
    pub ready: bool,
    pub index_ready: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ownership_error: Option<String>,
    /// Why `registered` could not be confirmed (for example, a sandbox that
    /// denies reading the host service directory); `registered` is then false.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub registration_error: Option<String>,
    pub repos: Vec<String>,
    pub lock_path: String,
    /// Paths that triggered each repo's most recent reconcile — the
    /// drill-down handle for an agent to see what actually changed rather
    /// than only which repo root is being watched. Empty until the first
    /// reconcile after the watcher starts.
    pub changed_paths: Vec<String>,
}

/// List every watcher instance with a lock file under `watch-locks/`,
/// live or stale. Read-only — never reclaims or removes anything; that's
/// `--stop`/`--stop-all`'s job, so `--list` is always safe to run alongside
/// a live watcher.
pub fn list_instances() -> Result<Vec<WatchInstance>> {
    let dir = crate::db::path::config_dir().join("watch-locks");
    let mut instances = Vec::new();
    if dir.exists() {
        for entry in
            std::fs::read_dir(&dir).with_context(|| format!("reading {}", dir.display()))?
        {
            let entry = entry?;
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("lock") {
                continue;
            }
            let contents = std::fs::read_to_string(&path);
            let ownership_error = contents
                .as_ref()
                .err()
                .map(|err| format!("reading watcher owner {}: {err}", path.display()));
            let contents = contents.unwrap_or_default();
            let owner = serde_json::from_str::<InstanceOwner>(&contents).ok();
            let meta_path = meta_path_for(&path);
            let meta_contents = match std::fs::read_to_string(&meta_path) {
                Ok(contents) => Some(contents),
                Err(err) if err.kind() == std::io::ErrorKind::NotFound => None,
                Err(err) => {
                    return Err(err).with_context(|| {
                        format!("reading watcher metadata {}", meta_path.display())
                    });
                }
            };
            let meta = meta_contents
                .as_deref()
                .and_then(|contents| serde_json::from_str::<InstanceMeta>(contents).ok());
            let legacy_value = meta_contents
                .as_deref()
                .and_then(|contents| serde_json::from_str::<serde_json::Value>(contents).ok());
            let repos = meta
                .as_ref()
                .map(|meta| meta.repos.clone())
                .or_else(|| {
                    legacy_value
                        .as_ref()
                        .and_then(|value| value.get("repos").cloned())
                        .and_then(|value| serde_json::from_value::<Vec<String>>(value).ok())
                })
                .unwrap_or_default();
            let pid = owner
                .as_ref()
                .map(|owner| owner.pid)
                .or_else(|| contents.trim().parse::<u32>().ok())
                .unwrap_or_default();
            if repos.is_empty() {
                let held = match lock_is_held(&path) {
                    Ok(held) => held,
                    Err(err) => {
                        bail!(
                            "cannot inspect watcher lock {} to determine its repositories: {err:#}; inspect it on the host before ensuring coverage",
                            path.display()
                        );
                    }
                };
                if held || ownership_error.is_some() {
                    bail!(
                        "cannot determine the repositories for watcher lock {}; inspect it on the host before ensuring coverage",
                        path.display()
                    );
                }
            }
            if pid == 0 && repos.is_empty() {
                continue;
            }
            let (alive, ownership_error) = match (owner.as_ref(), meta.as_ref(), ownership_error) {
                (_, _, Some(error)) => (None, Some(error)),
                (Some(owner), Some(meta), None) => {
                    match instance_owner_is_current(&path, owner, meta) {
                        Ok(alive) => (Some(alive), None),
                        Err(err) => (None, Some(format!("inspecting watcher ownership: {err:#}"))),
                    }
                }
                _ => match lock_is_held(&path) {
                    Ok(false) => (Some(false), None),
                    Ok(true) => (
                        None,
                        Some(format!(
                            "watcher lock {} is held but its owner metadata is unavailable",
                            path.display()
                        )),
                    ),
                    Err(err) => (None, Some(format!("inspecting watcher lock: {err:#}"))),
                },
            };
            let (registered, registration_error) = if repos.len() == 1 {
                registration_status(Path::new(&repos[0]))
            } else {
                (false, None)
            };
            let index_ready =
                !repos.is_empty() && repos.iter().all(|repo| index_ready(Path::new(repo)));
            let ownership_error = ownership_error.or_else(|| {
                (alive.is_none())
                    .then(|| format!("could not confirm watcher ownership for {}", path.display()))
            });
            if alive == Some(false)
                && !registered
                && registration_error.is_none()
                && meta.as_ref().is_some_and(|meta| meta.stopped)
            {
                continue;
            }
            let changed_paths = repos
                .iter()
                .flat_map(|repo| {
                    std::fs::read_to_string(last_changed_path_for(Path::new(repo), &dir))
                        .ok()
                        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
                        .and_then(|v| v.get("changed_paths").cloned())
                        .and_then(|v| serde_json::from_value::<Vec<String>>(v).ok())
                        .unwrap_or_default()
                })
                .collect();
            instances.push(WatchInstance {
                pid,
                registered,
                alive,
                ready: alive == Some(true)
                    && index_ready
                    && meta.as_ref().is_some_and(|meta| {
                        !meta.stopped && repos.iter().all(|repo| meta.ready_repos.contains(repo))
                    }),
                index_ready,
                ownership_error,
                registration_error,
                repos,
                lock_path: path.to_string_lossy().into_owned(),
                changed_paths,
            });
        }
    }
    let registry = crate::db::path::config_dir().join("watch-services");
    if registry.is_dir() {
        for entry in std::fs::read_dir(&registry)? {
            let path = entry?.path();
            let Some(repo) = std::fs::read_to_string(&path)
                .ok()
                .and_then(|s| serde_json::from_str::<String>(&s).ok())
            else {
                continue;
            };
            let (registered, registration_error) = registration_status(Path::new(&repo));
            if !registered && registration_error.is_none() {
                continue;
            }
            if instances.iter().any(|item| item.repos.contains(&repo)) {
                continue;
            }
            instances.push(WatchInstance {
                pid: 0,
                registered,
                alive: Some(false),
                ready: false,
                index_ready: index_ready(Path::new(&repo)),
                ownership_error: None,
                registration_error,
                repos: vec![repo],
                lock_path: String::new(),
                changed_paths: Vec::new(),
            });
        }
    }
    Ok(instances)
}

fn instance_owner_is_current(
    path: &Path,
    owner: &InstanceOwner,
    meta: &InstanceMeta,
) -> Result<bool> {
    if !lock_is_held(path)? {
        return Ok(false);
    }
    let lock_dir = crate::db::path::config_dir().join("watch-locks");
    let mut coverage_locks = Vec::with_capacity(meta.repos.len());
    for repo in &meta.repos {
        coverage_locks.push(lock_is_held(&repo_coverage_path(
            &lock_dir,
            Path::new(repo),
        ))?);
    }
    if coverage_locks.iter().any(|held| !held) {
        bail!(
            "watcher holds only part of its coverage locks for {}",
            path.display()
        );
    }
    if owner != &meta.owner {
        bail!(
            "watcher owner and metadata do not match for {}",
            path.display()
        );
    }
    if !crate::repo_lock::pid_is_alive(owner.pid) {
        bail!("watcher lock is held but pid {} is not alive", owner.pid);
    }
    Ok(true)
}

fn index_ready(repo: &Path) -> bool {
    let path = crate::db::path::repo_db_path(repo);
    let Ok(conn) = crate::db::open_read_only(&path) else {
        return false;
    };
    crate::slice::check_fresh(&conn, &ALL_SLICES, &repo.to_string_lossy(), &Scope::Repo)
        .unwrap_or(false)
}

#[derive(Debug, serde::Serialize)]
pub struct EnsureStatus {
    pub repo: String,
    pub registered: bool,
    pub alive: Option<bool>,
    pub ready: bool,
    pub index_ready: bool,
    pub pid: Option<u32>,
}

#[derive(Debug)]
enum EnsureDecision {
    Return(EnsureStatus),
    Replace,
}

fn ensure_existing(
    item: &WatchInstance,
    repo: &Path,
    inspect_supervisor: impl FnOnce() -> Result<SupervisorState>,
) -> Result<EnsureDecision> {
    let explain = |reason: String| {
        format!(
            "{reason}; inspect or manage this watcher on the host with `varde-code watch --list` and `--stop`"
        )
    };
    let readonly = |alive: Option<bool>, reason: String| -> Result<EnsureDecision> {
        if item.index_ready {
            return Ok(EnsureDecision::Return(EnsureStatus {
                repo: repo.display().to_string(),
                registered: item.registered,
                alive,
                ready: false,
                index_ready: true,
                pid: (alive == Some(true)).then_some(item.pid),
            }));
        }
        bail!(
            "{}; the index is stale or unavailable for {}; search source directly until host-side watcher inspection is restored",
            explain(reason),
            repo.display()
        )
    };

    let Some(alive) = item.alive else {
        return readonly(
            None,
            item.ownership_error.clone().unwrap_or_else(|| {
                format!("could not confirm watcher ownership for {}", repo.display())
            }),
        );
    };
    if let Some(error) = &item.registration_error {
        return readonly(Some(alive), error.clone());
    }
    if !alive || !item.registered {
        return Ok(EnsureDecision::Replace);
    }
    let state = match inspect_supervisor() {
        Ok(state) => state,
        Err(err) => return readonly(Some(true), format!("supervisor inspection failed: {err:#}")),
    };
    if state == SupervisorState::Active && item.ready && item.index_ready {
        return Ok(EnsureDecision::Return(EnsureStatus {
            repo: repo.display().to_string(),
            registered: true,
            alive: Some(true),
            ready: true,
            index_ready: true,
            pid: Some(item.pid),
        }));
    }
    Ok(EnsureDecision::Replace)
}

fn readonly_status_or_error(
    repo: &Path,
    registered: bool,
    alive: Option<bool>,
    pid: Option<u32>,
    index_ready: bool,
    reason: impl std::fmt::Display,
) -> Result<EnsureStatus> {
    if index_ready {
        return Ok(EnsureStatus {
            repo: repo.display().to_string(),
            registered,
            alive,
            ready: false,
            index_ready: true,
            pid,
        });
    }
    bail!(
        "{reason}; the index is stale or unavailable for {}; inspect or manage the watcher on the host with `varde-code watch --list` and `--stop`, then search source directly",
        repo.display()
    )
}

fn ready_instance<'a>(instances: &'a [WatchInstance], repo: &Path) -> Option<&'a WatchInstance> {
    instances.iter().find(|item| {
        item.alive == Some(true)
            && item.ready
            && item.repos.iter().any(|path| Path::new(path) == repo)
    })
}

fn service_name(repo: &Path) -> String {
    format!("varde-code-{}", watch_set_id(&[repo.to_path_buf()]))
}

fn service_path(repo: &Path) -> PathBuf {
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_default();
    #[cfg(target_os = "macos")]
    {
        home.join("Library/LaunchAgents")
            .join(format!("{}.plist", service_name(repo)))
    }
    #[cfg(target_os = "linux")]
    {
        home.join(".config/systemd/user")
            .join(format!("{}.service", service_name(repo)))
    }
    #[cfg(not(any(target_os = "macos", target_os = "linux")))]
    {
        home.join(".config/varde-code/unsupported")
            .join(service_name(repo))
    }
}

fn service_path_is_file(repo: &Path) -> Result<bool> {
    match std::fs::metadata(service_path(repo)) {
        Ok(metadata) => Ok(metadata.is_file()),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(err) => Err(err).with_context(|| {
            format!(
                "inspecting watcher service definition for {}",
                repo.display()
            )
        }),
    }
}

/// Registration for one listed repo. An inspection error is reported with the
/// entry rather than failing the whole listing.
fn registration_status(repo: &Path) -> (bool, Option<String>) {
    match service_path_is_file(repo) {
        Ok(registered) => (registered, None),
        Err(err) => (false, Some(format!("{err:#}"))),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SupervisorState {
    Active,
    Inactive,
}

fn state_from_supervisor_output(
    success: bool,
    stdout: &str,
    stderr: &str,
    command: &str,
    confirmed_inactive: impl Fn(&str) -> bool,
) -> Result<SupervisorState> {
    if success {
        return Ok(SupervisorState::Active);
    }
    let output = format!("{stdout}{stderr}");
    if confirmed_inactive(&output) {
        return Ok(SupervisorState::Inactive);
    }
    bail!(
        "{command} could not inspect watcher service: {}",
        output.trim()
    )
}

fn registration_path(repo: &Path) -> PathBuf {
    crate::db::path::config_dir()
        .join("watch-services")
        .join(format!("{}.json", service_name(repo)))
}

/// Register a user service once, then verify a live process and a fresh
/// initial snapshot. The caller receives an error if host supervision cannot
/// start; source search remains available to the agent.
pub fn ensure(repo: &Path) -> Result<EnsureStatus> {
    let repo = std::fs::canonicalize(repo)?;
    if repo
        .to_string_lossy()
        .chars()
        .any(|c| matches!(c, '\n' | '\r' | '\0'))
    {
        bail!("repository path contains a character unsupported by host service definitions");
    }
    let matching = list_instances()?
        .into_iter()
        .filter(|item| item.repos.iter().any(|r| Path::new(r) == repo))
        .collect::<Vec<_>>();
    let live = matching
        .iter()
        .filter(|item| item.alive == Some(true))
        .collect::<Vec<_>>();
    if live.len() > 1 {
        bail!(
            "multiple live watcher owners claim {}; stop duplicate coverage before ensuring it",
            repo.display()
        );
    }
    if let Some(item) = matching.iter().find(|item| item.alive.is_none()) {
        return match ensure_existing(item, &repo, || inspect_service(&repo))? {
            EnsureDecision::Return(status) => Ok(status),
            EnsureDecision::Replace => unreachable!("unknown ownership is read-only"),
        };
    }
    let mut stopped_existing = false;
    if let Some(item) = live.first() {
        match ensure_existing(item, &repo, || inspect_service(&repo))? {
            EnsureDecision::Return(status) => return Ok(status),
            EnsureDecision::Replace => {}
        }
        {
            let set = item.repos.iter().map(PathBuf::from).collect::<Vec<_>>();
            stop(&set)?;
            wait_for_instance_exit(Path::new(&item.lock_path), Duration::from_secs(10))?;
            for other in set.iter().filter(|other| *other != &repo) {
                ensure(other)?;
            }
            stopped_existing = true;
        }
    }
    // A service definition can survive a failed start or an upgrade from the
    // previous PID-file watcher. Never treat that file as live coverage; if
    // the host still has the job active, stop it through the supervisor and
    // wait for the job itself to disappear before installing the replacement.
    if !stopped_existing {
        let state = match inspect_service(&repo) {
            Ok(state) => state,
            Err(err) => {
                let registered = service_path_is_file(&repo)?;
                return readonly_status_or_error(
                    &repo,
                    registered,
                    Some(false),
                    None,
                    index_ready(&repo),
                    format!("supervisor inspection failed: {err:#}"),
                );
            }
        };
        if state == SupervisorState::Active {
            stop_service(&repo)?;
            wait_for_service_inactive(&repo, Duration::from_secs(10))?;
            cleanup_service_registration(&repo)?;
        }
    }
    let binary = std::env::current_exe().context("locating varde-code executable")?;
    let definition = service_definition(&repo, &binary)?;
    let path = service_path(&repo);
    std::fs::create_dir_all(path.parent().expect("service path parent"))?;
    let current_definition = match std::fs::read_to_string(&path) {
        Ok(contents) => Some(contents),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => None,
        Err(err) => {
            return Err(err)
                .with_context(|| format!("reading service definition {}", path.display()));
        }
    };
    if current_definition.as_deref() != Some(definition.as_str()) {
        std::fs::write(&path, definition).with_context(|| format!("writing {}", path.display()))?;
    }
    let registration = registration_path(&repo);
    std::fs::create_dir_all(registration.parent().expect("registration parent"))?;
    std::fs::write(
        &registration,
        serde_json::to_string(&repo.display().to_string())?,
    )?;
    if let Err(err) = start_service(&repo) {
        match stop_service(&repo) {
            Ok(()) => {
                if let Err(cleanup_err) = cleanup_service_registration(&repo) {
                    eprintln!(
                        "varde-code watch: failed to clean partial registration: {cleanup_err:#}"
                    );
                }
            }
            Err(stop_err) => {
                eprintln!(
                    "varde-code watch: retaining registration because supervisor stop failed: {stop_err:#}"
                );
            }
        }
        return Err(err).context("starting persistent watcher service");
    }
    let deadline = Instant::now() + Duration::from_secs(30);
    loop {
        let instances = list_instances()?;
        if let Some(item) = ready_instance(&instances, &repo) {
            match inspect_service(&repo) {
                Ok(SupervisorState::Active) => {
                    return Ok(EnsureStatus {
                        repo: repo.display().to_string(),
                        registered: true,
                        alive: Some(true),
                        ready: true,
                        index_ready: true,
                        pid: Some(item.pid),
                    });
                }
                Ok(SupervisorState::Inactive) => {}
                Err(err) => {
                    return readonly_status_or_error(
                        &repo,
                        item.registered,
                        Some(true),
                        Some(item.pid),
                        item.index_ready,
                        format!("supervisor inspection failed: {err:#}"),
                    );
                }
            }
        } else if let Some(item) = instances.iter().find(|item| {
            item.alive.is_none() && item.repos.iter().any(|path| Path::new(path) == repo)
        }) {
            return readonly_status_or_error(
                &repo,
                item.registered,
                None,
                None,
                item.index_ready,
                item.ownership_error
                    .as_deref()
                    .unwrap_or("ownership is unknown"),
            );
        } else {
            match inspect_service(&repo) {
                Ok(SupervisorState::Active | SupervisorState::Inactive) => {}
                Err(err) => {
                    return readonly_status_or_error(
                        &repo,
                        true,
                        Some(false),
                        None,
                        index_ready(&repo),
                        format!("supervisor inspection failed: {err:#}"),
                    );
                }
            }
        }
        if Instant::now() >= deadline {
            bail!(
                "watcher registered but did not become ready for {} within 30 seconds; inspect the user service and search source directly",
                repo.display()
            );
        }
        std::thread::sleep(Duration::from_millis(250));
    }
}

fn wait_for_instance_exit(lock_path: &Path, timeout: Duration) -> Result<()> {
    let deadline = Instant::now() + timeout;
    while instance_locks_held(lock_path)? {
        if Instant::now() >= deadline {
            bail!(
                "watcher still owns {} after {} seconds; refusing to start replacement coverage",
                lock_path.display(),
                timeout.as_secs()
            );
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Ok(())
}

fn wait_for_service_inactive(repo: &Path, timeout: Duration) -> Result<()> {
    let deadline = Instant::now() + timeout;
    while inspect_service(repo)? == SupervisorState::Active {
        if Instant::now() >= deadline {
            bail!(
                "supervisor job for {} is still active after {} seconds",
                repo.display(),
                timeout.as_secs()
            );
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Ok(())
}

fn instance_locks_held(lock_path: &Path) -> Result<bool> {
    if lock_is_held(lock_path)? {
        return Ok(true);
    }
    let meta = read_instance_meta(&meta_path_for(lock_path))?;
    for repo in &meta.repos {
        if lock_is_held(&repo_coverage_path(
            &crate::db::path::config_dir().join("watch-locks"),
            Path::new(repo),
        ))? {
            return Ok(true);
        }
    }
    Ok(false)
}

#[cfg(target_os = "linux")]
fn inspect_service(repo: &Path) -> Result<SupervisorState> {
    let unit = format!("{}.service", service_name(repo));
    let output = std::process::Command::new("systemctl")
        .args(["--user", "is-active", &unit])
        .output()
        .context("running systemctl --user is-active")?;
    state_from_supervisor_output(
        output.status.success(),
        &String::from_utf8_lossy(&output.stdout),
        &String::from_utf8_lossy(&output.stderr),
        "systemctl --user is-active",
        |output| {
            systemd_job_is_absent(output)
                || output
                    .lines()
                    .any(|line| matches!(line.trim(), "inactive" | "failed"))
        },
    )
}

#[cfg(target_os = "macos")]
fn inspect_service(repo: &Path) -> Result<SupervisorState> {
    let uid = std::process::Command::new("id")
        .arg("-u")
        .output()
        .context("running id -u")?;
    if !uid.status.success() {
        bail!(
            "id -u failed: {}",
            String::from_utf8_lossy(&uid.stderr).trim()
        );
    }
    let label = format!(
        "gui/{}/{}",
        String::from_utf8_lossy(&uid.stdout).trim(),
        service_name(repo)
    );
    let output = std::process::Command::new("launchctl")
        .args(["print", &label])
        .output()
        .context("running launchctl print")?;
    state_from_supervisor_output(
        output.status.success(),
        &String::from_utf8_lossy(&output.stdout),
        &String::from_utf8_lossy(&output.stderr),
        "launchctl print",
        launchd_job_is_absent,
    )
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn inspect_service(_repo: &Path) -> Result<SupervisorState> {
    bail!("host supervision is unsupported on this platform")
}

#[cfg(target_os = "macos")]
fn service_definition(repo: &Path, binary: &Path) -> Result<String> {
    let escape = |s: &str| {
        s.replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;")
            .replace('"', "&quot;")
    };
    Ok(format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n<plist version=\"1.0\"><dict><key>Label</key><string>{}</string><key>ProgramArguments</key><array><string>{}</string><string>watch</string><string>--repo</string><string>{}</string></array><key>RunAtLoad</key><true/><key>KeepAlive</key><true/></dict></plist>\n",
        escape(&service_name(repo)),
        escape(&binary.display().to_string()),
        escape(&repo.display().to_string())
    ))
}

#[cfg(target_os = "linux")]
fn service_definition(repo: &Path, binary: &Path) -> Result<String> {
    Ok(format!(
        "[Unit]\nDescription=Varde code watcher\n[Service]\nType=simple\nExecStart={} watch --repo {}\nRestart=always\nRestartSec=2\n[Install]\nWantedBy=default.target\n",
        systemd_quote(&binary.display().to_string()),
        systemd_quote(&repo.display().to_string())
    ))
}

#[cfg(any(target_os = "linux", test))]
fn systemd_quote(value: &str) -> String {
    // systemd expands percent specifiers and dollar expressions in ExecStart.
    // Double both before escaping the quoted argument.
    format!(
        "\"{}\"",
        value
            .replace('%', "%%")
            .replace('$', "$$")
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
    )
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn service_definition(_repo: &Path, _binary: &Path) -> Result<String> {
    bail!("host supervision is unsupported on this platform")
}

#[cfg(target_os = "linux")]
fn start_service(repo: &Path) -> Result<()> {
    for args in [
        vec!["--user", "daemon-reload"],
        vec![
            "--user",
            "enable",
            "--now",
            &format!("{}.service", service_name(repo)),
        ],
    ] {
        let result = std::process::Command::new("systemctl")
            .args(args)
            .output()
            .context("running systemctl --user")?;
        if !result.status.success() {
            bail!(
                "systemctl --user failed: {}",
                String::from_utf8_lossy(&result.stderr)
            );
        }
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn start_service(repo: &Path) -> Result<()> {
    let uid = std::process::Command::new("id")
        .arg("-u")
        .output()
        .context("finding user id")?;
    if !uid.status.success() {
        bail!("id -u failed")
    }
    let domain = format!("gui/{}", String::from_utf8_lossy(&uid.stdout).trim());
    let label = format!("{domain}/{}", service_name(repo));
    let path = service_path(repo);
    let boot = std::process::Command::new("launchctl")
        .args(["bootstrap", &domain])
        .arg(&path)
        .output()
        .context("running launchctl bootstrap")?;
    if !boot.status.success() {
        let kick = std::process::Command::new("launchctl")
            .args(["kickstart", "-k", &label])
            .output()
            .context("running launchctl kickstart")?;
        if !kick.status.success() {
            bail!(
                "launchctl bootstrap failed: {}; kickstart failed: {}",
                String::from_utf8_lossy(&boot.stderr),
                String::from_utf8_lossy(&kick.stderr)
            );
        }
    }
    Ok(())
}

/// Outcome of stopping one watcher instance, as reported by `--stop`/`--stop-all`.
#[derive(Debug, Clone, serde::Serialize)]
pub struct StopOutcome {
    pub pid: u32,
    pub repos: Vec<String>,
    /// `true` if a live process was stopped; `false` if coverage was already
    /// absent and only its supervisor registration was removed.
    pub stopped: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Stop the watcher for exactly the given repo set (same `--repo` values a
/// `watch` invocation for it would use). Coverage locks remain stable files;
/// their kernel ownership ends with the watcher process.
pub fn stop(repos: &[PathBuf]) -> Result<StopOutcome> {
    let dir = crate::db::path::config_dir().join("watch-locks");
    let path = dir.join(format!("{}.lock", watch_set_id(repos)));
    let instances = list_instances()?;
    if let Some(instance) = instances
        .iter()
        .into_iter()
        .find(|instance| Path::new(&instance.lock_path) == path)
    {
        return stop_instance(instance);
    }
    if repos.len() == 1 && service_path_is_file(&repos[0])? {
        return unregister_service(&repos[0]);
    }
    if let Ok(meta) = read_instance_meta(&meta_path_for(&path))
        && meta.stopped
    {
        return Ok(StopOutcome {
            pid: meta.owner.pid,
            repos: meta.repos,
            stopped: false,
            error: None,
        });
    }
    bail!(
        "no watcher lock found for this repo set ({})",
        path.display()
    )
}

/// Stop every watcher instance with a lock under `watch-locks/`, regardless
/// of repo set. An individual supervisor failure is recorded in that
/// instance's outcome and does not prevent later instances from being tried.
pub fn stop_all() -> Result<Vec<StopOutcome>> {
    let instances = list_instances()?;
    Ok(stop_all_with(instances, |instance| {
        if instance.lock_path.is_empty() {
            unregister_service(Path::new(&instance.repos[0]))
        } else {
            stop_instance(instance)
        }
    }))
}

fn stop_all_with(
    instances: Vec<WatchInstance>,
    mut stop_one: impl FnMut(&WatchInstance) -> Result<StopOutcome>,
) -> Vec<StopOutcome> {
    instances
        .iter()
        .map(|instance| match stop_one(instance) {
            Ok(outcome) => outcome,
            Err(err) => StopOutcome {
                pid: instance.pid,
                repos: instance.repos.clone(),
                stopped: false,
                error: Some(err.to_string()),
            },
        })
        .collect()
}

fn unregister_service(repo: &Path) -> Result<StopOutcome> {
    stop_service(repo)?;
    cleanup_service_registration(repo)?;
    Ok(StopOutcome {
        pid: 0,
        repos: vec![repo.display().to_string()],
        stopped: false,
        error: None,
    })
}

fn stop_instance(instance: &WatchInstance) -> Result<StopOutcome> {
    if instance.alive.is_none() {
        bail!(
            "cannot stop watcher because ownership is unknown: {}; inspect it on the host before changing registrations",
            instance
                .ownership_error
                .as_deref()
                .unwrap_or("lock probe failed")
        );
    }
    let lock_path = Path::new(&instance.lock_path);
    let meta_path = meta_path_for(lock_path);
    let contents = std::fs::read_to_string(lock_path)
        .with_context(|| format!("reading watcher owner {}", lock_path.display()))?;
    let owner = serde_json::from_str::<InstanceOwner>(&contents)
        .with_context(|| format!("parsing watcher owner {}", lock_path.display()))?;
    let meta = read_instance_meta(&meta_path)?;
    let alive = instance_owner_is_current(lock_path, &owner, &meta)?;
    let repos = instance.repos.clone();
    let pid = owner.pid;

    let registered_repo = if repos.len() == 1 && service_path_is_file(Path::new(&repos[0]))? {
        Some(PathBuf::from(&repos[0]))
    } else {
        None
    };
    let supervisor_state = registered_repo
        .as_ref()
        .map(|repo| inspect_service(repo))
        .transpose()?;
    let supervised = supervisor_state == Some(SupervisorState::Active);
    if let Some(repo) = &registered_repo {
        // An unloaded job is already stopped. Other launchctl/systemd errors
        // remain visible and keep the registration available for retry.
        stop_service(repo)?;
        cleanup_service_registration(repo)?;
    }
    if alive && !supervised {
        crate::repo_lock::terminate(pid)
            .with_context(|| format!("sending SIGTERM to watcher pid {pid}"))?;
    }

    if lock_path.exists() {
        wait_for_instance_exit(lock_path, Duration::from_secs(10))?;
    }
    let mut meta = read_instance_meta(&meta_path)?;
    if owner == meta.owner {
        meta.ready_repos.clear();
        meta.stopped = true;
        write_instance_meta(&meta_path, &meta)?;
    }
    Ok(StopOutcome {
        pid,
        repos,
        stopped: alive,
        error: None,
    })
}

fn cleanup_service_registration(repo: &Path) -> Result<()> {
    for path in [service_path(repo), registration_path(repo)] {
        match std::fs::remove_file(&path) {
            Ok(()) => {}
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
            Err(err) => {
                return Err(err)
                    .with_context(|| format!("removing watcher registration {}", path.display()));
            }
        }
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn stop_service(repo: &Path) -> Result<()> {
    let unit = format!("{}.service", service_name(repo));
    let out = std::process::Command::new("systemctl")
        .args(["--user", "disable", "--now", &unit])
        .output()?;
    if !out.status.success() {
        let output = format!(
            "{}{}",
            String::from_utf8_lossy(&out.stdout),
            String::from_utf8_lossy(&out.stderr)
        );
        if systemd_job_is_absent(&output) {
            return Ok(());
        }
        bail!("systemctl --user disable failed: {}", output.trim());
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn stop_service(repo: &Path) -> Result<()> {
    let uid = std::process::Command::new("id").arg("-u").output()?;
    if !uid.status.success() {
        bail!("id -u failed")
    }
    let label = format!(
        "gui/{}/{}",
        String::from_utf8_lossy(&uid.stdout).trim(),
        service_name(repo)
    );
    let out = std::process::Command::new("launchctl")
        .args(["bootout", &label])
        .output()?;
    if !out.status.success() {
        let output = format!(
            "{}{}",
            String::from_utf8_lossy(&out.stdout),
            String::from_utf8_lossy(&out.stderr)
        );
        if launchd_job_is_absent(&output) {
            return Ok(());
        }
        bail!("launchctl bootout failed: {}", output.trim());
    }
    Ok(())
}

#[cfg(not(any(target_os = "macos", target_os = "linux")))]
fn stop_service(_repo: &Path) -> Result<()> {
    bail!("host supervision is unsupported on this platform")
}

#[cfg(any(target_os = "linux", test))]
fn systemd_job_is_absent(message: &str) -> bool {
    let message = message.to_ascii_lowercase();
    message.contains("not loaded")
        || message.contains("not found")
        || message.contains("does not exist")
}

#[cfg(any(target_os = "macos", test))]
fn launchd_job_is_absent(message: &str) -> bool {
    let message = message.to_ascii_lowercase();
    message.contains("could not find service")
        || message.contains("service not found")
        || message.contains("no such process")
}

/// Deterministic id for a watch set: hash of the sorted, canonicalized repo
/// paths, so the same set of repos always maps to the same lock file
/// regardless of the order they were passed in.
fn watch_set_id(repos: &[PathBuf]) -> String {
    let mut paths: Vec<String> = repos
        .iter()
        .map(|p| p.to_string_lossy().into_owned())
        .collect();
    paths.sort();
    const OFFSET: u64 = 0xcbf29ce484222325;
    const PRIME: u64 = 0x100000001b3;
    let mut hash = OFFSET;
    for byte in paths.join("\n").as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(PRIME);
    }
    format!("{hash:016x}")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(unix)]
    use std::os::unix::fs::PermissionsExt;

    fn registered_test_repo(label: &str) -> (PathBuf, PathBuf, PathBuf) {
        let root = crate::db::path::config_dir().join(label);
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(root.join("main.rs"), "fn watcher_test() {}\n").unwrap();
        let repo = std::fs::canonicalize(root).unwrap();
        let service = service_path(&repo);
        let registration = registration_path(&repo);
        std::fs::create_dir_all(service.parent().unwrap()).unwrap();
        std::fs::create_dir_all(registration.parent().unwrap()).unwrap();
        std::fs::write(&service, "keep service definition").unwrap();
        std::fs::write(
            &registration,
            serde_json::to_string(&repo.display().to_string()).unwrap(),
        )
        .unwrap();
        (repo, service, registration)
    }

    #[cfg(unix)]
    fn supervisor_stub(message: &str, exit_code: i32) -> (PathBuf, PathBuf) {
        let home = PathBuf::from(std::env::var_os("HOME").unwrap());
        let bin = home.join("stub-bin");
        std::fs::create_dir_all(&bin).unwrap();
        let log = home.join("supervisor.log");
        #[cfg(target_os = "linux")]
        let command = "systemctl";
        #[cfg(target_os = "macos")]
        let command = "launchctl";
        #[cfg(not(any(target_os = "linux", target_os = "macos")))]
        let command = "systemctl";
        let script_path = bin.join(command);
        let script = format!(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{}'\nprintf '%s\\n' '{}' >&2\nexit {exit_code}\n",
            log.display(),
            message
        );
        std::fs::write(&script_path, script).unwrap();
        let mut permissions = std::fs::metadata(&script_path).unwrap().permissions();
        permissions.set_mode(0o755);
        std::fs::set_permissions(&script_path, permissions).unwrap();
        (bin, log)
    }

    fn make_owner_unknown(watcher: &InstanceLock) {
        let mut meta = read_instance_meta(&watcher.meta_path).unwrap();
        meta.owner.generation.push_str("-mismatch");
        write_instance_meta(&watcher.meta_path, &meta).unwrap();
    }

    fn recovery_publishes_readiness(debounced: bool) {
        crate::test_support::with_isolated_home("watch-recovery", || {
            let root = crate::db::path::config_dir().join("recovery-repo");
            std::fs::create_dir_all(&root).unwrap();
            let repo = std::fs::canonicalize(&root).unwrap();
            std::fs::write(repo.join("main.py"), "def recovered():\n    return 1\n").unwrap();
            let watcher = acquire_instance_lock(std::slice::from_ref(&repo)).unwrap();
            let owner = watcher.owner.clone();
            let db_path = crate::db::path::repo_db_path(&repo);
            std::fs::create_dir_all(&db_path).unwrap();
            assert!(!reconcile(&repo, &HashSet::new()), "initial failure");

            let recover = || {
                if debounced {
                    let mut pending = HashMap::new();
                    pending.insert(repo.clone(), PendingRepo::new(Instant::now()));
                    reconcile_due(&mut pending, Duration::ZERO, &watcher).unwrap();
                    assert!(pending.is_empty());
                } else {
                    reconcile_and_mark_ready(&repo, &HashSet::new(), &watcher).unwrap();
                }
            };
            recover();
            assert!(
                read_instance_meta(&watcher.meta_path)
                    .unwrap()
                    .ready_repos
                    .is_empty()
            );
            std::fs::remove_dir(&db_path).unwrap();
            recover();
            assert!(index_ready(&repo), "recovery built a fresh index");
            let meta = read_instance_meta(&watcher.meta_path).unwrap();
            assert_eq!(meta.owner, owner, "same watcher generation recovered");
            assert!(
                meta.ready_repos
                    .contains(&repo.to_string_lossy().into_owned()),
                "recovery publishes readiness"
            );
        });
    }

    #[test]
    fn debounced_recovery_publishes_readiness() {
        recovery_publishes_readiness(true);
    }

    #[test]
    fn periodic_recovery_publishes_readiness() {
        recovery_publishes_readiness(false);
    }

    #[test]
    fn list_distinguishes_registration_liveness_and_readiness() {
        crate::test_support::with_isolated_home("watch-status", || {
            let repo =
                std::env::temp_dir().join(format!("varde-watch-status-{}", std::process::id()));
            std::fs::create_dir_all(&repo).unwrap();
            std::fs::write(repo.join("main.py"), "def ready():\n    return 1\n").unwrap();
            let repo = std::fs::canonicalize(repo).unwrap();
            let service = service_path(&repo);
            std::fs::create_dir_all(service.parent().unwrap()).unwrap();
            std::fs::write(&service, "test service definition").unwrap();
            let registration = registration_path(&repo);
            std::fs::create_dir_all(registration.parent().unwrap()).unwrap();
            std::fs::write(
                &registration,
                serde_json::to_string(&repo.display().to_string()).unwrap(),
            )
            .unwrap();
            let dead = list_instances().unwrap();
            assert_eq!(dead.len(), 1);
            assert!(dead[0].registered);
            assert_eq!(dead[0].alive, Some(false));
            assert!(!dead[0].ready);
            assert!(!dead[0].index_ready);

            let watcher = acquire_instance_lock(std::slice::from_ref(&repo)).unwrap();
            let live = list_instances().unwrap();
            assert_eq!(live.len(), 1);
            assert_eq!(live[0].alive, Some(true));
            assert!(!live[0].ready, "live but not yet reconciled");
            assert!(!live[0].index_ready, "freshness is reported independently");

            crate::slice::ensure_fresh(&ALL_SLICES, &repo.to_string_lossy(), &Scope::Repo).unwrap();
            watcher.mark_ready(&repo).unwrap();
            let ready = list_instances().unwrap();
            assert!(ready[0].registered && ready[0].alive == Some(true) && ready[0].ready);
            assert!(ready[0].index_ready);
            std::fs::write(repo.join("main.py"), "def changed():\n    return 345\n").unwrap();
            assert!(!list_instances().unwrap()[0].ready, "lag is observable");
            drop(watcher);
            assert!(
                list_instances()
                    .unwrap()
                    .iter()
                    .all(|item| item.alive == Some(false))
            );
            let _ = std::fs::remove_dir_all(repo);
        });
    }

    #[test]
    fn service_definition_escapes_repo_and_binary_paths() {
        let repo = Path::new(r#"/tmp/repo & 100% "quoted""#);
        let binary = Path::new(r#"/tmp/bin & 100% "quoted""#);
        let definition = service_definition(repo, binary).unwrap();
        #[cfg(target_os = "macos")]
        {
            assert!(definition.contains("&amp;"));
            assert!(definition.contains("&quot;"));
        }
        #[cfg(target_os = "linux")]
        {
            assert!(definition.contains("100%%"));
            assert!(definition.contains("\\\"quoted\\\""));
        }
    }

    #[test]
    fn service_definition_preserves_dollar_expressions_in_repo_paths() {
        let repo = Path::new("/tmp/project-${USER}");
        let argument = systemd_quote(&repo.display().to_string());

        assert!(argument.contains("project-$${USER}"));
    }

    #[test]
    fn watcher_coverage_is_exclusive_per_repo_across_overlapping_sets() {
        crate::test_support::with_isolated_home("watch-overlap", || {
            let root =
                std::env::temp_dir().join(format!("varde-watch-overlap-{}", std::process::id()));
            let repo_a = root.join("a");
            let repo_b = root.join("b");
            std::fs::create_dir_all(&repo_a).unwrap();
            std::fs::create_dir_all(&repo_b).unwrap();
            let repo_a = std::fs::canonicalize(repo_a).unwrap();
            let repo_b = std::fs::canonicalize(repo_b).unwrap();

            let first = acquire_instance_lock(std::slice::from_ref(&repo_a)).unwrap();
            let overlap = acquire_instance_lock(&[repo_b.clone(), repo_a.clone()]);
            assert!(overlap.is_err(), "[A] must exclude [B, A]");

            let set_path = crate::db::path::config_dir()
                .join("watch-locks")
                .join(format!(
                    "{}.lock",
                    watch_set_id(std::slice::from_ref(&repo_a))
                ));
            assert!(
                wait_for_instance_exit(&set_path, Duration::from_millis(10)).is_err(),
                "replacement coverage must wait while the previous process owns its locks"
            );
            let coverage =
                repo_coverage_path(&crate::db::path::config_dir().join("watch-locks"), &repo_a);
            assert!(coverage.is_file(), "stable lock marker remains on disk");
            assert!(lock_is_held(&coverage).unwrap());
            drop(first);
            assert!(!lock_is_held(&coverage).unwrap());
            wait_for_instance_exit(&set_path, Duration::from_millis(100)).unwrap();

            let replacement = acquire_instance_lock(&[repo_b.clone(), repo_a.clone()]).unwrap();
            drop(replacement);

            let barrier = std::sync::Arc::new(std::sync::Barrier::new(3));
            let start = |set: Vec<PathBuf>| {
                let barrier = std::sync::Arc::clone(&barrier);
                std::thread::spawn(move || {
                    barrier.wait();
                    match acquire_instance_lock(&set) {
                        Ok(lock) => {
                            std::thread::sleep(Duration::from_millis(100));
                            drop(lock);
                            true
                        }
                        Err(_) => false,
                    }
                })
            };
            let left = start(vec![repo_a.clone()]);
            let right = start(vec![repo_b, repo_a]);
            barrier.wait();
            let acquired = [left.join().unwrap(), right.join().unwrap()]
                .into_iter()
                .filter(|acquired| *acquired)
                .count();
            assert_eq!(acquired, 1, "concurrent overlapping starts have one owner");
            let _ = std::fs::remove_dir_all(root);
        });
    }

    #[test]
    fn reused_pid_metadata_without_kernel_ownership_cannot_report_ready() {
        crate::test_support::with_isolated_home("watch-reused-pid", || {
            let repo = std::env::temp_dir().join(format!("varde-watch-pid-{}", std::process::id()));
            std::fs::create_dir_all(&repo).unwrap();
            let repo = std::fs::canonicalize(repo).unwrap();
            let lock_dir = crate::db::path::config_dir().join("watch-locks");
            let set_path = lock_dir.join(format!(
                "{}.lock",
                watch_set_id(std::slice::from_ref(&repo))
            ));
            let coverage_path = repo_coverage_path(&lock_dir, &repo);
            let owner = InstanceOwner {
                pid: std::process::id(),
                generation: "stale-generation".into(),
            };
            let stale_meta = InstanceMeta {
                repos: vec![repo.to_string_lossy().into_owned()],
                owner: owner.clone(),
                ready_repos: vec![repo.to_string_lossy().into_owned()],
                stopped: false,
            };
            let mut set_file = open_lock_file(&set_path).unwrap();
            write_instance_owner(&mut set_file, &owner).unwrap();
            let mut coverage_file = open_lock_file(&coverage_path).unwrap();
            write_instance_owner(&mut coverage_file, &owner).unwrap();
            drop((coverage_file, set_file));

            assert!(
                crate::repo_lock::pid_is_alive(owner.pid),
                "the test process demonstrates that PID liveness alone is insufficient"
            );
            assert!(write_instance_meta(&meta_path_for(&set_path), &stale_meta).is_ok());
            assert!(
                !instance_owner_is_current(&set_path, &owner, &stale_meta).unwrap(),
                "a reused live PID without the watcher's kernel locks is stale"
            );
            let _ = std::fs::remove_dir_all(repo);
        });
    }

    #[test]
    fn stop_all_reports_one_failure_and_continues() {
        let instance = |pid, repo: &str| WatchInstance {
            pid,
            registered: false,
            alive: Some(true),
            ready: false,
            index_ready: false,
            ownership_error: None,
            registration_error: None,
            repos: vec![repo.into()],
            lock_path: format!("/locks/{pid}.lock"),
            changed_paths: Vec::new(),
        };
        let calls = std::cell::Cell::new(0);
        let outcomes = stop_all_with(vec![instance(1, "/a"), instance(2, "/b")], |item| {
            calls.set(calls.get() + 1);
            if item.pid == 1 {
                bail!("supervisor permission denied");
            }
            Ok(StopOutcome {
                pid: item.pid,
                repos: item.repos.clone(),
                stopped: true,
                error: None,
            })
        });

        assert_eq!(calls.get(), 2);
        assert_eq!(
            outcomes[0].error.as_deref(),
            Some("supervisor permission denied")
        );
        assert!(outcomes[1].error.is_none());
        assert!(outcomes[1].stopped);
    }

    #[test]
    fn absent_supervisor_jobs_are_distinguished_from_permission_errors() {
        assert!(systemd_job_is_absent("Unit varde-code.service not loaded."));
        assert!(!systemd_job_is_absent(
            "Failed to connect: Operation not permitted"
        ));
        assert!(launchd_job_is_absent(
            "Could not find service \"gui/501/varde-code\""
        ));
        assert!(!launchd_job_is_absent(
            "Boot-out failed: Operation not permitted"
        ));
        assert_eq!(
            state_from_supervisor_output(false, "inactive\n", "", "systemctl", |output| {
                systemd_job_is_absent(output)
                    || output
                        .lines()
                        .any(|line| matches!(line.trim(), "inactive" | "failed"))
            })
            .unwrap(),
            SupervisorState::Inactive
        );
        assert!(
            state_from_supervisor_output(
                false,
                "",
                "Failed to connect: Operation not permitted",
                "systemctl",
                systemd_job_is_absent,
            )
            .unwrap_err()
            .to_string()
            .contains("Operation not permitted")
        );
    }

    #[test]
    fn stale_entry_does_not_mask_new_live_ready_coverage() {
        let repo = Path::new("/tmp/watcher-repo");
        let stale = test_instance(Some(false), true, false);
        let mut live = test_instance(Some(true), true, true);
        live.ready = true;
        live.pid = 456;
        let instances = [stale, live];

        assert_eq!(ready_instance(&instances, repo).unwrap().pid, 456);
    }

    #[cfg(unix)]
    #[test]
    fn ensure_ignores_stale_set_lock_when_new_single_repo_owner_is_ready() {
        crate::test_support::with_isolated_home("watch-stale-set-new-owner", || {
            let (repo, _service, _registration) = registered_test_repo("stale-set-target");
            let other = crate::db::path::config_dir().join("stale-set-other");
            std::fs::create_dir_all(&other).unwrap();
            let other = std::fs::canonicalize(other).unwrap();
            let old = acquire_instance_lock(&[repo.clone(), other]).unwrap();
            let old_lock_path = old.meta_path.with_extension("lock");
            drop(old);

            let mut old_meta = read_instance_meta(&meta_path_for(&old_lock_path)).unwrap();
            old_meta.stopped = false;
            write_instance_meta(&meta_path_for(&old_lock_path), &old_meta).unwrap();

            let current = acquire_instance_lock(std::slice::from_ref(&repo)).unwrap();
            crate::slice::ensure_fresh(&ALL_SLICES, &repo.to_string_lossy(), &Scope::Repo).unwrap();
            current.mark_ready(&repo).unwrap();
            let (bin, _log) = supervisor_stub("active", 0);
            let _path = crate::test_support::PathOverride::new(&bin);

            let instances = list_instances().unwrap();
            let stale = instances
                .iter()
                .find(|item| Path::new(&item.lock_path) == old_lock_path)
                .unwrap();
            assert_eq!(stale.alive, Some(false));
            let ready = ready_instance(&instances, &repo).unwrap();
            assert_eq!(
                ready.lock_path,
                current.meta_path.with_extension("lock").to_string_lossy()
            );

            let status = ensure(&repo).unwrap();

            assert_eq!(status.alive, Some(true));
            assert!(status.ready);
            assert!(status.index_ready);
        });
    }

    #[cfg(unix)]
    #[test]
    fn ensure_unknown_owner_with_fresh_index_does_not_touch_host_state() {
        crate::test_support::with_isolated_home("watch-ensure-unknown-fresh", || {
            let (repo, service, registration) = registered_test_repo("ensure-unknown-fresh");
            let watcher = acquire_instance_lock(std::slice::from_ref(&repo)).unwrap();
            crate::slice::ensure_fresh(&ALL_SLICES, &repo.to_string_lossy(), &Scope::Repo).unwrap();
            watcher.mark_ready(&repo).unwrap();
            make_owner_unknown(&watcher);
            let (bin, log) = supervisor_stub("Operation not permitted", 1);
            let _path = crate::test_support::PathOverride::new(&bin);
            let before = (
                std::fs::read(&service).unwrap(),
                std::fs::read(&registration).unwrap(),
                std::fs::read(&watcher.meta_path).unwrap(),
                std::fs::read(watcher.meta_path.with_extension("lock")).unwrap(),
            );

            let status = ensure(&repo).unwrap();

            assert_eq!(status.alive, None);
            assert!(!status.ready);
            assert!(status.index_ready);
            assert_eq!(
                before,
                (
                    std::fs::read(&service).unwrap(),
                    std::fs::read(&registration).unwrap(),
                    std::fs::read(&watcher.meta_path).unwrap(),
                    std::fs::read(watcher.meta_path.with_extension("lock")).unwrap(),
                )
            );
            assert!(
                !log.exists(),
                "unknown ownership must not inspect or mutate the host service"
            );
        });
    }

    #[cfg(unix)]
    #[test]
    fn ensure_unknown_owner_with_stale_index_stops_before_host_inspection() {
        crate::test_support::with_isolated_home("watch-ensure-unknown-stale", || {
            let (repo, service, registration) = registered_test_repo("ensure-unknown-stale");
            let watcher = acquire_instance_lock(std::slice::from_ref(&repo)).unwrap();
            make_owner_unknown(&watcher);
            let (bin, log) = supervisor_stub("Operation not permitted", 1);
            let _path = crate::test_support::PathOverride::new(&bin);
            let before = (
                std::fs::read(&service).unwrap(),
                std::fs::read(&registration).unwrap(),
            );

            let error = ensure(&repo).unwrap_err().to_string();

            assert!(error.contains("stale"));
            assert!(error.contains("host"));
            assert_eq!(
                before,
                (
                    std::fs::read(&service).unwrap(),
                    std::fs::read(&registration).unwrap()
                )
            );
            assert!(!log.exists());
        });
    }

    #[cfg(unix)]
    #[test]
    fn ensure_unresolved_locked_set_errors_before_host_inspection() {
        crate::test_support::with_isolated_home("watch-ensure-unresolved", || {
            let (repo, service, registration) = registered_test_repo("ensure-unresolved");
            let lock_dir = crate::db::path::config_dir().join("watch-locks");
            let orphan = open_lock_file(&lock_dir.join("unknown-set.lock")).unwrap();
            assert!(try_lock_file(&orphan).unwrap());
            let (bin, log) = supervisor_stub("Operation not permitted", 1);
            let _path = crate::test_support::PathOverride::new(&bin);
            let before = (
                std::fs::read(&service).unwrap(),
                std::fs::read(&registration).unwrap(),
            );

            let error = ensure(&repo).unwrap_err().to_string();

            assert!(error.contains("determine the repositories"));
            assert!(error.contains("host"));
            assert_eq!(
                before,
                (
                    std::fs::read(&service).unwrap(),
                    std::fs::read(&registration).unwrap()
                )
            );
            assert!(!log.exists());
            drop(orphan);
        });
    }

    #[cfg(unix)]
    #[test]
    fn ensure_supervisor_denial_keeps_fresh_index_and_registration_read_only() {
        crate::test_support::with_isolated_home("watch-ensure-supervisor-denied", || {
            let (repo, service, registration) = registered_test_repo("ensure-supervisor-denied");
            let watcher = acquire_instance_lock(std::slice::from_ref(&repo)).unwrap();
            crate::slice::ensure_fresh(&ALL_SLICES, &repo.to_string_lossy(), &Scope::Repo).unwrap();
            watcher.mark_ready(&repo).unwrap();
            let (bin, log) = supervisor_stub("Operation not permitted", 1);
            let _path = crate::test_support::PathOverride::new(&bin);
            let before = (
                std::fs::read(&service).unwrap(),
                std::fs::read(&registration).unwrap(),
                std::fs::read(&watcher.meta_path).unwrap(),
                std::fs::read(watcher.meta_path.with_extension("lock")).unwrap(),
            );

            let status = ensure(&repo).unwrap();

            assert_eq!(status.alive, Some(true));
            assert!(!status.ready);
            assert!(status.index_ready);
            let calls = std::fs::read_to_string(&log).unwrap();
            assert!(calls.contains("is-active") || calls.contains("print"));
            assert!(!calls.contains("disable"));
            assert!(!calls.contains("bootout"));
            assert_eq!(
                before,
                (
                    std::fs::read(&service).unwrap(),
                    std::fs::read(&registration).unwrap(),
                    std::fs::read(&watcher.meta_path).unwrap(),
                    std::fs::read(watcher.meta_path.with_extension("lock")).unwrap(),
                )
            );
        });
    }

    #[test]
    fn ownership_probe_errors_are_not_reported_as_stopped() {
        crate::test_support::with_isolated_home("watch-unknown-owner", || {
            let repo = PathBuf::from("/tmp/watch-unknown-owner");
            let lock_path = crate::db::path::config_dir().join("watch-locks/unknown.lock");
            let service = service_path(&repo);
            let registration = registration_path(&repo);
            std::fs::create_dir_all(service.parent().unwrap()).unwrap();
            std::fs::create_dir_all(registration.parent().unwrap()).unwrap();
            std::fs::write(&service, "service definition").unwrap();
            std::fs::write(&registration, "registered").unwrap();
            let instance = WatchInstance {
                pid: std::process::id(),
                registered: true,
                alive: None,
                ready: false,
                index_ready: true,
                ownership_error: Some("permission denied".into()),
                registration_error: None,
                repos: vec![repo.to_string_lossy().into_owned()],
                lock_path: lock_path.to_string_lossy().into_owned(),
                changed_paths: Vec::new(),
            };

            assert!(stop_instance(&instance).is_err());
            assert!(
                service.exists(),
                "denied ownership must not unregister the host job"
            );
            assert!(
                registration.exists(),
                "denied ownership must not clean registration"
            );
        });
    }

    /// Makes the isolated home's host service directory unreadable, runs
    /// `list_instances`, then restores access so the home can be cleaned up.
    #[cfg(unix)]
    fn list_with_unreadable_service_dir(repo: &Path) -> Result<Vec<WatchInstance>> {
        let service_dir = service_path(repo).parent().unwrap().to_path_buf();
        std::fs::create_dir_all(&service_dir).unwrap();
        std::fs::set_permissions(&service_dir, std::fs::Permissions::from_mode(0o000)).unwrap();
        let listed = list_instances();
        std::fs::set_permissions(&service_dir, std::fs::Permissions::from_mode(0o755)).unwrap();
        listed
    }

    #[cfg(unix)]
    #[test]
    fn list_reports_unreadable_registration_for_lock_entry() {
        crate::test_support::with_isolated_home("watch-unreadable-lock", || {
            let root = crate::db::path::config_dir().join("unreadable-lock-repo");
            std::fs::create_dir_all(&root).unwrap();
            let repo = std::fs::canonicalize(root).unwrap();
            let watcher = acquire_instance_lock(std::slice::from_ref(&repo)).unwrap();

            let listed = list_with_unreadable_service_dir(&repo).unwrap();
            assert_eq!(listed.len(), 1);
            assert!(!listed[0].registered);
            assert!(listed[0].registration_error.is_some());
            assert_eq!(listed[0].alive, Some(true));
            drop(watcher);
        });
    }

    #[cfg(unix)]
    #[test]
    fn list_reports_unreadable_registration_for_registry_entry() {
        crate::test_support::with_isolated_home("watch-unreadable-registry", || {
            let repo = PathBuf::from("/tmp/watch-unreadable-registry");
            let registration = registration_path(&repo);
            std::fs::create_dir_all(registration.parent().unwrap()).unwrap();
            std::fs::write(
                &registration,
                serde_json::to_string(&repo.display().to_string()).unwrap(),
            )
            .unwrap();

            let listed = list_with_unreadable_service_dir(&repo).unwrap();
            assert_eq!(listed.len(), 1);
            assert!(!listed[0].registered);
            assert!(listed[0].registration_error.is_some());
            assert_eq!(listed[0].repos, vec![repo.display().to_string()]);
        });
    }

    #[test]
    fn ensure_never_replaces_live_watcher_with_unknown_registration() {
        let mut item = test_instance(Some(true), false, true);
        item.registration_error = Some("permission denied".into());

        let decision = ensure_existing(&item, Path::new("/tmp/watcher-repo"), || {
            panic!("unknown registration must not reach supervisor inspection")
        })
        .unwrap();
        let EnsureDecision::Return(status) = decision else {
            panic!("unknown registration must not replace a live watcher");
        };
        assert_eq!(status.alive, Some(true));
        assert!(!status.ready);
    }

    fn test_instance(alive: Option<bool>, registered: bool, index_ready: bool) -> WatchInstance {
        WatchInstance {
            pid: 123,
            registered,
            alive,
            ready: false,
            index_ready,
            ownership_error: alive.is_none().then(|| "permission denied".into()),
            registration_error: None,
            repos: vec!["/tmp/watcher-repo".into()],
            lock_path: "/tmp/watcher.lock".into(),
            changed_paths: Vec::new(),
        }
    }

    #[test]
    fn failed_registration_cleanup_removes_definition_and_registry() {
        crate::test_support::with_isolated_home("watch-registration-cleanup", || {
            let repo =
                std::env::temp_dir().join(format!("varde-watch-cleanup-{}", std::process::id()));
            std::fs::create_dir_all(&repo).unwrap();
            let repo = std::fs::canonicalize(repo).unwrap();
            let definition = service_path(&repo);
            let registration = registration_path(&repo);
            std::fs::create_dir_all(definition.parent().unwrap()).unwrap();
            std::fs::create_dir_all(registration.parent().unwrap()).unwrap();
            std::fs::write(&definition, "service definition").unwrap();
            std::fs::write(&registration, "registered").unwrap();

            cleanup_service_registration(&repo).unwrap();

            assert!(!definition.exists());
            assert!(!registration.exists());
            let _ = std::fs::remove_dir_all(repo);
        });
    }

    #[test]
    fn resolve_repos_dedupes_explicit_and_config() {
        let dir = std::env::temp_dir().join(format!("varde-watch-test-{}", std::process::id()));
        let repo = dir.join("repo");
        std::fs::create_dir_all(repo.join(".git")).unwrap();

        let config = WatchConfig {
            repos: vec![repo.to_string_lossy().into_owned()],
            parent_dirs: vec![],
        };
        let repos = resolve_repos(&[repo.to_string_lossy().into_owned()], Some(&config)).unwrap();
        assert_eq!(repos.len(), 1);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn resolve_repos_discovers_under_parent_dir() {
        let dir = std::env::temp_dir().join(format!("varde-watch-test2-{}", std::process::id()));
        let repo_a = dir.join("a");
        let repo_b = dir.join("b");
        let not_a_repo = dir.join("c");
        std::fs::create_dir_all(repo_a.join(".git")).unwrap();
        std::fs::create_dir_all(repo_b.join(".git")).unwrap();
        std::fs::create_dir_all(&not_a_repo).unwrap();

        let config = WatchConfig {
            repos: vec![],
            parent_dirs: vec![dir.to_string_lossy().into_owned()],
        };
        let mut repos = resolve_repos(&[], Some(&config)).unwrap();
        repos.sort();
        assert_eq!(repos.len(), 2);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn resolve_repos_rejects_non_git_explicit_path() {
        let dir = std::env::temp_dir().join(format!("varde-watch-test3-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let result = resolve_repos(&[dir.to_string_lossy().into_owned()], None);
        assert!(result.is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn resolve_repos_errors_when_nothing_configured() {
        let result = resolve_repos(&[], None);
        assert!(result.is_err());
    }

    #[test]
    fn pending_events_coalesce_wakeups_and_bound_diagnostic_paths() {
        let (wake, wake_rx) = sync_channel(EVENT_SIGNAL_CAPACITY);
        let events = PendingEvents::new(wake);
        let repo = PathBuf::from("/repo");

        for index in 0..(MAX_DIAGNOSTIC_PATHS + 100) {
            let path = PathBuf::from(format!("/repo/file-{index}.rs"));
            assert!(events.push(&repo, &path));
        }

        let repos = events.repos.lock().unwrap();
        let state = repos.get(&repo).expect("repo remains dirty");
        assert_eq!(repos.len(), 1, "events coalesce by repository");
        assert_eq!(
            state.changed_paths.len(),
            MAX_DIAGNOSTIC_PATHS,
            "diagnostic paths stay bounded"
        );
        drop(repos);

        assert!(wake_rx.try_recv().is_ok(), "one wakeup is retained");
        assert!(
            wake_rx.try_recv().is_err(),
            "duplicate wakeups are coalesced"
        );
    }

    #[test]
    fn pending_repo_reconciles_after_maximum_batch_age() {
        let now = Instant::now();
        let state = PendingRepo {
            first_event: now - MAX_RECONCILE_DELAY,
            last_event: now,
            changed_paths: HashSet::new(),
        };

        assert!(
            state.is_due_at(now, Duration::from_secs(60)),
            "continuous activity cannot postpone reconciliation forever"
        );

        let mut pending = HashMap::new();
        pending.insert(PathBuf::from("/repo"), state);
        assert_eq!(
            next_wait_at(&pending, Duration::from_secs(60), now),
            Duration::from_millis(1),
            "the loop wakes at the maximum batch age"
        );
    }

    #[test]
    fn run_guarded_contains_a_panicking_reconcile() {
        // A panic in one repo's reconcile must be caught so the watch loop
        // survives to serve every other repo. (The default panic hook still
        // prints the panic to stderr — expected; what matters is that control
        // returns here instead of unwinding out of the loop.)
        assert!(run_guarded(Path::new("/nonexistent-repo"), || panic!("boom")).is_none());

        // A non-panicking task still runs to completion through the guard.
        let ran = std::cell::Cell::new(false);
        assert_eq!(
            run_guarded(Path::new("/nonexistent-repo"), || ran.set(true)),
            Some(())
        );
        assert!(ran.get(), "non-panicking task runs under the guard");
    }

    #[test]
    fn reconcile_refreshes_index_after_file_change() {
        // End-to-end smoke test for the watch action: a file change followed by
        // a reconcile must land in the on-disk index.
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock is after epoch")
            .as_nanos();
        let home =
            std::env::temp_dir().join(format!("varde-watch-home-{}-{stamp}", std::process::id()));
        let _ = std::fs::remove_dir_all(&home);
        std::fs::create_dir_all(&home).expect("home creates");
        let _home_override = crate::test_support::HomeOverride::new(&home);

        let root =
            std::env::temp_dir().join(format!("varde-watch-repo-{}-{stamp}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).expect("repo creates");
        std::fs::write(root.join("a.rs"), "fn alpha() {}\n").expect("a.rs writes");
        let root_s = root.to_str().expect("root is utf-8");

        // Initial build establishes the index.
        crate::build::run_with_force(root_s, false).expect("initial build succeeds");

        // Add a function, then reconcile the repo exactly as the watch loop does.
        std::fs::write(root.join("a.rs"), "fn alpha() {}\nfn beta() {}\n")
            .expect("a.rs edit writes");
        reconcile(&root, &HashSet::new());

        // The freshly-added entity must now be present in the index.
        let db_path = crate::db::path::repo_db_path(&root);
        let conn = crate::db::open(&db_path).expect("db opens");
        let beta: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM entities WHERE name = 'beta'",
                [],
                |r| r.get(0),
            )
            .expect("count query runs");
        assert!(beta >= 1, "reconcile picked up the newly added function");
        drop(conn);

        let _ = std::fs::remove_dir_all(&home);
        let _ = std::fs::remove_dir_all(&root);
    }
}
