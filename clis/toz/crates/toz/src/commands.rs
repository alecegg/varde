use crate::cli::*;
use crate::diagnostics;
use crate::sandbox;
use crate::worker;
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use std::io::{Read, Write};
use toz_core::capture::{self, CaptureInput, Outcome};
use toz_core::config::WorkspaceAccess;
use toz_core::fetch::{self, FetchOpts};
use toz_core::index;
use toz_core::profile;
use toz_core::search::{self, QueryResult, SearchOpts};
use toz_core::{Config, Project, Store};

pub fn dispatch(cli: Cli) -> Result<i32> {
    if let Some(dir) = &cli.global.fallback_dir {
        if toz_core::config::env_os("TOZ_FALLBACK_DIR").is_none() {
            std::env::set_var("TOZ_FALLBACK_DIR", dir);
        }
    }
    if let Command::Event(a) = &cli.cmd {
        diagnostics::record(&a.harness, &a.outcome, &a.reason, &a.tool, a.bytes)?;
        return Ok(0);
    }
    if let Command::Note(a) = &cli.cmd {
        return cmd_note(NoteArgs {
            harness: a.harness.clone(),
        });
    }
    let command = cli.cmd;
    let cfg = Config::load()?;
    let project = Project::resolve(cli.global.project.as_deref())?;
    if !matches!(&command, Command::Query(QueryArgs { raw: Some(_), .. })) {
        // With no daemon, the next toz invocation performs expiry cleanup.
        if let Ok(dir) = project.store_dir() {
            if let Ok(raw) = toz_core::raw::RawStore::open(&dir.join("raw"), &cfg.raw, &cfg.capture)
            {
                let _ = raw.prune();
            }
        }
    }
    dispatch_loaded(&cfg, &project, &cli.global, command)
}

fn dispatch_loaded(
    cfg: &Config,
    project: &Project,
    g: &GlobalOpts,
    command: Command,
) -> Result<i32> {
    match command {
        Command::Query(a) => cmd_query(cfg, project, g, a),
        Command::Run(a) => cmd_run(cfg, project, g, a),
        Command::Capture(a) => cmd_capture(cfg, project, g, a),
        Command::Index(a) => cmd_index(cfg, project, g, a),
        Command::Fetch(a) => cmd_fetch(cfg, project, g, a),
        Command::Stats(a) => cmd_stats(project, g, a),
        Command::Purge(a) => cmd_purge(project, g, a),
        Command::Doctor => cmd_doctor(cfg, project, g),
        Command::Profile(a) => cmd_profile(cfg, project, g, a),
        Command::Event(_) => unreachable!("event returned before loading configuration"),
        Command::Install(a) => cmd_install(g, a),
        Command::Uninstall(a) => cmd_uninstall(g, a),
        Command::Note(_) => unreachable!("note returned before loading configuration"),
    }
}

fn cmd_query(cfg: &Config, project: &Project, g: &GlobalOpts, a: QueryArgs) -> Result<i32> {
    if a.raw.is_some() {
        if query_raw_conflicts(&a) {
            bail!("--raw cannot be combined with search or capture options");
        }
        return cmd_raw(
            cfg,
            project,
            RawArgs {
                handle: a.raw.unwrap(),
                stream: a.stream,
            },
        );
    }
    if a.list {
        if query_list_conflicts(&a) {
            bail!("--list cannot be combined with search or capture options");
        }
        return cmd_list(
            project,
            g,
            ListArgs {
                limit: a.limit.unwrap_or(20),
                all: a.all,
            },
        );
    }
    if !a.queries.is_empty() {
        return query_search(cfg, project, g, a);
    }
    query_retrieve(project, g, a)
}

fn query_raw_conflicts(a: &QueryArgs) -> bool {
    [
        a.list,
        a.handle.is_some(),
        !a.queries.is_empty(),
        a.chunk.is_some(),
        a.records.is_some(),
        a.lines.is_some(),
        a.source.is_some(),
        a.limit.is_some(),
        a.content_type.is_some(),
        a.all,
        a.global,
    ]
    .contains(&true)
}

fn query_list_conflicts(a: &QueryArgs) -> bool {
    [
        a.handle.is_some(),
        !a.queries.is_empty(),
        a.chunk.is_some(),
        a.records.is_some(),
        a.lines.is_some(),
        a.source.is_some(),
        a.content_type.is_some(),
        a.global,
        a.stream != "stdout",
    ]
    .contains(&true)
}

fn query_search(cfg: &Config, project: &Project, g: &GlobalOpts, a: QueryArgs) -> Result<i32> {
    if a.chunk.is_some() || a.records.is_some() || a.lines.is_some() || a.stream != "stdout" {
        bail!("--chunk, --records, --lines, and --stream require capture retrieval");
    }
    cmd_search(
        cfg,
        project,
        g,
        SearchArgs {
            queries: a.queries,
            handle: a.handle,
            source: a.source,
            limit: a.limit.unwrap_or(3),
            content_type: a.content_type,
            all: a.all,
            global: a.global,
        },
    )
}

fn query_retrieve(project: &Project, g: &GlobalOpts, a: QueryArgs) -> Result<i32> {
    let handle = a
        .handle
        .context("provide search terms, --handle, --list, or --raw")?;
    if a.source.is_some() || a.limit.is_some() || a.content_type.is_some() || a.all || a.global {
        bail!("search filters require search terms");
    }
    if a.chunk.is_some() && a.lines.is_some() {
        bail!("--chunk and --lines cannot be combined");
    }
    if a.records.is_some() && (a.chunk.is_some() || a.lines.is_some()) {
        bail!("--records cannot be combined with --chunk or --lines");
    }
    cmd_show(
        project,
        g,
        ShowArgs {
            handle,
            chunk: a.chunk,
            records: a.records,
            lines: a.lines,
            stream: a.stream,
        },
    )
}

fn cmd_raw(cfg: &Config, project: &Project, a: RawArgs) -> Result<i32> {
    let handle = toz_core::raw::RawHandle::parse(&a.handle)?;
    let dir = project.store_dir()?.join("raw");
    let raw = toz_core::raw::RawStore::open(&dir, &cfg.raw, &cfg.capture)?;
    let output = raw.get(&handle);
    let _ = raw.prune();
    let output = output?;
    let bytes = if a.stream == "stderr" {
        output.stderr
    } else {
        output.stdout
    };
    std::io::stdout().lock().write_all(&bytes)?;
    Ok(0)
}

fn open_store(cfg: &Config, project: &Project) -> Result<Store> {
    let path = project.db_path()?;
    let mut store = match Store::open(&path) {
        Ok(store) => store,
        Err(error) => {
            if !Store::access_error(&error) {
                return Err(error);
            }
            let fallback = project.fallback_db_path().filter(|p| p != &path);
            let Some(fallback) = fallback else {
                return Err(error);
            };
            let store = Store::open(&fallback)
                .with_context(|| format!("default store failed ({error:#}); opening fallback"))?;
            eprintln!(
                "varde-toz: default store unavailable; using {}",
                fallback.display()
            );
            store
        }
    };
    store.maybe_prune(&cfg.retention)?;
    Ok(store)
}

fn session() -> Option<String> {
    toz_core::config::env("TOZ_SESSION")
        .ok()
        .filter(|s| !s.is_empty())
}

fn emit_preview(g: &GlobalOpts, p: &toz_core::Preview) -> Result<()> {
    let mut out = std::io::stdout().lock();
    if g.json {
        let mut v = serde_json::to_value(p)?;
        v["preview"] = Value::String(p.render());
        writeln!(out, "{}", serde_json::to_string(&v)?)?;
    } else if g.quiet {
        writeln!(
            out,
            "varde-toz: captured {} → handle {} ({} chunks)",
            capture::fmt_bytes(p.bytes),
            p.handle,
            p.chunks
        )?;
    } else {
        out.write_all(p.render().as_bytes())?;
    }
    Ok(())
}

// ---------------------------------------------------------------------------------------------
// index

fn cmd_index(cfg: &Config, project: &Project, g: &GlobalOpts, a: IndexArgs) -> Result<i32> {
    let mut store = open_store(cfg, project)?;
    let sess = session();
    if a.paths.len() == 1 && a.paths[0].as_os_str() == "-" {
        return index_stdin(cfg, &mut store, g, &a, sess.as_deref());
    }
    let files = index_paths(&a)?;
    index_files(cfg, &mut store, g, &a, &files, sess.as_deref())
}

fn index_stdin(
    cfg: &Config,
    store: &mut Store,
    g: &GlobalOpts,
    a: &IndexArgs,
    sess: Option<&str>,
) -> Result<i32> {
    let mut raw = Vec::new();
    std::io::stdin()
        .lock()
        .read_to_end(&mut raw)
        .context("reading stdin")?;
    let source = a.label.clone().unwrap_or_else(|| "stdin".into());
    let outcome = index::index_bytes(cfg, store, &raw, &source, a.label.as_deref(), sess)?;
    report_index(g, &source, outcome)
}

fn index_paths(a: &IndexArgs) -> Result<Vec<std::path::PathBuf>> {
    let glob = a.glob.as_deref().map(glob_pattern).transpose()?;
    let mut files: Vec<std::path::PathBuf> = Vec::new();
    for p in &a.paths {
        collect_index_path(p, a.recursive, &mut files)?;
    }
    if let Some(re) = &glob {
        files.retain(|f| {
            f.file_name()
                .map(|n| re.is_match(&n.to_string_lossy()))
                .unwrap_or(false)
        });
    }
    if files.is_empty() {
        bail!("nothing to index");
    }
    Ok(files)
}

fn collect_index_path(
    path: &std::path::Path,
    recursive: bool,
    files: &mut Vec<std::path::PathBuf>,
) -> Result<()> {
    if path.is_dir() {
        let walker = walkdir::WalkDir::new(path)
            .max_depth(if recursive { usize::MAX } else { 1 })
            .follow_links(false)
            .sort_by_file_name();
        for entry in walker.into_iter().filter_entry(|e| !is_hidden(e)) {
            let entry = entry?;
            if entry.file_type().is_file() {
                files.push(entry.into_path());
            }
        }
    } else if path.is_file() {
        files.push(path.to_path_buf());
    } else {
        bail!("no such file or directory: {}", path.display());
    }
    Ok(())
}

