//! `varde setup autosave install|uninstall|run` for a standalone Git store.

use clap::{Arg, ArgAction, Command};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::ffi::OsString;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command as ProcessCommand, ExitCode, Output, Stdio};
use toz_core::config::Redact;
use toz_core::redact::Redactor;

const ABOUT: &str = "Schedule commits and secret-scanned pushes for a standalone Git store";
const DEFAULT_BRANCH: &str = "main";
const DEFAULT_MAX_FILE_MB: u64 = 50;
const TEST_PLIST_DIR: &str = "VARDE_AUTOSAVE_TEST_PLIST_DIR";
const TEST_LAUNCHCTL: &str = "VARDE_AUTOSAVE_TEST_LAUNCHCTL";

pub fn command() -> Command {
    Command::new("autosave")
        .bin_name("varde setup autosave")
        .about(ABOUT)
        .arg_required_else_help(true)
        .subcommand_required(true)
        .subcommand(
            Command::new("install")
                .about("Install the scheduled autosave job for an explicit standalone store")
                .arg(repo_arg())
                .arg(branch_arg())
                .arg(
                    Arg::new("interval-minutes")
                        .long("interval-minutes")
                        .value_name("MINUTES")
                        .value_parser(clap::value_parser!(u64).range(1..))
                        .default_value("30")
                        .help("Minutes between scheduled runs"),
                )
                .arg(max_file_mb_arg())
                .arg(
                    Arg::new("dry-run")
                        .long("dry-run")
                        .action(ArgAction::SetTrue)
                        .help("Print the plist and launchctl commands without writing or running them"),
                ),
        )
        .subcommand(
            Command::new("uninstall")
                .about("Remove the scheduled autosave job")
                .arg(repo_arg()),
        )
        .subcommand(
            Command::new("run")
                .about("Run one autosave tick")
                .arg(repo_arg())
                .arg(branch_arg())
                .arg(max_file_mb_arg())
                .arg(
                    Arg::new("scan-only")
                        .long("scan-only")
                        .action(ArgAction::SetTrue)
                        .help("Scan outgoing commits without staging, committing, or pushing"),
                ),
        )
}

fn repo_arg() -> Arg {
    Arg::new("repo")
        .long("repo")
        .value_name("DIR")
        .required(true)
        .help("Standalone Git store root")
}

fn branch_arg() -> Arg {
    Arg::new("branch")
        .long("branch")
        .value_name("NAME")
        .default_value(DEFAULT_BRANCH)
        .help("Branch to autosave")
}

fn max_file_mb_arg() -> Arg {
    Arg::new("max-file-mb")
        .long("max-file-mb")
        .value_name("MB")
        .value_parser(clap::value_parser!(u64))
        .default_value("50")
        .help("Maximum size of a staged added or modified file")
}

pub fn run(args: Vec<OsString>) -> ExitCode {
    let matches = match command().try_get_matches_from(args) {
        Ok(matches) => matches,
        Err(error) => {
            let code = error.exit_code();
            let _ = error.print();
            return ExitCode::from(code as u8);
        }
    };
    let Some((action, matches)) = matches.subcommand() else {
        return ExitCode::from(2);
    };
    let result = match action {
        "install" => install(matches),
        "uninstall" => uninstall(matches),
        "run" => tick(matches),
        _ => Err(format!("unknown autosave command {action}")),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("autosave: {error}");
            ExitCode::from(1)
        }
    }
}

fn install(matches: &clap::ArgMatches) -> Result<(), String> {
    let repo = store_root(matches.get_one::<String>("repo").unwrap())?;
    let branch = matches.get_one::<String>("branch").unwrap();
    require_upstream(&repo, branch)?;

    let interval = *matches.get_one::<u64>("interval-minutes").unwrap();
    let max_file_mb = *matches.get_one::<u64>("max-file-mb").unwrap();
    let dry_run = matches.get_flag("dry-run");
    let launchd = Launchctl::from_env();
    if !dry_run && !launchd.is_test_fake() && !cfg!(target_os = "macos") {
        return Err("launchd install is available only on macOS; use `varde setup autosave run` with a scheduler on this host".into());
    }

    let paths = JobPaths::new(&repo)?;
    let domain = gui_domain()?;
    let plist = render_plist(&repo, branch, interval, max_file_mb, &paths)?;
    if dry_run {
        print!("{plist}");
        println!("launchctl bootstrap {domain} {}", paths.plist.display());
        println!("launchctl bootout {domain} {}", paths.plist.display());
        return Ok(());
    }

    fs::create_dir_all(&paths.plist_dir).map_err(|error| error.to_string())?;
    fs::write(&paths.plist, plist).map_err(|error| error.to_string())?;
    launchd.bootstrap(&domain, &paths.plist)
}

