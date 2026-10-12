//! Store one short progress line per plan outside the plan artifacts, and run
//! the `plan watch` loop that reads those lines back.

use crate::cli::{NowArgs, WatchArgs};
use crate::commands::error::{InternalError, report_error};
use crate::commands::watch::{self, Event};
use crate::commands::watch_cache::{self, WatchCache};
use crate::commands::{status, watch_block, watch_state};
use crate::output::print_success;
use anyhow::{Context, Result, anyhow, bail};
use fs4::FileExt;
use serde_json::json;
use std::ffi::OsStr;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use varde_workflow_core::memory::MemoryPaths;

const MAX_LINE_CHARS: usize = 200;

pub fn run(args: NowArgs) -> Result<()> {
    let json = args.json;
    match run_inner(args) {
        Ok(()) => Ok(()),
        Err(error) => report_error(&InternalError(error.to_string()), json),
    }
}

fn run_inner(args: NowArgs) -> Result<()> {
    let provided = [args.clear, args.text.is_some(), args.waiting.is_some()];
    if provided.into_iter().filter(|given| *given).count() != 1 {
        bail!("provide exactly one of TEXT, --waiting, or --clear");
    }
    let cwd = std::env::current_dir().context("could not resolve current directory")?;
    let working = MemoryPaths::resolve(&cwd)?.working.path;
    let plans_dir = working.join("plans");
    let plan_path = resolve_plan(&args.plan, &cwd, &plans_dir)?;
    if let Some(notice) = status::staleness_notice_for(&plan_path, args.repo.as_deref()) {
        eprintln!("{notice}");
    }
    let key = plan_key(&plans_dir, &plan_path)?;
    let id = read_plan_id(&plan_path)?;
    let now_path = working.join("plan-now").join(format!("{key}.txt"));

    if args.clear {
        match fs::remove_file(&now_path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => {
                return Err(error)
                    .with_context(|| format!("could not clear {}", now_path.display()));
            }
        }
        if args.json {
            print_success(json!({"plan": id, "cleared": true}))
        } else {
            println!("Cleared now line for {id}.");
            Ok(())
        }
    } else {
        let line = match args.waiting.as_deref() {
            Some(reason) => {
                let reason = normalize_line(reason);
                if reason.is_empty() {
                    bail!("--waiting must contain non-whitespace text");
                }
                normalize_line(&format!("waiting: {reason}"))
            }
            None => normalize_line(args.text.as_deref().unwrap_or_default()),
        };
        if line.is_empty() {
            bail!("TEXT must contain non-whitespace text");
        }
        write_line(&now_path, &line)?;
        if args.json {
            print_success(json!({"plan": id, "now": line}))
        } else {
            println!("Set now line for {id}.");
            Ok(())
        }
    }
}

fn watch_memory_paths(cwd: &Path) -> Result<MemoryPaths> {
    match MemoryPaths::resolve(cwd) {
        Ok(paths) => Ok(paths),
        Err(error) => {
            eprintln!(
                "varde plan watch: could not load memory path config ({error}); using built-in paths"
            );
            MemoryPaths::resolve_with(cwd, &Default::default()).map_err(Into::into)
        }
    }
}

pub fn run_watch(args: WatchArgs) -> Result<()> {
    let json = args.json;
    match watch_inner(args) {
        Ok(()) => Ok(()),
        Err(error) => report_error(&InternalError(error.to_string()), json),
    }
}