fn index_files(
    cfg: &Config,
    store: &mut Store,
    g: &GlobalOpts,
    a: &IndexArgs,
    files: &[std::path::PathBuf],
    sess: Option<&str>,
) -> Result<i32> {
    // One explicit label across several files would make them supersede each other.
    let label = if files.len() == 1 {
        a.label.as_deref()
    } else {
        None
    };
    if files.len() > 1 && a.label.is_some() {
        println!("varde-toz: --label ignored for multiple files");
    }

    let mut worst = 0;
    for f in files {
        match index::index_file(cfg, store, f, label, sess) {
            Ok(outcome) => {
                worst = worst.max(report_index(g, &f.display().to_string(), outcome)?);
            }
            Err(e) => {
                println!("varde-toz: {}: {e:#}", f.display());
                worst = 1;
            }
        }
    }
    Ok(worst)
}

fn is_hidden(e: &walkdir::DirEntry) -> bool {
    e.depth() > 0
        && e.file_name()
            .to_str()
            .map(|s| s.starts_with('.'))
            .unwrap_or(false)
}

/// Filename glob: `*`, `?`, and `{a,b}` alternation.
fn glob_pattern(glob: &str) -> Result<regex::Regex> {
    let mut s = String::from("^");
    let mut in_alt = false;
    for ch in glob.chars() {
        match ch {
            '*' => s.push_str(".*"),
            '?' => s.push('.'),
            '{' => {
                in_alt = true;
                s.push('(');
            }
            '}' if in_alt => {
                in_alt = false;
                s.push(')');
            }
            ',' if in_alt => s.push('|'),
            c => s.push_str(&regex::escape(&c.to_string())),
        }
    }
    s.push('$');
    regex::Regex::new(&s).with_context(|| format!("invalid glob {glob:?}"))
}

fn report_index(g: &GlobalOpts, what: &str, outcome: Outcome) -> Result<i32> {
    match outcome {
        Outcome::Captured(p) => {
            emit_preview(g, &p)?;
            Ok(0)
        }
        Outcome::Skipped { rule } => {
            println!("varde-toz: {what}: not indexed ({rule})");
            Ok(1)
        }
        Outcome::PassThrough => unreachable!("index always forces capture"),
    }
}

// ---------------------------------------------------------------------------------------------
// fetch

fn cmd_fetch(cfg: &Config, project: &Project, g: &GlobalOpts, a: FetchArgs) -> Result<i32> {
    let opts = FetchOpts {
        ttl_secs: a.ttl.unwrap_or(fetch::DEFAULT_TTL_SECS),
        force: a.force,
    };
    let urls: Vec<String> = a.urls.iter().map(|u| fetch::normalize_url(u)).collect();
    let label = if urls.len() == 1 {
        a.label.clone()
    } else {
        None
    };
    if urls.len() > 1 && a.label.is_some() {
        println!("varde-toz: --label ignored for multiple URLs");
    }

    let results = fetch_many(&urls, opts, a.concurrency);
    let mut store = open_store(cfg, project)?;
    let sess = session();
    let mut worst = 0;
    for (url, result) in urls.iter().zip(results) {
        if urls.len() > 1 {
            println!("=== {url} ===");
        }
        worst = worst.max(report_fetch(
            cfg,
            project,
            g,
            &mut store,
            url,
            result,
            label.as_deref(),
            sess.as_deref(),
        )?);
    }
    Ok(worst)
}

type FetchResult = Option<std::result::Result<fetch::Fetched, String>>;

fn fetch_many(urls: &[String], opts: FetchOpts, concurrency: usize) -> Vec<FetchResult> {
    // Fetches race on a small worker pool; storing is serialised by the caller.
    let workers = concurrency.max(1).min(urls.len().max(1));
    let queue = std::sync::Arc::new(std::sync::Mutex::new((0usize, urls.to_vec())));
    let results = std::sync::Arc::new(std::sync::Mutex::new(
        (0..urls.len()).map(|_| None).collect::<Vec<FetchResult>>(),
    ));
    let handles: Vec<_> = (0..workers)
        .map(|_| {
            let queue = queue.clone();
            let results = results.clone();
            std::thread::spawn(move || loop {
                let (i, url) = {
                    let mut q = queue.lock().unwrap();
                    if q.0 >= q.1.len() {
                        break;
                    }
                    let i = q.0;
                    q.0 += 1;
                    (i, q.1[i].clone())
                };
                let r = fetch::fetch(&url, opts).map_err(|e| format!("{e:#}"));
                results.lock().unwrap()[i] = Some(r);
            })
        })
        .collect();
    for h in handles {
        let _ = h.join();
    }
    std::sync::Arc::try_unwrap(results)
        .ok()
        .unwrap()
        .into_inner()
        .unwrap()
}

fn report_fetch(
    cfg: &Config,
    project: &Project,
    g: &GlobalOpts,
    store: &mut Store,
    url: &str,
    result: FetchResult,
    label: Option<&str>,
    sess: Option<&str>,
) -> Result<i32> {
    let mut fetched = match result {
        Some(Ok(fetched)) => fetched,
        Some(Err(e)) => {
            println!("varde-toz: {e}");
            return Ok(1);
        }
        None => return Ok(0),
    };
    if report_cached_fetch(&fetched, project, g, store, url)? {
        return Ok(0);
    }
    match fetch::store_fetched(cfg, store, &project.key, &mut fetched, label, sess)? {
        Outcome::Captured(p) => {
            emit_preview(g, &p)?;
            Ok(0)
        }
        Outcome::Skipped { rule } => {
            println!("varde-toz: {url}: not stored ({rule})");
            Ok(1)
        }
        Outcome::PassThrough => unreachable!("fetch always forces capture"),
    }
}

fn report_cached_fetch(
    fetched: &fetch::Fetched,
    project: &Project,
    g: &GlobalOpts,
    store: &Store,
    url: &str,
) -> Result<bool> {
    // A cache hit whose capture still exists in this project needs no new store entry.
    if !fetched.from_cache || fetched.meta.project_key.as_deref() != Some(&project.key) {
        return Ok(false);
    }
    let Some(handle) = &fetched.meta.handle else {
        return Ok(false);
    };
    let Some(row) = store.get_by_handle(handle)? else {
        return Ok(false);
    };
    if row.superseded_by.is_some() {
        return Ok(false);
    }
    let age = fmt_age(toz_core::store::now() - fetched.meta.fetched_at);
    if g.json {
        println!(
            "{}",
            json!({"handle": handle, "cached": true, "fetched_at": fetched.meta.fetched_at, "url": url})
        );
    } else {
        println!(
            "varde-toz: cached {age} ago → handle {handle} ({} chunks)   next: varde-toz query --handle {handle} \"<query>\"   |   varde-toz query --handle {handle} --chunk N",
            row.chunk_count
        );
    }
    Ok(true)
}

// ---------------------------------------------------------------------------------------------
// stats

fn cmd_stats(project: &Project, g: &GlobalOpts, a: StatsArgs) -> Result<i32> {
    let stores: Vec<(String, std::path::PathBuf)> = if a.global {
        toz_core::project::all_store_dbs(project)?
    } else {
        vec![(project.key.clone(), project.db_path()?)]
    };
    let sess = session();
    // `--session`: the harness-provided TOZ_SESSION if set, else the last 8 hours.
    let (session_filter, since) = if a.session {
        match &sess {
            Some(s) => (Some(s.as_str()), None),
            None => (None, Some(toz_core::store::now() - 8 * 3600)),
        }
    } else {
        (None, None)
    };

    let mut rows = Vec::new();
    for (key, path) in stores {
        if !path.exists() {
            continue;
        }
        let store = Store::open_readonly(&path)?;
        rows.push((key, store.stats(session_filter, since)?));
    }

    if g.json {
        print_stats_json(&rows)?;
        return Ok(0);
    }
    print_stats_text(&rows, a.global, a.session, sess.as_deref());
    Ok(0)
}

fn print_stats_json(rows: &[(String, toz_core::store::Stats)]) -> Result<()> {
    let v: Vec<Value> = rows
        .iter()
        .map(|(k, s)| {
            let mut v = serde_json::to_value(s).unwrap();
            v["project"] = Value::String(k.clone());
            let saved = (s.bytes_in - s.bytes_out).max(0);
            v["tokens_saved_estimate"] = json!(saved / 4);
            v["reduction_pct"] = json!(if s.bytes_in > 0 {
                saved * 100 / s.bytes_in
            } else {
                0
            });
            v
        })
        .collect();
    println!("{}", serde_json::to_string(&v)?);
    Ok(())
}

fn print_stats_text(
    rows: &[(String, toz_core::store::Stats)],
    global: bool,
    session: bool,
    sess: Option<&str>,
) {
    let window = if session {
        match sess {
            Some(s) => format!("session {s}"),
            None => "last 8 hours".to_string(),
        }
    } else {
        "all time".to_string()
    };
    if rows.is_empty() {
        println!("varde-toz: no store yet ({window})");
        return;
    }
    for (key, s) in rows {
        if global {
            println!("== {key} ==");
        }
        let saved = (s.bytes_in - s.bytes_out).max(0);
        let pct = if s.bytes_in > 0 {
            saved * 100 / s.bytes_in
        } else {
            0
        };
        println!(
            "{window}: {} captures, {} in → {} out ({pct}% kept out of context, ~{} tokens at bytes/4)",
            s.captures,
            capture::fmt_bytes(s.bytes_in as usize),
            capture::fmt_bytes(s.bytes_out as usize),
            fmt_count(saved / 4),
        );
        for k in &s.by_kind {
            println!(
                "  {:<14} {:>5}  {:>14} → {}",
                k.kind,
                k.captures,
                capture::fmt_bytes(k.bytes_in as usize),
                capture::fmt_bytes(k.bytes_out as usize),
            );
        }
        println!(
            "store: {} captures on disk, {} DB",
            s.stored_captures,
            capture::fmt_bytes(s.db_bytes as usize)
        );
    }
}

fn fmt_count(n: i64) -> String {
    capture::fmt_bytes(n.max(0) as usize)
        .trim_end_matches(" bytes")
        .to_string()
}

// ---------------------------------------------------------------------------------------------
// purge

/// `30m`, `12h`, `7d`, `2w`, or bare seconds.
fn parse_duration(s: &str) -> Result<i64> {
    let s = s.trim();
    let (num, unit) = match s.find(|c: char| !c.is_ascii_digit()) {
        Some(i) => s.split_at(i),
        None => (s, "s"),
    };
    let n: i64 = num
        .parse()
        .with_context(|| format!("invalid duration {s:?}"))?;
    let mult = match unit.trim() {
        "s" | "sec" | "secs" => 1,
        "m" | "min" | "mins" => 60,
        "h" | "hr" | "hours" => 3600,
        "d" | "day" | "days" => 86400,
        "w" | "week" | "weeks" => 7 * 86400,
        _ => bail!("invalid duration {s:?} (use e.g. 30m, 12h, 7d)"),
    };
    Ok(n * mult)
}