fn uninstall(matches: &clap::ArgMatches) -> Result<(), String> {
    let repo = store_root(matches.get_one::<String>("repo").unwrap())?;
    let paths = JobPaths::new(&repo)?;
    if !paths.plist.exists() {
        return Ok(());
    }
    let launchd = Launchctl::from_env();
    let domain = gui_domain()?;
    match launchd.bootout(&domain, &paths.plist) {
        Ok(()) => {}
        Err(error) if missing_launchd_job(&error) => {}
        Err(error) => return Err(error),
    }
    fs::remove_file(&paths.plist).map_err(|error| error.to_string())
}

fn tick(matches: &clap::ArgMatches) -> Result<(), String> {
    let repo = store_root(matches.get_one::<String>("repo").unwrap())?;
    let branch = matches.get_one::<String>("branch").unwrap();
    let upstream = require_upstream(&repo, branch)?;
    if matches.get_flag("scan-only") {
        return scan_outgoing(&repo, &upstream, branch);
    }
    let current = match git(&repo, &["symbolic-ref", "--short", "HEAD"]) {
        Ok(output) => String::from_utf8_lossy(&output.stdout).trim().to_owned(),
        Err(_) => return skip("detached HEAD"),
    };
    if current != *branch {
        return skip(&format!("not on branch {branch}"));
    }
    if in_progress(&repo)? {
        return skip("merge or rebase in progress");
    }
    if index_lock(&repo)?.exists() {
        return skip("index.lock exists");
    }
    if let Err(error) = stage_and_commit(&repo, *matches.get_one::<u64>("max-file-mb").unwrap()) {
        if is_index_lock_error(&error) {
            return skip("index.lock blocked a Git operation");
        }
        return Err(error);
    }
    scan_outgoing(&repo, &upstream, branch)?;
    let ahead = git_text(
        &repo,
        &["rev-list", "--count", &format!("{upstream}..{branch}")],
    )?;
    if ahead.parse::<u64>().unwrap_or_default() == 0 {
        return Ok(());
    }
    let output = git_command(&repo)
        .arg("push")
        .output()
        .map_err(|error| error.to_string())?;
    if output.status.success() {
        return Ok(());
    }
    let error = String::from_utf8_lossy(&output.stderr).trim().to_owned();
    if error.contains("non-fast-forward") || error.contains("fetch first") {
        return Err("remote diverged; not pushing".into());
    }
    Err(if error.is_empty() {
        "git push failed".into()
    } else {
        error
    })
}

fn skip(reason: &str) -> Result<(), String> {
    eprintln!("autosave: {reason}; skipping tick");
    Ok(())
}

fn stage_and_commit(repo: &Path, max_file_mb: u64) -> Result<(), String> {
    checked(
        git_command(repo)
            .args(["add", "-A"])
            .output()
            .map_err(|error| error.to_string())?,
    )?;
    let mut changes = staged_changes(repo)?;
    let max_bytes = max_file_mb.saturating_mul(1024 * 1024);
    let mut oversized = Vec::new();
    for change in changes.iter().filter(|change| {
        (change.status == b"A" || change.status == b"M" || change.status == b"T")
            && (change.mode == b"100644" || change.mode == b"100755")
    }) {
        let size = blob_size(repo, &change.blob)?;
        if size > max_bytes {
            let path = String::from_utf8_lossy(&change.path);
            eprintln!(
                "autosave: skipping oversized file {} ({} bytes)",
                path.escape_debug(),
                size
            );
            oversized.push(change.path.clone());
        }
    }
    if !oversized.is_empty() {
        let mut input = Vec::new();
        for path in oversized {
            input.extend(path);
            input.push(0);
        }
        let output = output_with_input(
            git_command(repo).args([
                "--literal-pathspecs",
                "restore",
                "--staged",
                "--pathspec-from-file=-",
                "--pathspec-file-nul",
            ]),
            &input,
        )?;
        checked(output)?;
        changes = staged_changes(repo)?;
    }
    if changes.is_empty() {
        return Ok(());
    }
    let message = format!("autosave {}", utc_timestamp()?);
    let output = git_command(repo)
        .args(["commit", "-q", "-m", &message])
        .output()
        .map_err(|error| error.to_string())?;
    checked(output)?;
    Ok(())
}

#[derive(Debug)]
struct RawChange {
    mode: Vec<u8>,
    blob: String,
    status: Vec<u8>,
    path: Vec<u8>,
}

