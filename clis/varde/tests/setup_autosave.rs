use std::fs;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::thread;
use std::time::{Duration, Instant};
use tempfile::TempDir;

struct Store {
    _temp: TempDir,
    repo: PathBuf,
    remote: PathBuf,
}

struct TestEnv {
    plist_dir: PathBuf,
    launchctl: PathBuf,
    launchctl_log: PathBuf,
}

fn git(repo: &Path, args: &[&str]) -> Output {
    let output = Command::new("git")
        .arg("-C")
        .arg(repo)
        .args(args)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "git {args:?} failed:\n{}",
        String::from_utf8_lossy(&output.stderr)
    );
    output
}

fn git_with_input(repo: &Path, args: &[&str], input: &[u8]) -> Output {
    let mut child = Command::new("git")
        .arg("-C")
        .arg(repo)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(input).unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "git {args:?} failed:\n{}",
        String::from_utf8_lossy(&output.stderr)
    );
    output
}

fn git_text(repo: &Path, args: &[&str]) -> String {
    String::from_utf8(git(repo, args).stdout)
        .unwrap()
        .trim()
        .to_owned()
}

fn git_allow_failure(repo: &Path, args: &[&str]) -> Output {
    Command::new("git")
        .arg("-C")
        .arg(repo)
        .args(args)
        .output()
        .unwrap()
}

fn init_repo(repo: &Path) {
    fs::create_dir_all(repo).unwrap();
    let output = Command::new("git")
        .args(["init", "--initial-branch=main"])
        .arg(repo)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    git(repo, &["config", "user.name", "Autosave Test"]);
    git(repo, &["config", "user.email", "autosave@example.invalid"]);
    git(repo, &["config", "commit.gpgsign", "false"]);
}

fn store() -> Store {
    let temp = tempfile::tempdir().unwrap();
    let repo = temp.path().join("store");
    let remote = temp.path().join("remote.git");
    let output = Command::new("git")
        .args(["init", "--bare", "--initial-branch=main"])
        .arg(&remote)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    init_repo(&repo);
    fs::write(repo.join("initial.txt"), "initial\n").unwrap();
    git(&repo, &["add", "initial.txt"]);
    git(&repo, &["commit", "-m", "initial"]);
    git(
        &repo,
        &["remote", "add", "origin", remote.to_str().unwrap()],
    );
    git(&repo, &["push", "--set-upstream", "origin", "main"]);
    Store {
        _temp: temp,
        repo,
        remote,
    }
}

fn test_env(root: &Path) -> TestEnv {
    let bin = root.join("fake-bin");
    fs::create_dir_all(&bin).unwrap();
    let launchctl = bin.join("launchctl-recording-fake");
    fs::write(
        &launchctl,
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$VARDE_AUTOSAVE_TEST_LAUNCHCTL_LOG\"\n",
    )
    .unwrap();
    fs::set_permissions(&launchctl, fs::Permissions::from_mode(0o755)).unwrap();
    TestEnv {
        plist_dir: root.join("launchagents"),
        launchctl,
        launchctl_log: root.join("launchctl.log"),
    }
}

fn varde_command(args: &[&str], repo: &Path, env: &TestEnv, fake_launchd: bool) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_varde"));
    command
        .args(args)
        .arg("--repo")
        .arg(repo)
        .env_remove("VARDE_AUTOSAVE_TEST_PLIST_DIR")
        .env_remove("VARDE_AUTOSAVE_TEST_LAUNCHCTL")
        .env_remove("VARDE_AUTOSAVE_TEST_LAUNCHCTL_LOG")
        .env("VARDE_AUTOSAVE_TEST_PLIST_DIR", &env.plist_dir);
    if fake_launchd {
        command
            .env("VARDE_AUTOSAVE_TEST_LAUNCHCTL", &env.launchctl)
            .env("VARDE_AUTOSAVE_TEST_LAUNCHCTL_LOG", &env.launchctl_log);
    }
    command
}

fn varde(args: &[&str], repo: &Path, env: &TestEnv, fake_launchd: bool) -> Output {
    varde_command(args, repo, env, fake_launchd)
        .output()
        .unwrap()
}