fn confirm(prompt: &str, yes: bool) -> Result<bool> {
    if yes {
        return Ok(true);
    }
    if unsafe { libc::isatty(libc::STDIN_FILENO) } == 0 {
        bail!("refusing without --yes (stdin is not a terminal)");
    }
    eprint!("{prompt} [y/N] ");
    let mut line = String::new();
    std::io::stdin().read_line(&mut line)?;
    Ok(matches!(line.trim(), "y" | "Y" | "yes"))
}

fn cmd_purge(project: &Project, g: &GlobalOpts, a: PurgeArgs) -> Result<i32> {
    let targets: Vec<(String, std::path::PathBuf)> = if a.global {
        toz_core::project::all_store_dbs(project)?
    } else {
        vec![(project.key.clone(), project.db_path()?)]
    };
    let targets: Vec<_> = targets.into_iter().filter(|(_, p)| p.exists()).collect();
    if targets.is_empty() {
        println!("varde-toz: nothing to purge");
        return Ok(0);
    }

    if let Some(dur) = &a.older_than {
        return purge_older(&targets, g, a.global, dur);
    }
    purge_stores(project, g, &a, &targets)
}

fn purge_older(
    targets: &[(String, std::path::PathBuf)],
    g: &GlobalOpts,
    global: bool,
    dur: &str,
) -> Result<i32> {
    let secs = parse_duration(dur)?;
    let mut total = 0;
    for (key, path) in targets {
        let mut store = Store::open(path)?;
        let n = store.delete_older_than(secs)?;
        store.vacuum()?;
        total += n;
        if global {
            println!("{key}: removed {n} capture(s)");
        }
    }
    if g.json {
        println!("{}", json!({"removed": total}));
    } else {
        println!("varde-toz: removed {total} capture(s) older than {dur}");
    }
    Ok(0)
}

fn purge_stores(
    project: &Project,
    g: &GlobalOpts,
    a: &PurgeArgs,
    targets: &[(String, std::path::PathBuf)],
) -> Result<i32> {
    let what = if a.global {
        format!("delete ALL {} toz store(s)", targets.len())
    } else {
        format!("delete the toz store for {}", project.key)
    };
    if !confirm(&format!("varde-toz: {what}?"), a.yes)? {
        println!("varde-toz: aborted");
        return Ok(1);
    }
    let mut n = 0;
    for (key, path) in targets {
        let dir = path.parent().context("store path has no parent")?;
        std::fs::remove_dir_all(dir).with_context(|| format!("removing {}", dir.display()))?;
        n += 1;
        if !g.json {
            println!("removed {key}");
        }
    }
    if a.global {
        let swept = fetch::cache_sweep(0)?;
        if !g.json {
            println!("removed {swept} cached page(s)");
        }
    }
    if g.json {
        println!("{}", json!({"removed_stores": n}));
    }
    Ok(0)
}

// ---------------------------------------------------------------------------------------------
// profile

fn cmd_profile(cfg: &Config, project: &Project, g: &GlobalOpts, a: ProfileArgs) -> Result<i32> {
    match a.cmd {
        ProfileCommand::List => cmd_profile_list(project, g),
        ProfileCommand::Test(t) => cmd_profile_test(cfg, project, g, t),
    }
}

fn cmd_profile_list(project: &Project, g: &GlobalOpts) -> Result<i32> {
    let (profiles, diagnostics) = profile::load_profiles(project);
    let summaries = profile::summarize(&profiles);

    if g.json {
        println!(
            "{}",
            serde_json::to_string(&json!({
                "profiles": summaries,
                "diagnostics": diagnostics,
            }))?
        );
        return Ok(0);
    }

    if summaries.is_empty() {
        println!("varde-toz: no profiles loaded");
    } else {
        for s in &summaries {
            println!(
                "{}  [{}]  {}{}",
                s.id,
                s.scope,
                s.file,
                if s.has_script { "  (script)" } else { "" }
            );
        }
    }
    for d in &diagnostics {
        println!(
            "warning: {}{}: {}",
            d.profile_id
                .as_ref()
                .map(|id| format!("{id} "))
                .unwrap_or_default(),
            d.file.display(),
            d.reason
        );
    }
    Ok(0)
}

/// One `[[profile.test]]` case's outcome.
#[derive(Debug, serde::Serialize)]
struct ProfileTestResult {
    profile_id: String,
    name: String,
    passed: bool,
    reason: Option<String>,
}

fn cmd_profile_test(
    cfg: &Config,
    project: &Project,
    g: &GlobalOpts,
    a: ProfileTestArgs,
) -> Result<i32> {
    let (profiles, diagnostics) = match &a.file {
        Some(path) => profile::load_file(path),
        None => profile::load_profiles(project),
    };

    let results: Vec<ProfileTestResult> = profiles
        .iter()
        .flat_map(|p| p.tests.iter().map(move |case| (p, case)))
        .map(|(p, case)| run_profile_test_case(cfg, &profiles, p, case))
        .collect();
    let any_failed = results.iter().any(|r| !r.passed);

    if g.json {
        println!(
            "{}",
            serde_json::to_string(&json!({
                "results": results,
                "diagnostics": diagnostics,
            }))?
        );
    } else {
        if results.is_empty() {
            println!("varde-toz: no profile test cases");
        }
        for r in &results {
            if r.passed {
                println!("pass: {} / {}", r.profile_id, r.name);
            } else {
                println!(
                    "FAIL: {} / {}: {}",
                    r.profile_id,
                    r.name,
                    r.reason.as_deref().unwrap_or("unknown failure")
                );
            }
        }
        for d in &diagnostics {
            println!(
                "warning: {}{}: {}",
                d.profile_id
                    .as_ref()
                    .map(|id| format!("{id} "))
                    .unwrap_or_default(),
                d.file.display(),
                d.reason
            );
        }
    }

    Ok(if any_failed { 1 } else { 0 })
}

/// Run one test case against a throwaway in-memory store: force a capture of `case.input`
/// through the real pipeline (so a declarative profile's sections/preview and a scripted
/// profile's records are both exercised), then check `expect_records` and
/// `expect_preview_contains` against what came out.
fn run_profile_test_case(
    cfg: &Config,
    profiles: &[profile::Profile],
    p: &profile::Profile,
    case: &profile::ProfileTest,
) -> ProfileTestResult {
    let fail = |reason: String| ProfileTestResult {
        profile_id: p.id.clone(),
        name: case.name.clone(),
        passed: false,
        reason: Some(reason),
    };

    // The case has no match field of its own; derive a source that satisfies this profile's own
    // `match` glob so `capture::run`'s matching picks the same profile the case belongs to.
    let Some(source) = profile_test_source(p) else {
        return fail("profile has no `match`; cannot select it for a test case".into());
    };

    let (_dir, mut store) = match profile_test_store() {
        Ok(pair) => pair,
        Err(e) => return fail(format!("temp store: {e:#}")),
    };

    let mut input = CaptureInput::new(case.input.as_bytes(), &source, "run");
    input.force = true;

    let outcome = match capture::run(cfg, &mut store, input, profiles) {
        Ok(o) => o,
        Err(e) => return fail(format!("capture failed: {e:#}")),
    };
    let preview = match outcome {
        Outcome::Captured(preview) => preview,
        Outcome::PassThrough => {
            return fail("capture was not stored (stayed under threshold)".into())
        }
        Outcome::Skipped { rule } => return fail(format!("capture skipped: {rule}")),
    };

    let mut failures = missing_profile_preview_terms(&preview.render(), case);

    if case.expect_records.is_some() {
        if !check_profile_records(&store, &preview.handle, case, &mut failures) {
            return fail(failures.join("; "));
        }
    }

    if failures.is_empty() {
        ProfileTestResult {
            profile_id: p.id.clone(),
            name: case.name.clone(),
            passed: true,
            reason: None,
        }
    } else {
        fail(failures.join("; "))
    }
}

fn profile_test_source(p: &profile::Profile) -> Option<String> {
    match &p.match_spec {
        Some(profile::MatchSpec::Command(glob)) => Some(glob.pattern.clone()),
        Some(profile::MatchSpec::Source(glob)) => Some(glob.pattern.clone()),
        None => None,
    }
}

fn profile_test_store() -> Result<(tempfile::TempDir, Store)> {
    let dir = tempfile::tempdir()?;
    let store = Store::open(&dir.path().join("toz.db"))?;
    Ok((dir, store))
}

fn missing_profile_preview_terms(rendered: &str, case: &profile::ProfileTest) -> Vec<String> {
    case.expect_preview_contains
        .iter()
        .filter(|needle| !rendered.contains(needle.as_str()))
        .map(|needle| format!("preview missing {needle:?}"))
        .collect()
}

fn check_profile_records(
    store: &Store,
    handle: &str,
    case: &profile::ProfileTest,
    failures: &mut Vec<String>,
) -> bool {
    let Some(table) = case
        .expect_records
        .as_ref()
        .and_then(|expect| expect.as_table())
    else {
        failures.push("expect_records is not a table".into());
        return false;
    };
    let capture_id = store.get_by_handle(handle).ok().flatten().map(|r| r.id);
    let Some(id) = capture_id else {
        failures.push("no capture row found for handle".into());
        return false;
    };
    for (kind, expected_val) in table {
        let expected: Vec<Value> = expected_val
            .as_array()
            .map(|arr| {
                arr.iter()
                    .map(|v| serde_json::to_value(v).unwrap_or(Value::Null))
                    .collect()
            })
            .unwrap_or_default();
        let actual: Vec<Value> = store
            .records_for(id, kind)
            .unwrap_or_default()
            .iter()
            .map(|s| serde_json::from_str(s).unwrap_or(Value::Null))
            .collect();
        if actual != expected {
            failures.push(format!(
                "records[{kind}]: expected {}, got {}",
                serde_json::to_string(&expected).unwrap_or_default(),
                serde_json::to_string(&actual).unwrap_or_default()
            ));
        }
    }
    true
}

// ---------------------------------------------------------------------------------------------
// doctor