fn watch_inner(args: WatchArgs) -> Result<()> {
    let cwd = std::env::current_dir().context("could not resolve current directory")?;
    let working = watch_memory_paths(&cwd)?.working.path;
    let repo = args.repo.clone().unwrap_or(cwd);
    let threshold = match args.stale {
        Some(seconds) => seconds,
        None => {
            let (minutes, notice) = status::load_stall_minutes();
            if let Some(reason) = notice {
                eprintln!(
                    "varde plan watch: orchestration stall_minutes ignored ({reason}); using {minutes}"
                );
            }
            minutes * 60
        }
    };
    let notes = args.notes.as_deref();
    let lock_path = watch_cache::cache_path_for_repo(&working, notes, &repo).with_extension("lock");
    if let Some(parent) = lock_path.parent() {
        fs::create_dir_all(parent).with_context(|| {
            format!(
                "could not create watch cache directory {}",
                parent.display()
            )
        })?;
    }
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .open(&lock_path)
        .with_context(|| format!("could not open watcher lock {}", lock_path.display()))?;
    match FileExt::try_lock(&lock) {
        Ok(()) => {}
        Err(fs4::TryLockError::WouldBlock) => {
            bail!("another varde plan watch is already running for this cache");
        }
        Err(error) => return Err(anyhow!(error)).context("could not lock plan watch cache"),
    }
    let mut cache = if args.no_inbox && args.once {
        None
    } else {
        Some(watch_cache::read_for_repo(&working, notes, &repo).unwrap_or_else(WatchCache::new))
    };
    let mut wake = if args.no_wake {
        None
    } else {
        Some(
            crate::commands::wake::WakeRunner::load().unwrap_or_else(|error| {
                eprintln!("varde plan watch: {error:#}; wake disabled for this run");
                crate::commands::wake::WakeRunner::empty()
            }),
        )
    };
    loop {
        let plans = watch::scan(&working, &repo, SystemTime::now(), threshold);
        let events = match cache.as_mut() {
            None => watch::events_for(&plans),
            Some(cache) => {
                let (events, next) = watch::diff(cache, &plans);
                *cache = next;
                events
            }
        };
        if !args.no_inbox {
            for event in &events {
                let kind = match event.kind {
                    watch::EventKind::Stale => "stale",
                    watch::EventKind::Blocked => "blocked",
                    watch::EventKind::NeedsDecision => "needs-user",
                    watch::EventKind::MergeReady => "merge-ready",
                    watch::EventKind::Finished => "done",
                };
                if let Err(error) = crate::commands::msg::append_event_message(
                    &working,
                    "varde-watch",
                    "main",
                    kind,
                    &event.line(),
                    None,
                ) {
                    eprintln!("varde plan watch: could not append event to inbox: {error:#}");
                }
            }
        }
        print_events(&events, args.json)?;
        if let Some(wake) = wake.as_mut() {
            for event in &events {
                if let Some(message) = wake.run(event)? {
                    if args.no_inbox {
                        eprintln!("varde plan watch: {message}");
                    } else if let Err(error) = crate::commands::msg::append_event_message(
                        &working,
                        "varde-watch",
                        "main",
                        "info",
                        &message,
                        None,
                    ) {
                        eprintln!(
                            "varde plan watch: could not append wake result to inbox: {error:#}"
                        );
                    }
                }
            }
        }
        if let Some(path) = notes
            && let Err(error) = watch_block::write_block(path, &watch_state::model(&plans))
        {
            eprintln!("varde plan watch: {error:#}");
        }
        // A broken pipe exits before wake or checkpoint; the next run replays
        // the inbox event and retries wake.
        if let Some(cache) = cache.as_ref() {
            // Test seam: simulate a crash after delivery but before checkpoint
            // persistence so the next run can verify at-least-once replay.
            if std::env::var_os("VARDE_WATCH_FAIL_BEFORE_CACHE_SAVE").is_some() {
                bail!("injected failure before watch cache save");
            }
            if let Err(error) =
                watch_cache::write_if_changed_for_repo(&working, notes, &repo, cache)
            {
                eprintln!("varde plan watch: {error:#}");
            }
        }
        if args.once {
            return Ok(());
        }
        std::thread::sleep(Duration::from_secs(args.interval));
    }
}

fn print_events(events: &[Event], json: bool) -> Result<()> {
    let mut stdout = std::io::stdout().lock();
    for event in events {
        if json {
            writeln!(stdout, "{}", serde_json::to_string(event)?)?;
        } else {
            writeln!(stdout, "{}", event.line())?;
        }
    }
    stdout.flush()?;
    Ok(())
}