fn varde_with_timeout(
    args: &[&str],
    repo: &Path,
    env: &TestEnv,
    timeout: Duration,
) -> (Output, bool) {
    let mut child = varde_command(args, repo, env, false).spawn().unwrap();
    let started = Instant::now();
    let mut timed_out = false;
    loop {
        if child.try_wait().unwrap().is_some() {
            break;
        }
        if started.elapsed() >= timeout {
            timed_out = true;
            child.kill().unwrap();
            break;
        }
        thread::sleep(Duration::from_millis(20));
    }
    (child.wait_with_output().unwrap(), timed_out)
}

fn setup_nightly(store: &Store) {
    git(&store.repo, &["checkout", "-b", "nightly"]);
    git(
        &store.repo,
        &["branch", "--set-upstream-to=origin/main", "nightly"],
    );
}

fn assert_ok(output: &Output) {
    assert!(
        output.status.success(),
        "status {:?}\nstdout:\n{}\nstderr:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

fn assert_err(output: &Output) {
    assert!(
        !output.status.success(),
        "expected failure, got stdout:\n{}\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

fn output_text(output: &Output) -> String {
    format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    )
}

fn head(repo: &Path) -> String {
    git_text(repo, &["rev-parse", "HEAD"])
}

#[test]
fn run_commits_and_pushes() {
    let store = store();
    let env = test_env(store._temp.path());
    fs::write(store.repo.join("initial.txt"), "modified\n").unwrap();
    fs::write(store.repo.join("new.txt"), "new\n").unwrap();

    let output = varde(&["setup", "autosave", "run"], &store.repo, &env, false);
    assert_ok(&output);
    assert_eq!(
        git_text(&store.repo, &["rev-parse", "HEAD"]),
        git_text(&store.remote, &["rev-parse", "refs/heads/main"])
    );
    assert!(
        git_text(&store.repo, &["show", "--format=", "--name-only", "HEAD"])
            .lines()
            .any(|line| line == "initial.txt")
    );
    assert!(
        git_text(&store.repo, &["show", "--format=", "--name-only", "HEAD"])
            .lines()
            .any(|line| line == "new.txt")
    );
    assert!(git_text(&store.repo, &["log", "-1", "--format=%s", "HEAD"]).starts_with("autosave "));
}

#[test]
fn skips_ignored_and_oversized() {
    let store = store();
    let env = test_env(store._temp.path());
    fs::write(store.repo.join(".gitignore"), "baseline/\n").unwrap();
    fs::create_dir_all(store.repo.join("baseline")).unwrap();
    fs::write(store.repo.join("baseline/ignored.txt"), "ignored\n").unwrap();
    fs::write(store.repo.join("large.bin"), vec![b'x'; 1024 * 1024 + 1]).unwrap();
    fs::write(store.repo.join("small.bin"), b"small file\n").unwrap();

    let output = varde(
        &["setup", "autosave", "run", "--max-file-mb", "1"],
        &store.repo,
        &env,
        false,
    );
    assert_ok(&output);
    let text = output_text(&output);
    assert!(text.contains("large.bin"), "{text}");
    assert!(text.to_lowercase().contains("oversized"), "{text}");
    let committed = git_text(&store.repo, &["show", "--format=", "--name-only", "HEAD"]);
    assert!(!committed.contains("baseline/ignored.txt"));
    assert!(!committed.contains("large.bin"));
    assert!(committed.contains("small.bin"));
    assert!(git_text(&store.repo, &["status", "--porcelain"]).contains("large.bin"));
    assert!(!git_text(&store.repo, &["status", "--porcelain"]).contains("small.bin"));
    assert_eq!(
        git_text(&store.repo, &["rev-parse", "HEAD"]),
        git_text(&store.remote, &["rev-parse", "refs/heads/main"])
    );
}

#[test]
fn guards_and_append_only() {
    let other = store();
    let other_env = test_env(other._temp.path());
    let before = head(&other.repo);
    git(&other.repo, &["checkout", "-b", "topic"]);
    let output = varde(
        &["setup", "autosave", "run"],
        &other.repo,
        &other_env,
        false,
    );
    assert_ok(&output);
    assert!(output_text(&output).contains("not on branch main"));
    assert_eq!(head(&other.repo), before);
    assert_eq!(
        git_text(&other.remote, &["rev-parse", "refs/heads/main"]),
        before
    );

    let rebasing = store();
    let rebase_env = test_env(rebasing._temp.path());
    let rebase_state = PathBuf::from(git_text(
        &rebasing.repo,
        &["rev-parse", "--git-path", "rebase-merge"],
    ));
    let rebase_state = if rebase_state.is_absolute() {
        rebase_state
    } else {
        rebasing.repo.join(rebase_state)
    };
    fs::create_dir_all(rebase_state).unwrap();
    let before = head(&rebasing.repo);
    let output = varde(
        &["setup", "autosave", "run"],
        &rebasing.repo,
        &rebase_env,
        false,
    );
    assert_ok(&output);
    assert!(output_text(&output).contains("merge or rebase in progress"));
    assert_eq!(head(&rebasing.repo), before);
    assert_eq!(
        git_text(&rebasing.remote, &["rev-parse", "refs/heads/main"]),
        before
    );

    let diverged = store();
    let diverged_env = test_env(diverged._temp.path());
    fs::write(diverged.repo.join("local.txt"), "local\n").unwrap();
    git(&diverged.repo, &["add", "local.txt"]);
    git(&diverged.repo, &["commit", "-m", "local change"]);
    fs::write(
        diverged.repo.join("pending.txt"),
        "pending during divergence\n",
    )
    .unwrap();
    let clone = diverged._temp.path().join("other-clone");
    let output = Command::new("git")
        .args(["clone", "--branch", "main"])
        .arg(&diverged.remote)
        .arg(&clone)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    git(&clone, &["config", "user.name", "Autosave Test"]);
    git(
        &clone,
        &["config", "user.email", "autosave@example.invalid"],
    );
    fs::write(clone.join("remote.txt"), "remote\n").unwrap();
    git(&clone, &["add", "remote.txt"]);
    git(&clone, &["commit", "-m", "remote change"]);
    git(&clone, &["push"]);
    let old_head = head(&diverged.repo);
    let output = varde(
        &["setup", "autosave", "run"],
        &diverged.repo,
        &diverged_env,
        false,
    );
    assert_err(&output);
    assert!(output_text(&output).contains("remote diverged; not pushing"));
    let new_head = head(&diverged.repo);
    assert!(
        git_allow_failure(
            &diverged.repo,
            &["merge-base", "--is-ancestor", &old_head, &new_head]
        )
        .status
        .success()
    );
    assert_ne!(new_head, old_head);
    assert!(
        git_text(
            &diverged.repo,
            &["show", "--format=", "--name-only", "HEAD"]
        )
        .lines()
        .any(|line| line == "pending.txt")
    );
    assert_eq!(
        git_text(&diverged.remote, &["rev-parse", "refs/heads/main"]),
        git_text(&clone, &["rev-parse", "HEAD"])
    );
}

#[test]
fn skips_on_index_lock() {
    let store = store();
    let env = test_env(store._temp.path());
    fs::write(store.repo.join("pending.txt"), "pending\n").unwrap();
    fs::write(store.repo.join(".git/index.lock"), "").unwrap();
    let before = head(&store.repo);

    let output = varde(&["setup", "autosave", "run"], &store.repo, &env, false);
    assert_ok(&output);
    let text = output_text(&output);
    assert!(text.contains("index.lock"), "{text}");
    assert_eq!(text.lines().count(), 1, "{text}");
    assert_eq!(head(&store.repo), before);
    assert_eq!(
        git_text(&store.remote, &["rev-parse", "refs/heads/main"]),
        before
    );
}

#[test]
fn requires_upstream() {
    let temp = tempfile::tempdir().unwrap();
    let repo = temp.path().join("store");
    let env = test_env(temp.path());
    init_repo(&repo);
    fs::write(repo.join("initial.txt"), "initial\n").unwrap();
    git(&repo, &["add", "initial.txt"]);
    git(&repo, &["commit", "-m", "initial"]);
    fs::write(repo.join("pending.txt"), "pending\n").unwrap();

    let run = varde(&["setup", "autosave", "run"], &repo, &env, false);
    assert_err(&run);
    assert!(output_text(&run).contains("no upstream"));
    assert_eq!(
        git_text(&repo, &["status", "--porcelain"]).lines().count(),
        1
    );
    let install = varde(&["setup", "autosave", "install"], &repo, &env, false);
    assert_err(&install);
    assert!(output_text(&install).contains("no upstream"));
    assert!(!env.plist_dir.exists());
}

#[test]
fn blocks_push_on_secret() {
    let store = store();
    let env = test_env(store._temp.path());
    let secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyz";
    fs::write(store.repo.join("agent.txt"), format!("token={secret}\n")).unwrap();
    git(&store.repo, &["add", "agent.txt"]);
    git(&store.repo, &["commit", "-m", "agent path commit"]);
    let agent_commit = head(&store.repo);
    let remote_before = git_text(&store.remote, &["rev-parse", "refs/heads/main"]);
    fs::write(store.repo.join("later.txt"), "clean autosave change\n").unwrap();

    let output = varde(&["setup", "autosave", "run"], &store.repo, &env, false);
    assert_err(&output);
    let text = output_text(&output);
    assert!(text.contains("agent.txt"), "{text}");
    assert!(text.contains(&agent_commit), "{text}");
    assert!(!text.contains(secret), "{text}");
    let new_head = head(&store.repo);
    assert_ne!(
        new_head, agent_commit,
        "the tick must create its autosave commit"
    );
    assert!(
        git_text(&store.repo, &["show", "--format=", "--name-only", "HEAD"])
            .lines()
            .any(|line| line == "later.txt")
    );
    assert_eq!(
        git_text(&store.remote, &["rev-parse", "refs/heads/main"]),
        remote_before
    );
}

#[test]
fn does_not_block_push_on_an_ordinary_dotenv_value() {
    let store = store();
    let env = test_env(store._temp.path());
    // `SSH_KEY` is secret-named and its value is ordinary. With value sources
    // enabled this `.env` entry would block any outgoing blob that contains
    // `localhost:5432`, so the push scan must stay pattern-only.
    fs::write(store.repo.join(".env"), "SSH_KEY=localhost:5432\n").unwrap();
    fs::write(
        store.repo.join("note.txt"),
        "the dev database listens on localhost:5432\n",
    )
    .unwrap();
    git(&store.repo, &["add", ".env", "note.txt"]);
    git(&store.repo, &["commit", "-m", "ordinary dotenv value"]);
    fs::write(store.repo.join("later.txt"), "clean autosave change\n").unwrap();

    // Run from the repo so `.env` discovery would see the ordinary value.
    let output = varde_command(&["setup", "autosave", "run"], &store.repo, &env, false)
        .current_dir(&store.repo)
        .output()
        .unwrap();
    assert_ok(&output);
    assert_eq!(
        git_text(&store.repo, &["rev-parse", "HEAD"]),
        git_text(&store.remote, &["rev-parse", "refs/heads/main"])
    );
}

#[test]
fn scans_large_outgoing_range_without_hanging() {
    let store = store();
    let env = test_env(store._temp.path());
    const BLOB_COUNT: usize = 27_000;
    let message = "large outgoing range";
    let parent = head(&store.repo);
    let mut input = format!(
        "commit refs/heads/main\nauthor Autosave Test <autosave@example.invalid> 1 +0000\ncommitter Autosave Test <autosave@example.invalid> 1 +0000\ndata {}\n{}\nfrom {parent}\n",
        message.len(),
        message
    )
    .into_bytes();
    for index in 0..BLOB_COUNT {
        let mut blob = [0xff; 9];
        blob[1..].copy_from_slice(&(index as u64).to_be_bytes());
        input.extend_from_slice(
            format!(
                "M 100644 inline outgoing-{index:05}.txt\ndata {}\n",
                blob.len()
            )
            .as_bytes(),
        );
        input.extend_from_slice(&blob);
        input.push(b'\n');
    }
    input.push(b'\n');
    git_with_input(&store.repo, &["fast-import", "--quiet"], &input);

    let (output, timed_out) = varde_with_timeout(
        &["setup", "autosave", "run", "--scan-only"],
        &store.repo,
        &env,
        Duration::from_secs(30),
    );
    assert!(
        !timed_out,
        "scan-only timed out on {BLOB_COUNT} distinct blobs"
    );
    assert_ok(&output);
}

#[cfg(unix)]
#[test]
fn scans_symlink_to_regular_type_change() {
    let store = store();
    let env = test_env(store._temp.path());
    std::os::unix::fs::symlink("target", store.repo.join("link.txt")).unwrap();
    git(&store.repo, &["add", "link.txt"]);
    git(&store.repo, &["commit", "-m", "add symlink"]);
    git(&store.repo, &["push"]);

    fs::remove_file(store.repo.join("link.txt")).unwrap();
    let secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyz";
    fs::write(store.repo.join("link.txt"), format!("token={secret}\n")).unwrap();
    git(&store.repo, &["add", "link.txt"]);
    git(&store.repo, &["commit", "-m", "replace symlink with file"]);
    let type_change = head(&store.repo);

    let output = varde(
        &["setup", "autosave", "run", "--scan-only"],
        &store.repo,
        &env,
        false,
    );
    assert_err(&output);
    let text = output_text(&output);
    assert!(text.contains("link.txt"), "{text}");
    assert!(text.contains(&type_change), "{text}");
    assert!(!text.contains(secret), "{text}");
}

#[cfg(unix)]
#[test]
fn skips_oversized_symlink_to_regular_type_change() {
    let store = store();
    let env = test_env(store._temp.path());
    std::os::unix::fs::symlink("target", store.repo.join("link.bin")).unwrap();
    git(&store.repo, &["add", "link.bin"]);
    git(&store.repo, &["commit", "-m", "add symlink"]);
    git(&store.repo, &["push"]);
    let before = head(&store.repo);

    fs::remove_file(store.repo.join("link.bin")).unwrap();
    fs::write(store.repo.join("link.bin"), vec![b'x'; 1024 * 1024 + 1]).unwrap();
    let output = varde(
        &["setup", "autosave", "run", "--max-file-mb", "1"],
        &store.repo,
        &env,
        false,
    );
    assert_ok(&output);
    let text = output_text(&output);
    assert!(text.contains("link.bin"), "{text}");
    assert!(text.to_lowercase().contains("oversized"), "{text}");
    assert_eq!(head(&store.repo), before);
    assert!(git_text(&store.repo, &["status", "--porcelain"]).contains("link.bin"));
}

#[test]
fn oversized_glob_path_does_not_unstage_matching_small_file() {
    let store = store();
    let env = test_env(store._temp.path());
    fs::write(store.repo.join("a[bc].bin"), vec![b'x'; 2 * 1024 * 1024]).unwrap();
    fs::write(store.repo.join("ab.bin"), b"small matching file\n").unwrap();

    let output = varde(
        &["setup", "autosave", "run", "--max-file-mb", "1"],
        &store.repo,
        &env,
        false,
    );
    assert_ok(&output);
    let text = output_text(&output);
    assert!(text.contains("a[bc].bin"), "{text}");
    let committed = git_text(&store.repo, &["show", "--format=", "--name-only", "HEAD"]);
    assert!(
        committed.lines().any(|line| line == "ab.bin"),
        "{committed}"
    );
    assert!(
        !committed.lines().any(|line| line == "a[bc].bin"),
        "{committed}"
    );
    let status = git_text(&store.repo, &["status", "--porcelain"]);
    assert!(status.contains("a[bc].bin"), "{status}");
    assert!(!status.contains("ab.bin"), "{status}");
}

#[test]
fn oversized_newline_path_is_logged_as_one_line() {
    let store = store();
    let env = test_env(store._temp.path());
    fs::write(store.repo.join("large\n.bin"), b"large\n").unwrap();

    let output = varde(
        &["setup", "autosave", "run", "--max-file-mb", "0"],
        &store.repo,
        &env,
        false,
    );
    assert_ok(&output);
    let text = output_text(&output);
    assert!(text.contains("large\\n.bin"), "{text:?}");
    assert!(!text.contains("large\n.bin"), "{text:?}");
    assert_eq!(text.lines().count(), 1, "{text:?}");
}

#[test]
fn scan_only_scans_requested_branch_before_tick_guards() {
    let store = store();
    let env = test_env(store._temp.path());
    let secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyz";
    fs::write(store.repo.join("branch-secret.txt"), secret).unwrap();
    git(&store.repo, &["add", "branch-secret.txt"]);
    git(&store.repo, &["commit", "-m", "secret on requested branch"]);
    let secret_commit = head(&store.repo);
    git(&store.repo, &["checkout", "-b", "topic"]);

    let output = varde(
        &[
            "setup",
            "autosave",
            "run",
            "--branch",
            "main",
            "--scan-only",
        ],
        &store.repo,
        &env,
        false,
    );
    assert_err(&output);
    let text = output_text(&output);
    assert!(text.contains("branch-secret.txt"), "{text}");
    assert!(text.contains(&secret_commit), "{text}");
    assert!(!text.contains(secret), "{text}");
    assert_eq!(head(&store.repo), secret_commit);
}

#[test]
fn rejects_zero_install_interval() {
    let store = store();
    let env = test_env(store._temp.path());
    let output = varde(
        &[
            "setup",
            "autosave",
            "install",
            "--interval-minutes",
            "0",
            "--dry-run",
        ],
        &store.repo,
        &env,
        false,
    );
    assert_err(&output);
    assert!(!output_text(&output).contains("<integer>0</integer>"));
}

#[test]
fn scan_only() {
    let store = store();
    let env = test_env(store._temp.path());
    let secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyz";
    fs::write(store.repo.join("agent.txt"), format!("token={secret}\n")).unwrap();
    fs::write(store.repo.join("binary.dat"), [0xff, 0xfe, 0xfd]).unwrap();
    #[cfg(unix)]
    std::os::unix::fs::symlink("agent.txt", store.repo.join("linked.txt")).unwrap();
    git(
        &store.repo,
        &["add", "agent.txt", "binary.dat", "linked.txt"],
    );
    git(&store.repo, &["commit", "-m", "outgoing fixtures"]);
    let dirty = store.repo.join("dirty.txt");
    fs::write(&dirty, "must stay dirty\n").unwrap();
    let before = head(&store.repo);
    let output = varde(
        &["setup", "autosave", "run", "--scan-only"],
        &store.repo,
        &env,
        false,
    );
    assert_err(&output);
    let text = output_text(&output);
    assert!(text.contains("agent.txt"), "{text}");
    assert!(!text.contains("binary.dat"), "{text}");
    assert!(!text.contains("linked.txt"), "{text}");
    assert!(!text.contains(secret), "{text}");
    assert_eq!(head(&store.repo), before);
    assert!(git_text(&store.repo, &["status", "--porcelain"]).contains("dirty.txt"));
    assert_eq!(
        git_text(&store.remote, &["rev-parse", "refs/heads/main"]),
        git_text(&store.repo, &["rev-parse", "refs/remotes/origin/main"])
    );

    git(&store.repo, &["push"]);
    let clean_range = varde(
        &["setup", "autosave", "run", "--scan-only"],
        &store.repo,
        &env,
        false,
    );
    assert_ok(&clean_range);
    assert_eq!(head(&store.repo), before);
    assert!(git_text(&store.repo, &["status", "--porcelain"]).contains("dirty.txt"));
}

#[test]
fn scans_secrets_in_merge_commits() {
    let store = store();
    let env = test_env(store._temp.path());
    git(&store.repo, &["checkout", "-b", "feature"]);
    let secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyz";
    fs::write(store.repo.join("conflict.txt"), "feature version\n").unwrap();
    git(&store.repo, &["add", "conflict.txt"]);
    git(&store.repo, &["commit", "-m", "feature change"]);
    git(&store.repo, &["checkout", "main"]);
    fs::write(store.repo.join("conflict.txt"), "main version\n").unwrap();
    git(&store.repo, &["add", "conflict.txt"]);
    git(&store.repo, &["commit", "-m", "main change"]);
    let merge = git_allow_failure(&store.repo, &["merge", "--no-ff", "feature"]);
    assert!(
        !merge.status.success(),
        "the fixture must produce a merge conflict"
    );
    fs::write(store.repo.join("conflict.txt"), secret).unwrap();
    git(&store.repo, &["add", "conflict.txt"]);
    git(&store.repo, &["commit", "-m", "resolve merge with secret"]);
    let merge_commit = head(&store.repo);

    let output = varde(
        &["setup", "autosave", "run", "--scan-only"],
        &store.repo,
        &env,
        false,
    );
    assert_err(&output);
    let text = output_text(&output);
    assert!(text.contains("conflict.txt"), "{text}");
    assert!(text.contains(&merge_commit), "{text}");
    assert!(!text.contains(secret), "{text}");
}

#[test]
fn scans_paths_with_spaces_and_newlines() {
    let store = store();
    let env = test_env(store._temp.path());
    let secret = "ghp_0123456789abcdefghijklmnopqrstuvwxyz";
    let second_secret = "ghp_0123456789abcdefghijklmno12345678901";
    fs::create_dir_all(store.repo.join("odd path")).unwrap();
    fs::write(store.repo.join("odd path/with space.txt"), second_secret).unwrap();
    let newline_path = store.repo.join("odd path/line\nbreak.txt");
    fs::write(&newline_path, secret).unwrap();
    git(&store.repo, &["add", "-A"]);
    git(&store.repo, &["commit", "-m", "odd path fixtures"]);

    let output = varde(
        &["setup", "autosave", "run", "--scan-only"],
        &store.repo,
        &env,
        false,
    );
    assert_err(&output);
    let text = output_text(&output);
    assert!(text.contains("odd path/with space.txt"), "{text}");
    assert!(text.contains("odd path/line\\nbreak.txt"), "{text:?}");
    assert!(!text.contains("odd path/line\nbreak.txt"), "{text:?}");
    assert!(!text.contains(secret), "{text}");
    assert!(!text.contains(second_secret), "{text}");
}

#[test]
fn refuses_store_inside_code_repo() {
    let temp = tempfile::tempdir().unwrap();
    let code_repo = temp.path().join("code");
    let nested = code_repo.join("memory");
    let env = test_env(temp.path());
    init_repo(&code_repo);
    fs::write(code_repo.join("README.md"), "code\n").unwrap();
    git(&code_repo, &["add", "README.md"]);
    git(&code_repo, &["commit", "-m", "code repo"]);
    init_repo(&nested);
    fs::write(nested.join("pending.txt"), "pending\n").unwrap();
    git(&nested, &["add", "pending.txt"]);
    git(&nested, &["commit", "-m", "nested store"]);
    let before = head(&nested);

    for args in [
        vec!["setup", "autosave", "install", "--dry-run"],
        vec!["setup", "autosave", "install"],
        vec!["setup", "autosave", "run"],
    ] {
        let output = varde(&args, &nested, &env, false);
        assert_err(&output);
        let text = output_text(&output);
        assert!(text.contains("inside a code repo"), "{text}");
        assert!(text.contains(code_repo.to_str().unwrap()), "{text}");
        assert_eq!(head(&nested), before);
    }
    assert!(!env.plist_dir.exists());
    assert!(!env.launchctl_log.exists());
}

#[test]
fn refuses_non_git_store() {
    let temp = tempfile::tempdir().unwrap();
    let repo = temp.path().join("not-a-repo");
    fs::create_dir_all(&repo).unwrap();
    let env = test_env(temp.path());

    for args in [
        vec!["setup", "autosave", "install"],
        vec!["setup", "autosave", "run"],
    ] {
        let output = varde(&args, &repo, &env, false);
        assert_err(&output);
        assert!(output_text(&output).contains("not a git repo"));
    }
    assert!(!env.plist_dir.exists());
}

#[test]
fn install_dry_run_allowed() {
    let store = store();
    let env = test_env(store._temp.path());
    setup_nightly(&store);
    let output = varde(
        &[
            "setup",
            "autosave",
            "install",
            "--branch",
            "nightly",
            "--interval-minutes",
            "45",
            "--max-file-mb",
            "7",
            "--dry-run",
        ],
        &store.repo,
        &env,
        false,
    );
    assert_ok(&output);
    let text = output_text(&output);
    assert!(text.contains("varde-autosave-"), "{text}");
    assert!(text.contains("<string>setup</string>"), "{text}");
    assert!(text.contains("<string>autosave</string>"), "{text}");
    assert!(text.contains("<string>run</string>"), "{text}");
    assert!(text.contains("<integer>2700</integer>"), "{text}");
    assert!(text.contains("<key>RunAtLoad</key><false/>"), "{text}");
    let path = std::env::var("PATH").unwrap_or_default();
    assert!(
        text.contains(&format!("<key>PATH</key><string>{path}</string>")),
        "{text}"
    );
    assert!(text.contains("<string>--repo</string>"), "{text}");
    assert!(
        text.contains("<string>--branch</string>\n    <string>nightly</string>"),
        "{text}"
    );
    assert!(
        text.contains("<string>--max-file-mb</string>\n    <string>7</string>"),
        "{text}"
    );
    let repo = store.repo.canonicalize().unwrap();
    assert!(
        text.contains(&format!("<string>{}</string>", repo.display())),
        "{text}"
    );
    let label = text
        .split_once("<key>Label</key><string>")
        .and_then(|(_, rest)| rest.split_once("</string>"))
        .map(|(label, _)| label)
        .unwrap_or_default();
    assert!(label.starts_with("varde-autosave-"), "{text}");
    let id = label.trim_start_matches("varde-autosave-");
    assert_eq!(id.len(), 12, "{text}");
    assert!(
        id.chars().all(|character| character.is_ascii_hexdigit()),
        "{text}"
    );
    let log_path = env
        .plist_dir
        .parent()
        .unwrap()
        .join("logs")
        .join(format!("varde-autosave-{id}.log"));
    let log_path = format!("<string>{}</string>", log_path.display());
    assert!(
        text.contains(&format!("<key>StandardOutPath</key>{log_path}")),
        "{text}"
    );
    assert!(
        text.contains(&format!("<key>StandardErrorPath</key>{log_path}")),
        "{text}"
    );
    assert!(!env.plist_dir.exists());
    assert!(!env.launchctl_log.exists());
}

#[test]
fn install_uninstall_with_fake() {
    let store = store();
    let env = test_env(store._temp.path());
    let install = varde(&["setup", "autosave", "install"], &store.repo, &env, true);
    assert_ok(&install);
    let plists = fs::read_dir(&env.plist_dir)
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert_eq!(plists.len(), 1);
    let plist = plists[0].path();
    let plist_text = fs::read_to_string(&plist).unwrap();
    assert!(plist_text.contains("<integer>1800</integer>"));
    assert!(plist_text.contains("<key>RunAtLoad</key><false/>"));
    let path = std::env::var("PATH").unwrap_or_default();
    assert!(plist_text.contains(&format!("<key>PATH</key><string>{path}</string>")));
    let id = plist.file_stem().unwrap().to_string_lossy();
    let log_path = env
        .plist_dir
        .parent()
        .unwrap()
        .join("logs")
        .join(format!("{id}.log"));
    let log_path = format!("<string>{}</string>", log_path.display());
    assert!(plist_text.contains(&format!("<key>StandardOutPath</key>{log_path}")));
    assert!(plist_text.contains(&format!("<key>StandardErrorPath</key>{log_path}")));
    assert!(plist_text.contains("<string>--repo</string>"));
    assert!(plist_text.contains("<string>run</string>"));

    let uninstall = varde(&["setup", "autosave", "uninstall"], &store.repo, &env, true);
    assert_ok(&uninstall);
    assert!(!plist.exists());
    let again = varde(&["setup", "autosave", "uninstall"], &store.repo, &env, true);
    assert_ok(&again);
    let calls = fs::read_to_string(&env.launchctl_log).unwrap();
    let calls = calls.lines().collect::<Vec<_>>();
    assert!(calls.len() >= 2, "{calls:?}");
    assert!(calls[0].starts_with("bootstrap gui/"), "{calls:?}");
    assert!(calls[1].starts_with("bootout gui/"), "{calls:?}");
}

#[test]
#[cfg_attr(
    target_os = "macos",
    ignore = "launchd install is tested only off macOS"
)]
fn non_macos_install_errors() {
    let store = store();
    let env = test_env(store._temp.path());
    let output = varde(&["setup", "autosave", "install"], &store.repo, &env, false);
    assert_err(&output);
    assert!(output_text(&output).contains("run"));
    assert!(!env.plist_dir.exists());
    assert!(!env.launchctl_log.exists());
}