fn cmd_doctor(cfg: &Config, project: &Project, g: &GlobalOpts) -> Result<i32> {
    let mut checks = Vec::new();
    let (_, profile_load_diagnostics) = profile::load_profiles(project);
    doctor_profile_load(&profile_load_diagnostics, &mut checks);
    doctor_executable(&mut checks);
    doctor_config_dir(cfg, &mut checks);
    doctor_ca_bundle(&mut checks);
    doctor_config_settings(cfg, &mut checks);
    doctor_store_dir(project, &mut checks);
    let mut profile_diagnostics = Vec::new();
    doctor_store(project, &mut checks, &mut profile_diagnostics);
    doctor_plugins(&mut checks);
    doctor_sandbox_access(project, &mut checks);
    doctor_context_mode(&mut checks);
    let recent = diagnostics::recent();
    doctor_hook_outcomes(&recent, &mut checks);
    let failures = checks.iter().filter(|(p, _)| !*p).count();
    if g.json {
        let v: Vec<Value> = checks
            .iter()
            .map(|(p, m)| json!({"ok": p, "message": m}))
            .collect();
        println!(
            "{}",
            json!({
                "checks": v,
                "warnings": failures,
                "hook_outcomes_7d": recent.ok(),
                "profile_diagnostics": profile_diagnostics,
                "profile_load_diagnostics": profile_load_diagnostics,
            })
        );
    } else {
        for (pass, msg) in &checks {
            println!("{} {msg}", if *pass { "ok  " } else { "warn" });
        }
        if failures == 0 {
            println!("all good");
        } else {
            println!("{failures} warning(s)");
        }
    }
    Ok(if failures == 0 { 0 } else { 1 })
}

fn doctor_profile_load(diagnostics: &[profile::Diagnostic], checks: &mut Vec<(bool, String)>) {
    let mut ok = |pass: bool, msg: String| checks.push((pass, msg));
    // Load-time profile diagnostics (e.g. a project-scope script dropped because the
    // project is not in trusted_projects) — the same call `varde-toz profile list` makes.
    for d in diagnostics {
        ok(
            false,
            format!(
                "profile diagnostic: {}{}: {}",
                d.profile_id
                    .as_ref()
                    .map(|id| format!("{id} "))
                    .unwrap_or_default(),
                d.file.display(),
                d.reason
            ),
        );
    }
}

fn doctor_executable(checks: &mut Vec<(bool, String)>) {
    let mut ok = |pass: bool, msg: String| checks.push((pass, msg));
    let exe = std::env::current_exe()
        .map(|p| p.canonicalize().unwrap_or(p))
        .unwrap_or_default();
    ok(
        true,
        format!(
            "varde-toz {} at {}",
            env!("CARGO_PKG_VERSION"),
            exe.display()
        ),
    );
}

fn doctor_config_dir(cfg: &Config, checks: &mut Vec<(bool, String)>) {
    let mut ok = |pass: bool, msg: String| checks.push((pass, msg));
    // Config.
    match toz_core::config::config_dir() {
        Ok(dir) => {
            let cfg_path = dir.join("config.toml");
            ok(
                true,
                format!(
                    "config dir {} ({})",
                    dir.display(),
                    if cfg_path.exists() {
                        "config.toml present"
                    } else {
                        "defaults; no config.toml"
                    }
                ),
            );
            if let Some(log) = &cfg.hook_log {
                let size = std::fs::metadata(log).map(|m| m.len()).unwrap_or(0);
                ok(
                    false,
                    format!(
                        "hook_log is on ({}, {}) — grows unbounded; remove once payload shapes are confirmed",
                        log.display(),
                        capture::fmt_bytes(size as usize)
                    ),
                );
            }
            // Cache dir writable.
            match fetch::cache_dir().and_then(|c| {
                std::fs::create_dir_all(&c)?;
                let probe = c.join(".doctor-probe");
                std::fs::write(&probe, b"ok")?;
                std::fs::remove_file(&probe)?;
                Ok(c)
            }) {
                Ok(c) => ok(true, format!("fetch cache writable at {}", c.display())),
                Err(e) => ok(false, format!("fetch cache not writable: {e:#}")),
            }
        }
        Err(e) => ok(false, format!("config dir: {e:#}")),
    }
}

fn doctor_ca_bundle(checks: &mut Vec<(bool, String)>) {
    let mut ok = |pass: bool, msg: String| checks.push((pass, msg));
    match toz_core::fetch::ca_bundle_status() {
        Ok(Some((path, n))) => ok(
            true,
            format!("fetch verifies TLS against {} ({n} roots)", path.display()),
        ),
        // Asking the OS to evaluate chains needs a service that sandboxed harness shells deny,
        // so this is a warning even though it works fine in an unsandboxed terminal.
        Ok(None) => ok(
            false,
            "no CA bundle found; fetch falls back to the OS trust store, which fails inside a \
             sandboxed shell. Set SSL_CERT_FILE to a PEM bundle."
                .to_string(),
        ),
        Err(e) => ok(false, format!("CA bundle unusable: {e:#}")),
    }
}

fn doctor_config_settings(cfg: &Config, checks: &mut Vec<(bool, String)>) {
    let mut ok = |pass: bool, msg: String| checks.push((pass, msg));
    ok(
        true,
        format!(
            "threshold {} bytes (per-tool overrides: {}); redaction {}; never-capture {} pattern(s)",
            cfg.threshold,
            if cfg.thresholds.is_empty() {
                "none".to_string()
            } else {
                cfg.thresholds
                    .iter()
                    .map(|(k, v)| format!("{k}={v}"))
                    .collect::<Vec<_>>()
                    .join(", ")
            },
            if cfg.redact.builtin {
                format!("builtin + {} user pattern(s)", cfg.redact.patterns.len())
            } else {
                format!("{} user pattern(s), builtin OFF", cfg.redact.patterns.len())
            },
            if cfg.capture.builtin_never {
                format!("builtin + {}", cfg.capture.never.len())
            } else {
                format!("{}, builtin OFF", cfg.capture.never.len())
            },
        ),
    );
    ok(
        true,
        format!(
            "raw exact output {} (cap {} bytes, TTL {} seconds)",
            if cfg.raw.enabled {
                "enabled"
            } else {
                "disabled"
            },
            cfg.raw.max_bytes,
            cfg.raw.ttl_secs
        ),
    );
}

fn doctor_store_dir(project: &Project, checks: &mut Vec<(bool, String)>) {
    let mut ok = |pass: bool, msg: String| checks.push((pass, msg));
    // Which source chose the project store directory.
    match project.store_dir_with_source() {
        Ok((dir, source)) => ok(
            true,
            format!("store dir {} (source: {source})", dir.display()),
        ),
        Err(e) => ok(false, format!("store dir: {e:#}")),
    }
}

fn doctor_store(
    project: &Project,
    checks: &mut Vec<(bool, String)>,
    profile_diagnostics: &mut Vec<toz_core::store::ProfileDiagnosticRow>,
) {
    let mut ok = |pass: bool, msg: String| checks.push((pass, msg));
    // Store + FTS5 + trigram.
    match project.db_path() {
        Ok(path) => match Store::open(&path) {
            Ok(store) => {
                ok(
                    true,
                    format!(
                        "store opens: {} ({} captures, {})",
                        path.display(),
                        store.list(usize::MAX, true).map(|r| r.len()).unwrap_or(0),
                        capture::fmt_bytes(store.db_size_bytes().unwrap_or(0) as usize)
                    ),
                );
                let fts = store.conn().execute_batch(
                    "CREATE VIRTUAL TABLE temp.doctor_fts USING fts5(x, tokenize='trigram');
                     DROP TABLE temp.doctor_fts;",
                );
                match fts {
                    Ok(()) => ok(true, "FTS5 with trigram tokenizer available".into()),
                    Err(e) => ok(false, format!("FTS5/trigram check failed: {e}")),
                }
                match store.recent_profile_diagnostics(10) {
                    Ok(diags) if diags.is_empty() => {
                        ok(true, "no recent profile script diagnostics".into());
                    }
                    Ok(diags) => {
                        ok(
                            false,
                            format!(
                                "{} recent profile script diagnostic(s); latest: {} — {}",
                                diags.len(),
                                diags[0].profile_id,
                                diags[0].reason
                            ),
                        );
                        *profile_diagnostics = diags;
                    }
                    Err(e) => ok(false, format!("profile diagnostics unavailable: {e:#}")),
                }
            }
            Err(e) => ok(false, format!("store {}: {e:#}", path.display())),
        },
        Err(e) => ok(false, format!("store path: {e:#}")),
    }
}

fn doctor_plugins(checks: &mut Vec<(bool, String)>) {
    for bundle in crate::install::BUNDLES {
        doctor_plugin(bundle, checks);
    }
}

fn doctor_plugin(bundle: &'static crate::install::Bundle, checks: &mut Vec<(bool, String)>) {
    let version = crate::install::installed_version(bundle.binary);
    let bundle = crate::install::resolve(bundle, version);
    let dir = match (bundle.default_dir)() {
        Ok(dir) => dir,
        Err(e) => {
            checks.push((false, format!("{}: {e:#}", bundle.harness)));
            return;
        }
    };
    if !bundle
        .files
        .iter()
        .any(|(rel, _, _)| dir.join(rel).exists())
        && !match bundle.harness {
            "pi" => dir.join("extensions/toz.ts").exists(),
            "opencode" => dir.join("plugin/toz.ts").exists(),
            "claude-code" => dir.with_file_name("toz").join("hooks/hooks.json").exists(),
            _ => false,
        }
    {
        checks.push((
            bundle.harness != "claude-code",
            format!(
                "{} plugin not installed (run `varde-toz install {}`)",
                bundle.harness, bundle.harness
            ),
        ));
        return;
    }
    doctor_plugin_version(bundle, version, checks);
    doctor_plugin_drift(bundle, &dir, checks);
}

fn doctor_plugin_version(
    bundle: &crate::install::Bundle,
    version: Option<(u64, u64, u64)>,
    checks: &mut Vec<(bool, String)>,
) {
    let mut ok = |pass: bool, msg: String| checks.push((pass, msg));
    match version {
        Some(v) if v < bundle.min_version => ok(
            false,
            format!(
                "{} {} is older than {} which the shim needs ({})",
                bundle.harness,
                crate::install::fmt_version(v),
                crate::install::fmt_version(bundle.min_version),
                bundle.why_min
            ),
        ),
        Some(v) => ok(
            true,
            format!(
                "{} {} ≥ {} ({})",
                bundle.harness,
                crate::install::fmt_version(v),
                crate::install::fmt_version(bundle.min_version),
                bundle.why_min
            ),
        ),
        None => ok(
            false,
            format!(
                "{} version unknown (`{} --version` not runnable); shim needs ≥ {} for {}",
                bundle.harness,
                bundle.binary,
                crate::install::fmt_version(bundle.min_version),
                bundle.why_min
            ),
        ),
    }
}