fn resolve_plan(argument: &Path, cwd: &Path, plans_dir: &Path) -> Result<PathBuf> {
    if argument.file_name() == Some(OsStr::new("plan.md")) {
        let path = if argument.is_absolute() {
            argument.to_path_buf()
        } else {
            cwd.join(argument)
        };
        let plans_root = fs::canonicalize(plans_dir)
            .with_context(|| format!("could not read plans tree {}", plans_dir.display()))?;
        let canonical_plan = fs::canonicalize(&path)
            .with_context(|| format!("could not read plan {}", path.display()))?;
        if !canonical_plan.starts_with(&plans_root) {
            bail!("plan path must be inside {}", plans_dir.display());
        }
        read_plan_id(&path)?;
        return Ok(path);
    }

    let wanted = argument.to_string_lossy();
    let mut paths = Vec::new();
    let mut skipped = 0;
    if plans_dir.is_dir() {
        status::collect_plan_paths(plans_dir, &mut paths, &mut skipped);
    }
    let mut matches = Vec::new();
    for path in paths {
        let Ok(id) = read_plan_id(&path) else {
            continue;
        };
        let directory_name = path
            .parent()
            .and_then(Path::file_name)
            .and_then(OsStr::to_str);
        if directory_name == Some(wanted.as_ref()) || id == wanted {
            matches.push(path);
        }
    }
    match matches.len() {
        0 => Err(anyhow!("unknown plan `{}`", argument.display())),
        1 => Ok(matches.remove(0)),
        _ => Err(anyhow!(
            "plan id `{}` is ambiguous; pass a plan.md path",
            argument.display()
        )),
    }
}

fn read_plan_id(path: &Path) -> Result<String> {
    let bytes =
        fs::read(path).with_context(|| format!("could not read plan {}", path.display()))?;
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(&bytes)
        .with_context(|| format!("could not parse plan {}", path.display()))?;
    let mapping = frontmatter
        .as_mapping()
        .ok_or_else(|| anyhow!("plan {} has invalid frontmatter", path.display()))?;
    if status::artifact_type(mapping) != "plan" {
        bail!("{} is not a plan", path.display());
    }
    Ok(status::artifact_id(path, mapping))
}

fn plan_key(plans_dir: &Path, plan_path: &Path) -> Result<String> {
    let directory = plan_path
        .parent()
        .ok_or_else(|| anyhow!("plan path has no directory"))?;
    let plans_root = fs::canonicalize(plans_dir)
        .with_context(|| format!("could not read plans tree {}", plans_dir.display()))?;
    let directory = fs::canonicalize(directory)
        .with_context(|| format!("could not read plan directory {}", directory.display()))?;
    let relative = directory
        .strip_prefix(&plans_root)
        .map_err(|_| anyhow!("plan path must be inside {}", plans_dir.display()))?;
    let mut components = Vec::new();
    for component in relative.components() {
        let Component::Normal(component) = component else {
            bail!("plan path contains an unsafe key component");
        };
        let component = component
            .to_str()
            .ok_or_else(|| anyhow!("plan path contains a non-UTF-8 key component"))?;
        if component.is_empty()
            || component == "."
            || component == ".."
            || !component
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
        {
            bail!("plan path contains an unsafe key component `{component}`");
        }
        // Reserve `__` for separating path components.
        components.push(component.replace('_', "_u"));
    }
    if components.is_empty() {
        bail!("plan path has an empty key");
    }
    Ok(components.join("__"))
}

fn normalize_line(value: &str) -> String {
    value
        .split(|character: char| character.is_whitespace() || character.is_control())
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(MAX_LINE_CHARS)
        .collect()
}

fn write_line(path: &Path, line: &str) -> Result<()> {
    let parent = path.parent().context("now path has no parent")?;
    fs::create_dir_all(parent)
        .with_context(|| format!("could not create now store {}", parent.display()))?;
    let filename = path
        .file_name()
        .and_then(OsStr::to_str)
        .context("now path has an invalid filename")?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let temporary = parent.join(format!(".{filename}.{}.{}.tmp", std::process::id(), nonce));
    let result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(line.as_bytes())?;
        file.write_all(b"\n")?;
        file.sync_all()?;
        fs::rename(&temporary, path)
    })();
    if let Err(error) = result {
        let _ = fs::remove_file(&temporary);
        return Err(error)
            .with_context(|| format!("could not store now line at {}", path.display()));
    }
    Ok(())
}

pub(super) fn read_line(plans_dir: &Path, plan_path: &Path) -> Option<String> {
    let working = plans_dir.parent()?;
    let key = plan_key(plans_dir, plan_path).ok()?;
    let path = working.join("plan-now").join(format!("{key}.txt"));
    let value = fs::read_to_string(path).ok()?;
    let line = value.lines().next()?.trim();
    (!line.is_empty()).then(|| line.to_string())
}