fn staged_changes(repo: &Path) -> Result<Vec<RawChange>, String> {
    let output = git(repo, &["diff", "--cached", "--raw", "-z", "--no-renames"])?;
    parse_raw_changes(&output.stdout)
}

fn parse_raw_changes(raw: &[u8]) -> Result<Vec<RawChange>, String> {
    let mut changes = Vec::new();
    let mut fields = raw.split(|byte| *byte == 0);
    while let Some(header) = fields.next() {
        if header.is_empty() {
            continue;
        }
        let path = fields
            .next()
            .ok_or_else(|| "malformed git raw diff".to_owned())?;
        let values = header
            .split(|byte| byte.is_ascii_whitespace())
            .filter(|part| !part.is_empty())
            .collect::<Vec<_>>();
        if values.len() != 5 {
            return Err("malformed git raw diff header".into());
        }
        let mode = values[1].to_vec();
        let blob = String::from_utf8_lossy(values[3]).into_owned();
        let status = values[4].to_vec();
        changes.push(RawChange {
            mode,
            blob,
            status,
            path: path.to_vec(),
        });
    }
    Ok(changes)
}

fn blob_size(repo: &Path, oid: &str) -> Result<u64, String> {
    let output = git_command(repo)
        .args(["cat-file", "-s", oid])
        .output()
        .map_err(|error| error.to_string())?;
    check_output(&output)?;
    String::from_utf8_lossy(&output.stdout)
        .trim()
        .parse::<u64>()
        .map_err(|error| error.to_string())
}

fn scan_outgoing(repo: &Path, upstream: &str, branch: &str) -> Result<(), String> {
    let range = format!("{upstream}..{branch}");
    let commits = git_text(repo, &["rev-list", "--reverse", &range])?;
    let mut seen = HashSet::new();
    let mut blobs = Vec::new();
    for commit in commits.lines() {
        let output = git(
            repo,
            &[
                "diff-tree",
                "--root",
                "-m",
                "-r",
                "--raw",
                "-z",
                "--no-commit-id",
                "--no-renames",
                "--diff-filter=AMT",
                commit,
            ],
        )?;
        for change in parse_raw_changes(&output.stdout)? {
            if (change.mode == b"100644" || change.mode == b"100755")
                && seen.insert(change.blob.clone())
            {
                blobs.push(OutgoingBlob {
                    oid: change.blob,
                    path: String::from_utf8_lossy(&change.path).into_owned(),
                    commit: commit.to_owned(),
                });
            }
        }
    }
    if blobs.is_empty() {
        return Ok(());
    }

    let mut input = Vec::new();
    for blob in &blobs {
        input.extend(blob.oid.as_bytes());
        input.push(b'\n');
    }
    let output = output_with_input(git_command(repo).arg("cat-file").arg("--batch"), &input)?;
    check_output(&output)?;
    let contents = parse_batch(&output.stdout)?;
    // Pattern-only until the autosave plan wires value sources: a memory note that
    // happens to contain an ordinary `.env` value must not block the push.
    let redactor = Redactor::from_config(&Redact {
        values: false,
        ..Default::default()
    })
    .expect("default redaction config is valid");
    let mut hits = Vec::new();
    for (blob, bytes) in blobs.iter().zip(contents) {
        let Ok(text) = std::str::from_utf8(&bytes) else {
            continue;
        };
        if redact(&redactor, text).1 > 0 {
            hits.push(blob);
        }
    }
    for blob in &hits {
        eprintln!(
            "autosave: secret detected in {} (commit {})",
            blob.path.escape_debug(),
            blob.commit
        );
    }
    if hits.is_empty() {
        Ok(())
    } else {
        Err("outgoing commit scan found secret patterns; not pushing".into())
    }
}

#[derive(Debug)]
struct OutgoingBlob {
    oid: String,
    path: String,
    commit: String,
}

fn parse_batch(raw: &[u8]) -> Result<Vec<Vec<u8>>, String> {
    let mut blobs = Vec::new();
    let mut offset = 0;
    while offset < raw.len() {
        let header_end = raw[offset..]
            .iter()
            .position(|byte| *byte == b'\n')
            .map(|position| offset + position)
            .ok_or_else(|| "malformed git cat-file batch header".to_owned())?;
        let header = &raw[offset..header_end];
        let fields = header
            .split(|byte| byte.is_ascii_whitespace())
            .filter(|part| !part.is_empty())
            .collect::<Vec<_>>();
        if fields.len() != 3 || fields[1] != b"blob" {
            return Err("git cat-file returned a non-blob object".into());
        }
        let size = std::str::from_utf8(fields[2])
            .map_err(|error| error.to_string())?
            .parse::<usize>()
            .map_err(|error| error.to_string())?;
        let body_start = header_end + 1;
        let body_end = body_start
            .checked_add(size)
            .ok_or_else(|| "git blob size overflow".to_owned())?;
        if raw.get(body_end) != Some(&b'\n') {
            return Err("malformed git cat-file batch body".into());
        }
        blobs.push(raw[body_start..body_end].to_vec());
        offset = body_end + 1;
    }
    Ok(blobs)
}