fn doctor_plugin_drift(
    bundle: &crate::install::Bundle,
    dir: &std::path::Path,
    checks: &mut Vec<(bool, String)>,
) {
    let mut drift = Vec::new();
    for (rel, template, mode) in bundle.files {
        let have = std::fs::read_to_string(dir.join(rel)).ok();
        let want =
            crate::install::desired(*mode, template, have.as_deref(), dir).unwrap_or_default();
        if have.as_deref() != Some(want.as_str()) {
            drift.push(*rel);
        }
    }
    if drift.is_empty() {
        checks.push((
            true,
            format!(
                "{} plugin installed at {} and up to date",
                bundle.harness,
                dir.display()
            ),
        ));
        return;
    }
    let blocked = crate::install::unowned_files(bundle, dir);
    let advice = if blocked.is_empty() {
        format!("run `varde-toz install {}`", bundle.harness)
    } else {
        format!(
            "`varde-toz install {}` will refuse: {} look hand-edited; move them aside or use --force",
            bundle.harness,
            blocked.join(", ")
        )
    };
    checks.push((
        false,
        format!(
            "{} plugin at {} is out of date ({}); {}",
            bundle.harness,
            dir.display(),
            drift.join(", "),
            advice
        ),
    ));
}

fn doctor_sandbox_access(project: &Project, checks: &mut Vec<(bool, String)>) {
    let mut ok = |pass: bool, msg: String| checks.push((pass, msg));
    // An actual open above is authoritative; config text alone cannot prove sandbox access.
    if let Some(fallback) = project.fallback_db_path().filter(|p| p.is_file()) {
        ok(
            true,
            format!("using sandbox fallback store {}", fallback.display()),
        );
    } else if let (Some(home), Ok(store_root)) = (dirs::home_dir(), toz_core::config::config_dir())
    {
        let cfg_path = home.join(".codex").join("config.toml");
        if let Ok(text) = std::fs::read_to_string(&cfg_path) {
            let root = store_root.to_string_lossy();
            let listed = text.contains(&*root)
                || text.contains(&root.replace(&home.to_string_lossy().to_string(), "~"));
            ok(
                listed,
                if listed {
                    format!(
                        "codex: {} is listed in writable_roots; active sandbox access may differ",
                        root
                    )
                } else {
                    format!(
                        "codex: add the toz store to the sandbox so `varde-toz run` can save output:\n                                [sandbox_workspace_write]\n       writable_roots = [\"{}\"]  (in {})",
                        root,
                        cfg_path.display()
                    )
                },
            );
        }
    }
}

fn doctor_context_mode(checks: &mut Vec<(bool, String)>) {
    let mut ok = |pass: bool, msg: String| checks.push((pass, msg));
    // context-mode conflict.
    if let Some(home) = dirs::home_dir() {
        let settings = home.join(".claude").join("settings.json");
        if let Ok(text) = std::fs::read_to_string(&settings) {
            if let Ok(v) = serde_json::from_str::<Value>(&text) {
                let enabled = v["enabledPlugins"]
                    .as_object()
                    .map(|m| {
                        m.iter().any(|(k, on)| {
                            k.starts_with("context-mode@") && on == &Value::Bool(true)
                        })
                    })
                    .unwrap_or(false);
                if enabled {
                    ok(
                        false,
                        "context-mode plugin is enabled in Claude Code — its steering contradicts toz's; \
                         run `claude plugin disable context-mode@context-mode`"
                            .into(),
                    );
                } else {
                    ok(
                        true,
                        "context-mode plugin not enabled in Claude Code".into(),
                    );
                }
                let leftovers = text.contains("context-mode statusline")
                    || text.contains("context-mode-cache-heal");
                if leftovers {
                    ok(
                        true,
                        "leftover context-mode statusline/hook entries in ~/.claude/settings.json (harmless; remove if you like)"
                            .into(),
                    );
                }
            }
        }
    }
}

fn doctor_hook_outcomes(recent: &Result<diagnostics::Summary>, checks: &mut Vec<(bool, String)>) {
    let mut ok = |pass: bool, msg: String| checks.push((pass, msg));
    match recent {
        Ok(summary) => {
            let attempts = summary.captured + summary.failed;
            let detail = summary
                .last_failure
                .as_deref()
                .map(|last| format!("; latest: {last}"))
                .unwrap_or_default();
            ok(
                summary.failed == 0
                    && summary.unreadable_lines == 0
                    && summary.unavailable_sources == 0,
                format!(
                    "retained hook outcomes, last 7 days: {} captured, {} skipped, {} failed ({} attempted), {} unreadable records, {} unavailable sources{}",
                    summary.captured, summary.skipped, summary.failed, attempts, summary.unreadable_lines, summary.unavailable_sources, detail
                ),
            );
        }
        Err(e) => ok(false, format!("hook diagnostics unavailable: {e:#}")),
    }
}

// ---------------------------------------------------------------------------------------------
// run

fn cmd_run(cfg: &Config, project: &Project, g: &GlobalOpts, a: RunArgs) -> Result<i32> {
    cmd_script(cfg, project, g, a)
}

fn pass_through(stdout: &[u8], stderr: &[u8]) -> Result<()> {
    let mut o = std::io::stdout().lock();
    o.write_all(stdout)?;
    o.flush()?;
    let mut e = std::io::stderr().lock();
    e.write_all(stderr)?;
    e.flush()?;
    Ok(())
}

// ---------------------------------------------------------------------------------------------
// capture (stdin / hook)

fn cmd_capture(cfg: &Config, project: &Project, g: &GlobalOpts, a: CaptureArgs) -> Result<i32> {
    let mut raw = Vec::new();
    std::io::stdin()
        .lock()
        .read_to_end(&mut raw)
        .context("reading stdin")?;

    if a.hook {
        return hook_capture(cfg, project, &raw, &a.harness);
    }

    let (stdout, stderr): (&[u8], &[u8]) = if a.stderr { (&[], &raw) } else { (&raw, &[]) };
    let source = a
        .source
        .clone()
        .or_else(|| a.label.clone())
        .unwrap_or_else(|| "stdin".into());
    let total = raw.len();
    let threshold = a.threshold.unwrap_or(cfg.threshold);
    if !a.force && total <= threshold {
        pass_through(stdout, stderr)?;
        return Ok(0);
    }

    let mut store = open_store(cfg, project)?;
    let sess = session();
    let (profiles, _) = profile::load_profiles(project);
    let outcome = capture::run(
        cfg,
        &mut store,
        CaptureInput {
            stdout,
            stderr,
            label: a.label.as_deref(),
            source: &source,
            kind: &a.kind,
            exit_code: a.exit_code,
            session: sess.as_deref(),
            force: a.force,
            defer_index: a.defer_index,
            threshold: a.threshold,
            file_mtime: None,
            file_hash: None,
        },
        &profiles,
    )?;
    match outcome {
        Outcome::PassThrough | Outcome::Skipped { .. } => pass_through(stdout, stderr)?,
        Outcome::Captured(p) => emit_preview(g, &p)?,
    }
    Ok(0)
}

/// Claude Code PostToolUse payload → `updatedToolOutput` JSON on overflow, nothing otherwise.
fn hook_capture(cfg: &Config, project: &Project, raw: &[u8], harness: &str) -> Result<i32> {
    let log = toz_core::config::env("TOZ_HOOK_LOG")
        .ok()
        .map(std::path::PathBuf::from)
        .or_else(|| cfg.hook_log.clone());
    if let Some(path) = log {
        log_payload(&path, raw);
    }
    let payload: Value = match serde_json::from_slice(raw) {
        Ok(v) => v,
        Err(_) => {
            diagnostics::record_best_effort(harness, "failed", "invalid-payload", "", raw.len());
            return Ok(0);
        }
    };
    let tool = payload["tool_name"].as_str().unwrap_or("");
    let input = &payload["tool_input"];
    let response = &payload["tool_response"];
    let Some(shape) = extract(tool, input, response, harness) else {
        diagnostics::record_best_effort(harness, "skipped", "unsupported-shape", tool, raw.len());
        return Ok(0);
    };

    // A running unified-exec session is delivered again when its final
    // write_stdin poll completes. Leave intermediate polling output alone.
    if harness == "codex" && !shape.completed {
        return Ok(0);
    }

    let total = shape.stdout.len() + shape.stderr.len();
    let threshold = cfg.threshold_for(tool);
    if total <= threshold {
        return Ok(0);
    }
    if ["toz ", "varde-toz "]
        .iter()
        .any(|name| shape.source.trim_start().starts_with(name))
    {
        return Ok(0); // don't capture our own previews
    }

    let Some(preview) = capture_hook_output(
        cfg, project, &payload, &shape, harness, tool, threshold, total,
    )?
    else {
        return Ok(0);
    };
    print_hook_output(harness, &shape, response, &preview);
    Ok(0)
}

fn capture_hook_output(
    cfg: &Config,
    project: &Project,
    payload: &Value,
    shape: &Extracted,
    harness: &str,
    tool: &str,
    threshold: usize,
    total: usize,
) -> Result<Option<Box<toz_core::Preview>>> {
    let mut store = open_store(cfg, project)?;
    let sess = session().or_else(|| {
        payload["session_id"]
            .as_str()
            .filter(|s| !s.is_empty())
            .map(|s| format!("{harness}-{s}"))
    });
    let kind = format!("hook:{tool}");
    let (profiles, _) = profile::load_profiles(project);
    let outcome = capture::run(
        cfg,
        &mut store,
        CaptureInput {
            stdout: shape.stdout.as_bytes(),
            stderr: shape.stderr.as_bytes(),
            label: Some(&shape.label),
            source: &shape.source,
            kind: &kind,
            exit_code: shape.exit_code,
            session: sess.as_deref(),
            force: false,
            defer_index: false,
            threshold: Some(threshold),
            file_mtime: None,
            file_hash: None,
        },
        &profiles,
    )?;
    let p = match outcome {
        Outcome::Captured(p) => p,
        Outcome::Skipped { .. } => {
            diagnostics::record_best_effort(harness, "skipped", "excluded", tool, total);
            return Ok(None);
        }
        Outcome::PassThrough => {
            diagnostics::record_best_effort(harness, "skipped", "pass-through", tool, total);
            return Ok(None);
        }
    };
    diagnostics::record_best_effort(harness, "captured", "stored", tool, total);
    Ok(Some(p))
}

fn print_hook_output(harness: &str, shape: &Extracted, response: &Value, p: &toz_core::Preview) {
    let text = p.render();

    if harness == "codex" {
        print_codex_hook_output(shape, p, &text);
        return;
    }

    let (key, value) = match &shape.kind {
        ShapeKind::Streams => (
            "updatedToolOutput",
            json!({
                "stdout": text,
                "stderr": "",
                "interrupted": response["interrupted"].as_bool().unwrap_or(false),
            }),
        ),
        ShapeKind::PlainString => ("updatedToolOutput", Value::String(text)),
        ShapeKind::ContentBlocks => ("updatedMCPToolOutput", content_preview(response, &text)),
        ShapeKind::ContentField => {
            let mut v = response.clone();
            v["content"] = content_preview(&response["content"], &text);
            ("updatedToolOutput", v)
        }
        ShapeKind::Field(path) => {
            let mut v = response.clone();
            // `set_path` keeps arrays as arrays: Claude Code joins Grep/Glob `filenames` itself.
            set_path(&mut v, &path, Value::String(text));
            ("updatedToolOutput", v)
        }
    };
    println!(
        "{}",
        json!({ "hookSpecificOutput": { "hookEventName": "PostToolUse", key: value } })
    );
}

fn print_codex_hook_output(shape: &Extracted, p: &toz_core::Preview, text: &str) {
    // Codex can replace stream-shaped command results with bounded feedback. Other
    // shapes get a handle hint because its output replacement support is limited.
    if matches!(shape.kind, ShapeKind::Streams) {
        let context = format!(
            "{}\n\nFull output is searchable as handle {}. Later: varde-toz query --handle {} \"<query>\" | varde-toz query --handle {} --chunk N",
            text, p.handle, p.handle, p.handle
        );
        println!(
            "{}",
            json!({
                "continue": false,
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": context
                }
            })
        );
        return;
    }
    let hint = format!(
        "varde-toz: stored this output as handle {h} ({}, {} chunks). Later: varde-toz query --handle {h} \"<query>\" | varde-toz query --handle {h} --chunk N",
        capture::fmt_bytes(p.bytes),
        p.chunks,
        h = p.handle,
    );
    println!(
        "{}",
        json!({ "hookSpecificOutput": { "hookEventName": "PostToolUse", "additionalContext": hint } })
    );
}

fn content_preview(response: &Value, text: &str) -> Value {
    let mut replaced_text = false;
    let items = response
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|item| {
            if item["type"] != "text" {
                return Some(item.clone());
            }
            if replaced_text {
                return None;
            }
            replaced_text = true;
            Some(json!({ "type": "text", "text": text }))
        })
        .collect();
    Value::Array(items)
}

/// Hook-mode failures are logged, never surfaced: stderr (visible to the user, not the model)
/// plus the hook log when one is configured.
pub fn log_hook_error(e: &anyhow::Error, harness: &str) {
    diagnostics::record_best_effort(harness, "failed", "hook-error", "", 0);
    eprintln!("varde-toz: hook failed open: {e:#}");
    let log = toz_core::config::env("TOZ_HOOK_LOG")
        .ok()
        .map(std::path::PathBuf::from)
        .or_else(|| Config::load().ok().and_then(|c| c.hook_log));
    if let Some(path) = log {
        log_payload(&path, format!("# toz hook error: {e:#}").as_bytes());
    }
}

fn log_payload(path: &std::path::Path, raw: &[u8]) {
    use std::io::Write as _;
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
        let _ = f.write_all(raw);
        let _ = f.write_all(b"\n");
    }
}

enum ShapeKind {
    Streams,
    PlainString,
    ContentBlocks,
    ContentField,
    /// Text lived at this key path inside a structured response object; replace it in place.
    Field(Vec<String>),
}

struct Extracted {
    kind: ShapeKind,
    stdout: String,
    stderr: String,
    label: String,
    source: String,
    exit_code: Option<i32>,
    completed: bool,
}

fn source_of(tool: &str, input: &Value) -> String {
    if let (Some(pattern), Some(path)) = (input["pattern"].as_str(), input["path"].as_str()) {
        return format!("{} {pattern} {path}", tool.to_ascii_lowercase());
    }
    let keys = [
        "command",
        "cmd",
        "file_path",
        "filePath",
        "path",
        "url",
        "query",
        "pattern",
    ];
    let value = keys
        .iter()
        .filter_map(|key| input[key].as_str())
        .find(|value| !value.is_empty());
    value.map(str::to_string).unwrap_or_else(|| {
        format!(
            "{tool} {}",
            serde_json::to_string(input).unwrap_or_default()
        )
    })
}

/// Normalize text-bearing response shapes without relying on tool names.
fn extract(tool: &str, input: &Value, response: &Value, harness: &str) -> Option<Extracted> {
    let source = source_of(tool, input);
    let label = format!("{tool}: {}", toz_core::chunk::truncate(&source, 100));
    if response["stdout"].is_string() || response["output"].is_string() {
        return Some(extract_streams(response, source, label));
    }
    if let Some(text) = extract_content_text(response) {
        return Some(Extracted {
            kind: if response.is_array() {
                ShapeKind::ContentBlocks
            } else {
                ShapeKind::ContentField
            },
            stdout: text,
            stderr: String::new(),
            label,
            source,
            exit_code: None,
            completed: true,
        });
    }
    if let Some(s) = response.as_str() {
        return Some(Extracted {
            kind: ShapeKind::PlainString,
            stdout: follow_truncation_notice(s, harness),
            stderr: String::new(),
            label,
            source,
            exit_code: None,
            completed: true,
        });
    }
    if response.is_object() {
        let (path, text) = dominant_text(response)?;
        return Some(Extracted {
            kind: ShapeKind::Field(path),
            stdout: follow_truncation_notice(&text, harness),
            stderr: String::new(),
            label,
            source,
            exit_code: None,
            completed: response_completed(response),
        });
    }
    None
}

fn extract_streams(response: &Value, source: String, label: String) -> Extracted {
    // Claude Code truncates stdout before PostToolUse, but can persist the full output.
    let mut stdout = response["stdout"]
        .as_str()
        .or_else(|| response["output"].as_str())
        .or_else(|| response.as_str())
        .unwrap_or("")
        .to_string();
    if let Some(path) = response["persistedOutputPath"].as_str() {
        if let Ok(full) = std::fs::read_to_string(path) {
            if full.len() > stdout.len() {
                stdout = full;
            }
        }
    }
    Extracted {
        kind: ShapeKind::Streams,
        stdout,
        stderr: response["stderr"].as_str().unwrap_or("").to_string(),
        label,
        source,
        exit_code: response["exit_code"].as_i64().map(|c| c as i32),
        completed: response_completed(response),
    }
}

fn extract_content_text(response: &Value) -> Option<String> {
    let items = response
        .as_array()
        .or_else(|| response["content"].as_array())?;
    let text: Vec<&str> = items
        .iter()
        .filter(|i| i["type"] == "text")
        .filter_map(|i| i["text"].as_str())
        .collect();
    (!text.is_empty()).then(|| text.join("\n"))
}

/// Unified-exec returns a live session before it has an exit code. Codex emits
/// the original command's final PostToolUse event after the last write_stdin.
fn response_completed(response: &Value) -> bool {
    match response.get("exit_code") {
        Some(Value::Number(_)) => true,
        Some(Value::Null) => false,
        Some(_) => false,
        None => match response.get("status").and_then(Value::as_str) {
            Some(status) => matches!(
                status.to_ascii_lowercase().as_str(),
                "complete" | "completed" | "done" | "exited" | "finished" | "success"
            ),
            None => response.get("session_id").is_none() && response.get("process_id").is_none(),
        },
    }
}

/// opencode and pi keep only the tail of big shell output and append a notice naming the file
/// with the full output. When that file is readable and larger, capture it instead.
fn follow_truncation_notice(text: &str, harness: &str) -> String {
    // opencode: "[output truncated; full output saved to: P]"; pi: "[Showing lines … Full output: P]"
    const MARKS: &[&str] = &["full output saved to: ", "Full output: "];
    let Some((i, mark)) = MARKS
        .iter()
        .filter_map(|m| text.rfind(m).map(|i| (i, *m)))
        .max_by_key(|(i, _)| *i)
    else {
        return text.to_string();
    };
    let rest = &text[i + mark.len()..];
    let path = rest.split([']', '\n']).next().unwrap_or("").trim();
    if path.is_empty() {
        return text.to_string();
    }
    let Some(path) = trusted_truncation_path(harness, path) else {
        return text.to_string();
    };
    match std::fs::read_to_string(path) {
        Ok(full) if full.len() > text.len() => full,
        _ => text.to_string(),
    }
}

fn trusted_truncation_path(harness: &str, path: &str) -> Option<std::path::PathBuf> {
    let path = std::fs::canonicalize(path).ok()?;
    if !path.is_file() {
        return None;
    }
    let name = path.file_name()?.to_str()?;
    let roots = match harness {
        "opencode" if name.starts_with("tool_") => {
            let mut roots = Vec::new();
            if let Some(dir) = std::env::var_os("XDG_DATA_HOME").filter(|d| !d.is_empty()) {
                roots.push(std::path::PathBuf::from(dir));
            } else if let Some(home) = dirs::home_dir() {
                roots.push(home.join(".local").join("share"));
            }
            if let Some(dir) = dirs::data_dir() {
                roots.push(dir);
            }
            roots
                .into_iter()
                .map(|root| root.join("opencode").join("tool-output"))
                .collect::<Vec<_>>()
        }
        "pi" if name
            .strip_prefix("pi-bash-")
            .and_then(|s| s.strip_suffix(".log"))
            .is_some_and(|id| !id.is_empty() && id.bytes().all(|b| b.is_ascii_hexdigit())) =>
        {
            vec![std::env::temp_dir()]
        }
        _ => return None,
    };
    roots
        .into_iter()
        .filter_map(|root| std::fs::canonicalize(root).ok())
        .any(|root| path.parent() == Some(root.as_path()))
        .then_some(path)
}

/// Keys that hold metadata, never payload.
const META_KEYS: &[&str] = &[
    "filePath",
    "file_path",
    "url",
    "type",
    "mode",
    "durationMs",
    "code",
    "codeText",
    "title",
];