fn redact(redactor: &Redactor, text: &str) -> (String, usize) {
    redactor.apply(text)
}

fn require_upstream(repo: &Path, branch: &str) -> Result<String, String> {
    let reference = format!("{branch}@{{upstream}}");
    git_text(repo, &["rev-parse", "--symbolic-full-name", &reference])
        .map_err(|_| format!("no upstream configured for branch {branch}"))
}

fn store_root(repo: &str) -> Result<PathBuf, String> {
    let repo = Path::new(repo)
        .canonicalize()
        .map_err(|_| format!("not a git repo: {repo}"))?;
    let mut ancestor = repo.parent();
    while let Some(path) = ancestor {
        if path.join(".git").exists() {
            return Err(format!(
                "inside a code repo at {}; autosave commits all non-ignored files and could commit work in progress to its history",
                path.display()
            ));
        }
        ancestor = path.parent();
    }
    let root = git_text(&repo, &["rev-parse", "--show-toplevel"])
        .map_err(|_| format!("not a git repo: {}", repo.display()))?;
    let root = Path::new(&root)
        .canonicalize()
        .map_err(|_| format!("not a git repo: {}", repo.display()))?;
    if root != repo {
        return Err(format!(
            "not a git repo root: {} (Git root is {})",
            repo.display(),
            root.display()
        ));
    }
    Ok(repo)
}

fn in_progress(repo: &Path) -> Result<bool, String> {
    for state in [
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REBASE_HEAD",
        "rebase-merge",
        "rebase-apply",
    ] {
        let path = git_text(repo, &["rev-parse", "--git-path", state])?;
        let path = PathBuf::from(path);
        let path = if path.is_absolute() {
            path
        } else {
            repo.join(path)
        };
        if path.exists() {
            return Ok(true);
        }
    }
    Ok(false)
}

fn index_lock(repo: &Path) -> Result<PathBuf, String> {
    let path = git_text(repo, &["rev-parse", "--git-path", "index.lock"])?;
    let path = PathBuf::from(path);
    Ok(if path.is_absolute() {
        path
    } else {
        repo.join(path)
    })
}

fn is_index_lock_error(error: &str) -> bool {
    error.contains("index.lock")
}

struct JobPaths {
    plist_dir: PathBuf,
    plist: PathBuf,
    log: PathBuf,
}

impl JobPaths {
    fn new(repo: &Path) -> Result<Self, String> {
        let id = repo_id(repo);
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .ok_or_else(|| "HOME is not set".to_owned())?;
        let plist_dir = std::env::var_os(TEST_PLIST_DIR)
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join("Library/LaunchAgents"));
        let plist = plist_dir.join(format!("varde-autosave-{id}.plist"));
        let log_dir = if std::env::var_os(TEST_PLIST_DIR).is_some() {
            plist_dir.parent().unwrap_or(&plist_dir).join("logs")
        } else {
            home.join("Library/Logs")
        };
        Ok(Self {
            plist_dir,
            plist,
            log: log_dir.join(format!("varde-autosave-{id}.log")),
        })
    }
}