/// The largest string (or string-array joined by newlines) within two levels of the object,
/// with its key path. Structured responses often put payload text in a nested field;
/// smaller sibling metadata stays untouched.
fn dominant_text(v: &Value) -> Option<(Vec<String>, String)> {
    fn walk(
        v: &Value,
        path: &mut Vec<String>,
        depth: usize,
        best: &mut Option<(Vec<String>, String)>,
    ) {
        let Some(obj) = v.as_object() else { return };
        for (k, val) in obj {
            if META_KEYS.contains(&k.as_str()) {
                continue;
            }
            let candidate = match val {
                Value::String(s) => Some(s.clone()),
                Value::Array(items) if !items.is_empty() && items.iter().all(|i| i.is_string()) => {
                    Some(
                        items
                            .iter()
                            .filter_map(|i| i.as_str())
                            .collect::<Vec<_>>()
                            .join("\n"),
                    )
                }
                _ => None,
            };
            if let Some(text) = candidate {
                if best.as_ref().is_none_or(|(_, b)| text.len() > b.len()) {
                    let mut p = path.clone();
                    p.push(k.clone());
                    *best = Some((p, text));
                }
            } else if val.is_object() && depth < 2 {
                path.push(k.clone());
                walk(val, path, depth + 1, best);
                path.pop();
            }
        }
    }
    let mut best = None;
    walk(v, &mut Vec::new(), 0, &mut best);
    best
}

fn set_path(v: &mut Value, path: &[String], new: Value) {
    let mut cur = v;
    for (i, k) in path.iter().enumerate() {
        if i + 1 == path.len() {
            // arrays of strings become a one-element array so the shape stays an array
            let replacement = if cur[k].is_array() {
                Value::Array(vec![new])
            } else {
                new
            };
            cur[k] = replacement;
            return;
        }
        cur = &mut cur[k];
    }
}

// ---------------------------------------------------------------------------------------------
// install / note

fn cmd_install(g: &GlobalOpts, a: InstallArgs) -> Result<i32> {
    let forced = match a.for_version.as_deref() {
        Some(text) => Some(
            crate::install::parse_version(text)
                .with_context(|| format!("--for-version {text:?} is not an X.Y.Z version"))?,
        ),
        None => None,
    };
    let b = crate::install::resolve(crate::install::bundle(&a.harness)?, forced);
    let dir = match a.dir {
        Some(d) => d,
        None => (b.default_dir)()?,
    };
    if a.print {
        for (rel, template, _) in b.files {
            println!("==> {rel}\n{}", crate::install::render_at(template, &dir)?);
        }
        return Ok(0);
    }
    let written = crate::install::install(b, &dir, a.force)?;
    if g.json {
        let v: Vec<Value> = written
            .iter()
            .map(|(p, c)| json!({"path": p, "changed": c}))
            .collect();
        println!("{}", serde_json::to_string(&v)?);
        return Ok(0);
    }
    for (p, changed) in &written {
        println!(
            "{} {}",
            if *changed { "wrote  " } else { "current" },
            p.display()
        );
    }
    println!("\n{}", b.after);
    Ok(0)
}

fn cmd_uninstall(g: &GlobalOpts, a: UninstallArgs) -> Result<i32> {
    let b = crate::install::bundle(&a.harness)?;
    let dir = match a.dir {
        Some(d) => d,
        None => (b.default_dir)()?,
    };
    let done = crate::install::uninstall(b, &dir)?;
    if g.json {
        let v: Vec<Value> = done
            .iter()
            .map(|(p, what)| json!({"path": p, "result": what}))
            .collect();
        println!("{}", serde_json::to_string(&v)?);
        return Ok(0);
    }
    for (p, what) in &done {
        println!("{what:<20} {}", p.display());
    }
    Ok(0)
}

fn cmd_note(a: NoteArgs) -> Result<i32> {
    let mut note = crate::install::usage_note(
        toz_core::config::env_os("TOZ_FALLBACK_DIR")
            .as_deref()
            .map(std::path::Path::new),
    );
    match diagnostics::recent() {
        Ok(summary) if summary.failed > 0 || summary.unreadable_lines > 0 || summary.unavailable_sources > 0 => note.push_str(&format!(
            "\nToz recorded {} hook failure(s), {} unreadable record(s), and {} unavailable diagnostic source(s) recently. Run `varde-toz doctor --json` and report recurring failures.",
            summary.failed, summary.unreadable_lines, summary.unavailable_sources
        )),
        Err(_) => note.push_str("\nToz diagnostics are unavailable. Run `varde-toz doctor --json`."),
        _ => {}
    }
    match a.harness.as_deref() {
        Some("claude-code") | Some("codex") => println!(
            "{}",
            json!({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": note}})
        ),
        _ => println!("{note}"),
    }
    Ok(0)
}

// ---------------------------------------------------------------------------------------------
// show / list

fn cmd_search(cfg: &Config, project: &Project, g: &GlobalOpts, a: SearchArgs) -> Result<i32> {
    let opts = SearchOpts {
        limit: a.limit,
        handle: a.handle.clone(),
        source: a.source.clone(),
        content_type: a.content_type.clone(),
        include_superseded: a.all,
        recency_floor: None,
    };
    let results = if a.global {
        search_all_projects(project, &a, &opts)?
    } else {
        let Some(results) = search_project(cfg, project, g, &a, &opts)? else {
            return Ok(0);
        };
        results
    };
    print_results(g, &results, a.global)?;
    Ok(0)
}

fn search_all_projects(
    project: &Project,
    a: &SearchArgs,
    opts: &SearchOpts,
) -> Result<Vec<QueryResult>> {
    let mut merged: Vec<QueryResult> = a
        .queries
        .iter()
        .map(|q| QueryResult {
            query: q.clone(),
            corrected: None,
            hits: Vec::new(),
        })
        .collect();
    for (key, db) in toz_core::project::all_store_dbs(project)? {
        let store = match Store::open(&db) {
            Ok(mut store) => {
                store.index_deferred(a.handle.as_deref())?;
                store
            }
            Err(_) => {
                let store = Store::open_readonly(&db)?;
                if store.has_deferred(a.handle.as_deref())? {
                    bail!("deferred capture requires a writable store for its first term search");
                }
                store
            }
        };
        for (i, r) in search::search(&store, &a.queries, opts)?
            .into_iter()
            .enumerate()
        {
            if merged[i].corrected.is_none() {
                merged[i].corrected = r.corrected;
            }
            merged[i].hits.extend(r.hits.into_iter().map(|mut h| {
                h.project = Some(key.clone());
                h
            }));
        }
    }
    for r in &mut merged {
        r.hits.sort_by(|x, y| {
            y.score
                .partial_cmp(&x.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        r.hits.truncate(a.limit.max(1));
    }
    Ok(merged)
}

fn search_project(
    cfg: &Config,
    project: &Project,
    g: &GlobalOpts,
    a: &SearchArgs,
    opts: &SearchOpts,
) -> Result<Option<Vec<QueryResult>>> {
    let path = project.db_path()?;
    if !path.exists() {
        if g.json {
            println!("[]");
        } else {
            println!("varde-toz: no captures yet for this project");
        }
        return Ok(None);
    }
    // Best effort: a read-only store searches without refreshing changed files.
    let (store, refreshed) = match Store::open(&path) {
        Ok(mut store) => {
            let refreshed =
                index::refresh_stale(cfg, &mut store, session().as_deref()).unwrap_or_default();
            store.index_deferred(a.handle.as_deref())?;
            (store, refreshed)
        }
        Err(_) => {
            let store = Store::open_readonly(&path)?;
            if store.has_deferred(a.handle.as_deref())? {
                bail!("deferred capture requires a writable store for its first term search");
            }
            (store, Vec::new())
        }
    };
    if !refreshed.is_empty() && !g.json {
        println!(
            "varde-toz: re-indexed {} changed file{}",
            refreshed.len(),
            if refreshed.len() == 1 { "" } else { "s" }
        );
    }
    Ok(Some(search::search(&store, &a.queries, opts)?))
}

fn print_results(g: &GlobalOpts, results: &[QueryResult], show_project: bool) -> Result<()> {
    let mut out = std::io::stdout().lock();
    if g.json {
        writeln!(out, "{}", serde_json::to_string(results)?)?;
        return Ok(());
    }
    for r in results {
        write!(out, "## {}", r.query)?;
        if let Some(c) = &r.corrected {
            write!(out, "  (searched for \"{c}\" instead)")?;
        }
        writeln!(out)?;
        if r.hits.is_empty() {
            writeln!(out, "  no matches")?;
        }
        for h in &r.hits {
            print_hit(&mut out, h, show_project)?;
        }
        writeln!(out)?;
    }
    Ok(())
}

fn print_hit(out: &mut impl Write, h: &search::Hit, show_project: bool) -> Result<()> {
    let proj = match (&h.project, show_project) {
        (Some(p), true) => format!(" [{p}]"),
        _ => String::new(),
    };
    let stream = if h.stream == "stderr" {
        " [stderr]"
    } else {
        ""
    };
    let stale = if h.stale {
        " [STALE: file changed]"
    } else {
        ""
    };
    writeln!(
        out,
        "[{}:{}] {} — {} (L{}-L{}){}{}{}",
        h.handle,
        h.chunk,
        toz_core::chunk::truncate(&h.label, 40),
        toz_core::chunk::truncate(&h.title, 50),
        h.line_start,
        h.line_end,
        stream,
        stale,
        proj
    )?;
    for line in h.snippet.lines() {
        writeln!(out, "    {line}")?;
    }
    Ok(())
}

fn cmd_show(project: &Project, g: &GlobalOpts, a: ShowArgs) -> Result<i32> {
    let store = open_for_handle(project, &a.handle)?;
    let Some(row) = store.get_by_handle(&a.handle)? else {
        bail!("no capture with handle {}", a.handle)
    };
    if row.binary {
        bail!("legacy binary capture contains metadata only; content was not retained");
    }
    let mut out = std::io::stdout().lock();

    if let Some(kind) = &a.records {
        for json in store.records_for(row.id, kind)? {
            writeln!(out, "{json}")?;
        }
        return Ok(0);
    }

    if let Some(i) = a.chunk {
        let chunks = store.chunks_for(row.id)?;
        let Some(c) = chunks.get(i) else {
            bail!("capture {} has {} chunks", a.handle, chunks.len())
        };
        if g.json {
            writeln!(
                out,
                "{}",
                json!({"handle": row.handle, "chunk": i, "stream": c.stream, "title": c.title,
                "line_start": c.line_start, "line_end": c.line_end, "body": c.body})
            )?;
        } else {
            writeln!(
                out,
                "── {} [{}] L{}-L{} ──",
                c.title, c.stream, c.line_start, c.line_end
            )?;
            writeln!(out, "{}", c.body)?;
        }
        return Ok(0);
    }

    let text = store.full_text(row.id, &a.stream)?;
    if let Some(range) = &a.lines {
        let (lo, hi) = parse_range(range)?;
        let lines: Vec<&str> = if row.chunk_count == 0 {
            Vec::new()
        } else {
            text.split('\n').collect()
        };
        let hi = hi.min(lines.len());
        if lo == 0 || lo > hi {
            bail!("range {range} out of bounds (1..{})", lines.len());
        }
        for l in &lines[lo - 1..hi] {
            writeln!(out, "{l}")?;
        }
        return Ok(0);
    }
    writeln!(out, "{text}")?;
    Ok(0)
}

/// The project store if it has the handle, else the first other store that does.
/// Compute over a capture without returning its body.
///
/// Exit codes skip 2: `main.rs` maps every `Err` to 2, so script-level failures return `Ok(code)`
/// and 2 keeps meaning "toz itself failed".
fn cmd_script(cfg: &Config, project: &Project, g: &GlobalOpts, a: RunArgs) -> Result<i32> {
    if !cfg.script.enabled {
        bail!("toz run is disabled (set script.enabled = true in config.toml)");
    }
    let source = script_source(&a)?;
    if source.trim().is_empty() {
        bail!("empty script; pass --file - with a heredoc, or --code '<js>' for a one-liner");
    }

    let limits = script_limits(cfg, &a);
    let (meta, src) = script_input(project, &a)?;
    let scratch = tempfile::tempdir().context("creating script scratch directory")?;
    let policy = cfg
        .sandbox
        .enabled
        .then(|| script_policy(cfg, project, scratch.path()))
        .transpose()?;
    let (outcome, external_calls_used) = worker::run_script(
        cfg,
        project,
        &source,
        &meta,
        src,
        &limits,
        worker::Launch {
            policy: policy.as_ref(),
            scratch: scratch.path(),
        },
    )?;
    match outcome {
        toz_core::script::Outcome::Ok(text) => {
            emit_script_result(cfg, project, g, &a, &source, text, external_calls_used)
        }
        toz_core::script::Outcome::Exception(msg) => {
            eprintln!("varde-toz: script error: {msg}");
            Ok(1)
        }
        toz_core::script::Outcome::Timeout => {
            eprintln!(
                "varde-toz: script exceeded {}ms; narrow the computation or raise --timeout-ms",
                limits.timeout_ms
            );
            Ok(3)
        }
        toz_core::script::Outcome::MemoryLimit => {
            eprintln!(
                "varde-toz: script exceeded {}MB; prefer vardeToz.eachLine() over vardeToz.text(), or raise --memory-mb",
                limits.memory_bytes / (1024 * 1024)
            );
            Ok(4)
        }
        toz_core::script::Outcome::OutputLimit => {
            eprintln!(
                "varde-toz: script printed more than {} bytes; aggregate further before printing",
                limits.max_output_bytes
            );
            Ok(5)
        }
    }
}

fn script_limits(cfg: &Config, a: &RunArgs) -> toz_core::script::Limits {
    toz_core::script::Limits {
        timeout_ms: a.timeout_ms.unwrap_or(cfg.script.timeout_ms),
        memory_bytes: a
            .memory_mb
            .unwrap_or(cfg.script.memory_mb)
            .saturating_mul(1024 * 1024),
        max_output_bytes: cfg.script.max_output_bytes,
        max_text_bytes: cfg.script.max_text_bytes,
        ..toz_core::script::Limits::default()
    }
}

fn script_input(
    project: &Project,
    a: &RunArgs,
) -> Result<(
    toz_core::script::Meta,
    std::rc::Rc<dyn toz_core::script::LineSource>,
)> {
    let (meta, src): (
        toz_core::script::Meta,
        std::rc::Rc<dyn toz_core::script::LineSource>,
    ) = if let Some(handle) = &a.handle {
        let store = open_for_handle(project, handle)?;
        let Some(row) = store.get_by_handle(handle)? else {
            bail!("no capture with handle {handle}")
        };
        if row.binary {
            bail!("capture {handle} holds metadata only; scripts operate on text");
        }
        // A partial aggregate could look like a complete answer.
        if row.state == "running" && !a.partial {
            bail!(
                    "capture {handle} is still running; wait for it to finish, or pass --partial to compute over what has been committed so far"
                );
        }
        let meta = toz_core::script::Meta {
            handle: row.handle.clone(),
            label: row.label.clone(),
            bytes: row.bytes,
            lines: store.line_count(row.id, &a.stream)?,
            exit_code: row.exit_code,
            stream: a.stream.clone(),
        };
        let src = std::rc::Rc::new(toz_core::script::StoreLines::new(store, row.id));
        (meta, src)
    } else {
        (
            toz_core::script::Meta {
                stream: a.stream.clone(),
                ..Default::default()
            },
            std::rc::Rc::new(toz_core::script::EmptyLines),
        )
    };
    Ok((meta, src))
}

pub(crate) fn script_policy(
    cfg: &Config,
    project: &Project,
    scratch: &std::path::Path,
) -> Result<sandbox::Policy> {
    let mut read_roots = cfg.sandbox.read_roots.clone();
    let mut write_roots = cfg.sandbox.write_roots.clone();
    match cfg.sandbox.workspace {
        WorkspaceAccess::None => {}
        WorkspaceAccess::ReadOnly => read_roots.push(project.root.clone()),
        WorkspaceAccess::ReadWrite => write_roots.push(project.root.clone()),
    }
    let store = open_store(cfg, project)?;
    let mut protected_roots = vec![store
        .path()
        .parent()
        .context("store has no parent")?
        .to_path_buf()];
    if let Ok(config_root) = toz_core::config::config_dir() {
        if config_root.is_dir() {
            protected_roots.push(config_root);
        }
    }
    if let Some(fallback) = project.fallback_db_path() {
        if let Some(parent) = fallback.parent().filter(|path| path.is_dir()) {
            protected_roots.push(parent.to_path_buf());
        }
    }
    Ok(sandbox::Policy {
        read_roots,
        write_roots,
        scratch_dir: scratch.to_path_buf(),
        network: cfg.sandbox.network,
        env_allow: cfg.sandbox.env_allow.clone(),
        protected_roots,
    })
}

fn script_source(a: &RunArgs) -> Result<String> {
    match (&a.code, &a.script) {
        (Some(c), _) => Ok(c.clone()),
        (None, Some(f)) if f == "-" => {
            let mut s = String::new();
            std::io::stdin()
                .read_to_string(&mut s)
                .context("reading script from stdin")?;
            Ok(s)
        }
        (None, Some(f)) => {
            std::fs::read_to_string(f).with_context(|| format!("reading script {f}"))
        }
        (None, None) => bail!("pass --file - with a heredoc (preferred), or --code '<js>'"),
    }
}

/// The result goes through the normal capture path, so a large aggregate becomes its own handle
/// rather than landing in context. Supersession keys on handle + script fingerprint: two different
/// questions about one capture coexist, while re-running the same script replaces its own answer.
fn emit_script_result(
    cfg: &Config,
    project: &Project,
    g: &GlobalOpts,
    a: &RunArgs,
    source: &str,
    text: String,
    external_calls_used: bool,
) -> Result<i32> {
    let mut origin = format!(
        "toz run {} #{}",
        a.handle.as_deref().unwrap_or("no-capture"),
        toz_core::script::source_fingerprint(source)
    );
    if external_calls_used {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_nanos();
        origin.push_str(&format!(" invocation-{}-{nonce}", std::process::id()));
    }
    let mut store = open_store(cfg, project).context("run could not save its script result")?;
    let sess = session();
    let mut input = CaptureInput::new(text.as_bytes(), &origin, "script");
    input.label = a.label.as_deref();
    input.exit_code = Some(0);
    input.session = sess.as_deref();
    input.force = true;
    // The origin here is an internal marker (`varde-toz run <handle> #<fingerprint>`), not a
    // command or path a profile would target.
    match capture::run(cfg, &mut store, input, &[])? {
        Outcome::Captured(p) => {
            if g.json {
                println!(
                    "{}",
                    json!({"state":"captured","handle":p.handle,"bytes":p.bytes})
                );
            } else {
                println!("varde-toz: script result saved → handle {}", p.handle);
            }
        }
        Outcome::PassThrough | Outcome::Skipped { .. } => {
            bail!("run script result was excluded from capture");
        }
    }
    Ok(0)
}

fn open_for_handle(project: &Project, handle: &str) -> Result<Store> {
    let local = project.db_path()?;
    if local.exists() {
        let s = Store::open_readonly(&local)?;
        if s.get_by_handle(handle)?.is_some() {
            return Ok(s);
        }
    }
    for (_, db) in toz_core::project::all_store_dbs(project)? {
        if db == local {
            continue;
        }
        let s = Store::open_readonly(&db)?;
        if s.get_by_handle(handle)?.is_some() {
            return Ok(s);
        }
    }
    bail!("no capture with handle {handle}")
}

fn parse_range(s: &str) -> Result<(usize, usize)> {
    let (a, b) = s.split_once(':').context("range must be A:B")?;
    Ok((a.parse()?, b.parse()?))
}

fn cmd_list(project: &Project, g: &GlobalOpts, a: ListArgs) -> Result<i32> {
    let path = project.db_path()?;
    if !path.exists() {
        if g.json {
            println!("[]");
        }
        return Ok(0);
    }
    let store = Store::open_readonly(&path)?;
    let rows = store.list(a.limit, a.all)?;
    if g.json {
        let v: Vec<Value> = rows
            .iter()
            .map(|r| {
                json!({"handle": r.handle, "label": r.label, "kind": r.kind, "source": r.source, "bytes": r.bytes,
                    "chunks": r.chunk_count, "exit_code": r.exit_code, "created_at": r.created_at,
                    "superseded": r.superseded_by.is_some(), "session": r.session, "state": r.state})
            })
            .collect();
        println!("{}", serde_json::to_string(&v)?);
        return Ok(0);
    }
    let now = toz_core::store::now();
    for r in rows {
        let age = fmt_age(now - r.created_at);
        let sup = if r.superseded_by.is_some() {
            " (superseded)"
        } else {
            ""
        };
        println!(
            "{:<6} {:>12} {:>4} chunks  {:>7}  {}{}",
            r.handle,
            capture::fmt_bytes(r.bytes as usize),
            r.chunk_count,
            age,
            toz_core::chunk::truncate(&r.label, 70),
            sup
        );
    }
    Ok(0)
}

fn fmt_age(secs: i64) -> String {
    match secs {
        s if s < 60 => format!("{s}s ago"),
        s if s < 3600 => format!("{}m ago", s / 60),
        s if s < 86400 => format!("{}h ago", s / 3600),
        s => format!("{}d ago", s / 86400),
    }
}