fn repo_id(repo: &Path) -> String {
    let digest = Sha256::digest(repo.to_string_lossy().as_bytes());
    digest[..6]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn render_plist(
    repo: &Path,
    branch: &str,
    interval_minutes: u64,
    max_file_mb: u64,
    paths: &JobPaths,
) -> Result<String, String> {
    let id = repo_id(repo);
    let label = format!("varde-autosave-{id}");
    let executable = std::env::current_exe().map_err(|error| error.to_string())?;
    let mut arguments = vec![
        executable.to_string_lossy().into_owned(),
        "setup".into(),
        "autosave".into(),
        "run".into(),
        "--repo".into(),
        repo.to_string_lossy().into_owned(),
    ];
    if branch != DEFAULT_BRANCH {
        arguments.extend(["--branch".into(), branch.into()]);
    }
    if max_file_mb != DEFAULT_MAX_FILE_MB {
        arguments.extend(["--max-file-mb".into(), max_file_mb.to_string()]);
    }
    let path = std::env::var("PATH").unwrap_or_default();
    let mut plist = String::from(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n<plist version=\"1.0\">\n<dict>\n",
    );
    plist.push_str(&format!(
        "  <key>Label</key><string>{}</string>\n  <key>ProgramArguments</key><array>\n",
        xml(&label)
    ));
    for argument in arguments {
        plist.push_str(&format!("    <string>{}</string>\n", xml(&argument)));
    }
    plist.push_str(&format!(
        "  </array>\n  <key>StartInterval</key><integer>{}</integer>\n  <key>RunAtLoad</key><false/>\n  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{}</string></dict>\n  <key>StandardOutPath</key><string>{}</string>\n  <key>StandardErrorPath</key><string>{}</string>\n</dict>\n</plist>\n",
        interval_minutes.saturating_mul(60),
        xml(&path),
        xml(&paths.log.to_string_lossy()),
        xml(&paths.log.to_string_lossy()),
    ));
    Ok(plist)
}

fn xml(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

fn gui_domain() -> Result<String, String> {
    let output = ProcessCommand::new("id")
        .arg("-u")
        .output()
        .map_err(|error| error.to_string())?;
    check_output(&output)?;
    Ok(format!(
        "gui/{}",
        String::from_utf8_lossy(&output.stdout).trim()
    ))
}

trait Launchd {
    fn bootstrap(&self, domain: &str, plist: &Path) -> Result<(), String>;
    fn bootout(&self, domain: &str, plist: &Path) -> Result<(), String>;
}

struct Launchctl {
    executable: OsString,
    test_fake: bool,
}

impl Launchctl {
    fn from_env() -> Self {
        match std::env::var_os(TEST_LAUNCHCTL) {
            Some(executable) => Self {
                executable,
                test_fake: true,
            },
            None => Self {
                executable: OsString::from("launchctl"),
                test_fake: false,
            },
        }
    }

    fn is_test_fake(&self) -> bool {
        self.test_fake
    }

    fn call(&self, action: &str, domain: &str, plist: &Path) -> Result<(), String> {
        let output = ProcessCommand::new(&self.executable)
            .arg(action)
            .arg(domain)
            .arg(plist)
            .output()
            .map_err(|error| error.to_string())?;
        check_output(&output)
    }
}

impl Launchd for Launchctl {
    fn bootstrap(&self, domain: &str, plist: &Path) -> Result<(), String> {
        self.call("bootstrap", domain, plist)
    }

    fn bootout(&self, domain: &str, plist: &Path) -> Result<(), String> {
        self.call("bootout", domain, plist)
    }
}

fn missing_launchd_job(error: &str) -> bool {
    error.contains("Could not find service") || error.contains("No such process")
}

fn utc_timestamp() -> Result<String, String> {
    let output = ProcessCommand::new("date")
        .args(["-u", "+%Y-%m-%dT%H:%M:%SZ"])
        .output()
        .map_err(|error| error.to_string())?;
    check_output(&output)?;
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn git_command(repo: &Path) -> ProcessCommand {
    let mut command = ProcessCommand::new("git");
    command.arg("-C").arg(repo);
    command
}

fn git(repo: &Path, args: &[&str]) -> Result<Output, String> {
    let output = git_command(repo)
        .args(args)
        .output()
        .map_err(|error| error.to_string())?;
    checked(output)
}

fn git_text(repo: &Path, args: &[&str]) -> Result<String, String> {
    let output = git(repo, args)?;
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn output_with_input(command: &mut ProcessCommand, input: &[u8]) -> Result<Output, String> {
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| error.to_string())?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| "failed to open child stdin".to_owned())?;
    let input = input.to_vec();
    let writer = std::thread::spawn(move || stdin.write_all(&input));
    let output = child
        .wait_with_output()
        .map_err(|error| error.to_string())?;
    let write_result = writer
        .join()
        .map_err(|_| "failed to write child stdin".to_owned())?;
    if let Err(error) = write_result {
        if output.status.success() {
            return Err(error.to_string());
        }
    }
    Ok(output)
}

fn checked(output: Output) -> Result<Output, String> {
    check_output(&output)?;
    Ok(output)
}

fn check_output(output: &Output) -> Result<(), String> {
    if output.status.success() {
        return Ok(());
    }
    let error = String::from_utf8_lossy(&output.stderr).trim().to_owned();
    Err(if error.is_empty() {
        format!("command exited with {}", output.status)
    } else {
        error
    })
}
