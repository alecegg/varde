//! Integration tests for reading a linked git worktree's queries from the
//! main checkout's index (`worktree-base`).
//!
//! Each test creates a throwaway git repository, commits to it, and adds a
//! linked worktree with `git worktree add`. `HOME`, `XDG_CONFIG_HOME` and
//! `VARDE_CONFIG_DIR` are redirected at a fixture root, so no test reads or
//! writes the real user config directory.

use crate::ENV_LOCK;

use serde_json::{Value, json};
use std::ffi::OsString;
use std::path::{Path, PathBuf};

/// Serializes the tests that mutate process-global environment variables;
/// cargo runs the tests in one binary on multiple threads.
/// Temporarily points the config-root environment at a fixture directory.
struct EnvGuard {
    saved: [(&'static str, Option<OsString>); 3],
}

impl EnvGuard {
    fn new(fixture: &Path) -> Self {
        let saved = [
            ("HOME", std::env::var_os("HOME")),
            ("XDG_CONFIG_HOME", std::env::var_os("XDG_CONFIG_HOME")),
            ("VARDE_CONFIG_DIR", std::env::var_os("VARDE_CONFIG_DIR")),
        ];
        unsafe {
            std::env::set_var("HOME", fixture.join("home"));
            std::env::set_var("XDG_CONFIG_HOME", fixture.join("config"));
            std::env::set_var("VARDE_CONFIG_DIR", fixture.join("config").join("varde"));
        }
        Self { saved }
    }
}

impl Drop for EnvGuard {
    fn drop(&mut self) {
        for (key, value) in self.saved.clone() {
            match value {
                Some(value) => unsafe { std::env::set_var(key, value) },
                None => unsafe { std::env::remove_var(key) },
            }
        }
    }
}

/// A main checkout with one committed file plus a linked worktree of it.
struct Fixture {
    root: PathBuf,
    main: PathBuf,
    worktree: PathBuf,
}

impl Fixture {
    fn new(label: &str) -> Self {
        let root = std::env::temp_dir().join(format!(
            "varde-worktree-base-{label}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(root.join("home")).expect("home dir creates");
        std::fs::create_dir_all(root.join("config")).expect("config dir creates");
        let main = root.join("main");
        std::fs::create_dir_all(&main).expect("main dir creates");
        git(&["init", "-q", "-b", "main"], &main);
        std::fs::write(main.join("main.py"), "def base_symbol():\n    return 1\n")
            .expect("main.py writes");
        git(&["add", "-A"], &main);
        git(
            &[
                "-c",
                "user.name=varde",
                "-c",
                "user.email=varde@example.com",
                "commit",
                "-q",
                "-m",
                "init",
            ],
            &main,
        );
        let worktree = root.join("worktree");
        git(
            &[
                "worktree",
                "add",
                "--detach",
                "-q",
                worktree.to_str().expect("utf-8 worktree path"),
                "HEAD",
            ],
            &main,
        );
        Self {
            root,
            main,
            worktree,
        }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn git(args: &[&str], cwd: &Path) {
    let output = std::process::Command::new("git")
        .args(args)
        .current_dir(cwd)
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .output()
        .expect("git runs");
    assert!(
        output.status.success(),
        "git {args:?} failed in {}: {}",
        cwd.display(),
        String::from_utf8_lossy(&output.stderr)
    );
}

fn query_mode(mode: &str, input: Value) -> Value {
    let raw = varde_code::query::run_mode(mode, &input.to_string());
    serde_json::from_str(&raw).expect("envelope is valid JSON")
}

fn query(input: Value) -> Value {
    query_mode("symbols_in_file", input)
}

fn symbol_names(envelope: &Value) -> Vec<String> {
    envelope["data"]
        .as_array()
        .expect("symbols array")
        .iter()
        .filter_map(|symbol| symbol["name"].as_str().map(str::to_string))
        .collect()
}

/// Every file and directory under `root` as `(relative path, size, mtime,
/// is_dir)`, sorted, for a before/after comparison of a read-only operation.
/// Recording mtimes catches a same-size rewrite that a size-only snapshot
/// would miss.
fn tree_snapshot(root: &Path) -> Vec<(String, u64, std::time::SystemTime, bool)> {
    let mut out = Vec::new();
    let mut stack: Vec<(PathBuf, String)> = vec![(root.to_path_buf(), String::new())];
    while let Some((dir, rel)) = stack.pop() {
        let Ok(read_dir) = std::fs::read_dir(&dir) else {
            continue;
        };
        for entry in read_dir.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            let rel_path = if rel.is_empty() {
                name
            } else {
                format!("{rel}/{name}")
            };
            let Ok(metadata) = entry.metadata() else {
                continue;
            };
            let Ok(mtime) = metadata.modified() else {
                continue;
            };
            if metadata.is_dir() {
                out.push((rel_path.clone(), 0, mtime, true));
                stack.push((entry.path(), rel_path));
            } else {
                out.push((rel_path, metadata.len(), mtime, false));
            }
        }
    }
    out.sort();
    out
}

#[test]
fn worktree_without_an_index_answers_from_the_main_checkout_and_writes_nothing() {
    let _lock = ENV_LOCK.lock().unwrap_or_else(|err| err.into_inner());
    let fixture = Fixture::new("base");
    let _env = EnvGuard::new(&fixture.root);

    varde_code::build::run(fixture.main.to_str().expect("utf-8 main path"))
        .expect("main index builds");
    // Snapshot the whole fixture (config, home, main, worktree), not only the
    // config root, so a write outside it is caught too.
    let before = tree_snapshot(&fixture.root);

    // A relative file path, as a worker inside the worktree would give it;
    // the base index stores the main checkout's absolute paths.
    let envelope = query(json!({"repoRoot": fixture.worktree.clone(), "filePath": "main.py"}));
    assert_eq!(envelope["ok"], true, "{envelope}");
    assert!(
        symbol_names(&envelope)
            .iter()
            .any(|name| name == "base_symbol"),
        "the main index answers the worktree query: {envelope}"
    );

    // Paths in the answer name the worktree, never the main checkout, so a
    // worker cannot read or edit main-checkout files. The default policy
    // relativizes them; the explicit `absolutePaths` variant must stay within
    // the worktree.
    let file_of = |envelope: &Value| -> Vec<String> {
        envelope["data"]
            .as_array()
            .expect("symbols array")
            .iter()
            .filter_map(|symbol| symbol["file"].as_str().map(str::to_string))
            .collect()
    };
    let main_given = fixture.main.to_string_lossy().into_owned();
    let main_canonical = std::fs::canonicalize(&fixture.main)
        .expect("main checkout canonicalizes")
        .to_string_lossy()
        .into_owned();
    let worktree_given = fixture.worktree.to_string_lossy().into_owned();
    assert!(
        file_of(&envelope).iter().all(|file| file == "main.py"),
        "repo-relative answer paths: {envelope}"
    );
    let envelope_text = envelope.to_string();
    assert!(
        !envelope_text.contains(&main_given) && !envelope_text.contains(&main_canonical),
        "no main-checkout path in a worktree answer: {envelope}"
    );

    let absolute = query(json!({
        "repoRoot": fixture.worktree.clone(),
        "filePath": "main.py",
        "absolutePaths": true
    }));
    assert_eq!(absolute["ok"], true, "{absolute}");
    assert!(
        file_of(&absolute)
            .iter()
            .all(|file| file.starts_with(&worktree_given)),
        "absolutePaths answers stay inside the worktree: {absolute}"
    );
    let absolute_text = absolute.to_string();
    assert!(
        !absolute_text.contains(&main_given) && !absolute_text.contains(&main_canonical),
        "no main-checkout path with absolutePaths: {absolute}"
    );

    let note = &envelope["meta"]["base_index"];
    assert!(!note.is_null(), "base_index note present: {envelope}");
    let hash = note["main_checkout_hash"]
        .as_str()
        .expect("main_checkout_hash is a string");
    assert_eq!(hash.len(), 16, "16 hex chars: {hash}");
    assert!(
        hash.chars().all(|c| c.is_ascii_hexdigit()),
        "hex hash: {hash}"
    );
    assert!(
        !note.to_string().contains(std::path::MAIN_SEPARATOR),
        "the note carries no absolute path: {note}"
    );

    let after = tree_snapshot(&fixture.root);
    assert_eq!(
        before, after,
        "a worktree query writes nothing under the fixture root"
    );
}

/// Every mode whose answer is (or holds) file paths must name the worktree,
/// never the main checkout, when it reads the base index. Bare string arrays
/// (`dependents`, `blast_radius`, `tests_for_file`) and other keys
/// (`symbol_blast_radius`'s `declaring_file`) once slipped past a rewrite
/// that only touched a fixed list of field names.
#[test]
fn base_index_answers_never_name_the_main_checkout() {
    let _lock = ENV_LOCK.lock().unwrap_or_else(|err| err.into_inner());
    let fixture = Fixture::new("no-leak");
    let _env = EnvGuard::new(&fixture.root);

    // `app.py` and `test_main.py` import `main.py`, so the graph and coverage
    // modes have real dependents and a covering test to return.
    std::fs::write(
        fixture.main.join("app.py"),
        "from main import base_symbol\n\ndef use():\n    return base_symbol()\n",
    )
    .expect("app.py writes");
    std::fs::write(
        fixture.main.join("test_main.py"),
        "from main import base_symbol\n\ndef test_base():\n    assert base_symbol() == 1\n",
    )
    .expect("test_main.py writes");
    varde_code::build::run(fixture.main.to_str().expect("utf-8 main path"))
        .expect("main index builds");

    let worktree = fixture.worktree.to_string_lossy().into_owned();
    let main_given = fixture.main.to_string_lossy().into_owned();
    let main_canonical = std::fs::canonicalize(&fixture.main)
        .expect("main checkout canonicalizes")
        .to_string_lossy()
        .into_owned();

    let cases: [(&str, Value); 5] = [
        (
            "dependents",
            json!({"repoRoot": worktree, "filePath": "main.py"}),
        ),
        (
            "blast_radius",
            json!({"repoRoot": worktree, "filePath": "main.py"}),
        ),
        (
            "tests_for_file",
            json!({"repoRoot": worktree, "filePath": "main.py"}),
        ),
        (
            "symbol_blast_radius",
            json!({"repoRoot": worktree, "name": "base_symbol"}),
        ),
        (
            "batch",
            json!({
                "repoRoot": worktree,
                "calls": [{"mode": "dependents", "filePath": "main.py"}]
            }),
        ),
    ];
    for (mode, input) in cases {
        let envelope = query_mode(mode, input);
        assert_eq!(envelope["ok"], true, "{mode}: {envelope}");
        let text = envelope.to_string();
        assert!(
            !text.contains(&main_given) && !text.contains(&main_canonical),
            "{mode} leaks a main-checkout path: {envelope}"
        );
        assert!(
            text.contains(&worktree),
            "{mode} names the worktree for its non-empty answer: {envelope}"
        );
    }
}

/// A worker inside the worktree that passes the absolute paths it was given
/// must still be answered from the base index. Input paths under the worktree
/// root are mapped onto the main checkout root before lookup (the inverse of
/// the output rewrite); before the fix an absolute `<worktree>/main.py`
/// returned `not_found`.
///
/// A nested file that shares the top-level basename must not win the lookup:
/// the mapped absolute path matches the top-level row exactly instead of
/// falling through to `simple::file_id`'s suffix match, which picks
/// `a/main.py` ('a' sorts before 'm').
#[test]
fn absolute_worktree_file_path_is_mapped_onto_the_main_root() {
    let _lock = ENV_LOCK.lock().unwrap_or_else(|err| err.into_inner());
    let fixture = Fixture::new("abs-input");
    let _env = EnvGuard::new(&fixture.root);

    std::fs::create_dir_all(fixture.main.join("a")).expect("a/ creates");
    std::fs::write(
        fixture.main.join("a/main.py"),
        "def nested_symbol():\n    return 2\n",
    )
    .expect("a/main.py writes");
    varde_code::build::run(fixture.main.to_str().expect("utf-8 main path"))
        .expect("main index builds");

    let main_given = fixture.main.to_string_lossy().into_owned();
    let main_canonical = std::fs::canonicalize(&fixture.main)
        .expect("main checkout canonicalizes")
        .to_string_lossy()
        .into_owned();
    let envelope = query(json!({
        "repoRoot": fixture.worktree.clone(),
        "filePath": fixture.worktree.join("main.py")
    }));
    assert_eq!(envelope["ok"], true, "{envelope}");
    assert!(!envelope["meta"]["base_index"].is_null(), "{envelope}");
    let files: Vec<String> = envelope["data"]
        .as_array()
        .expect("symbols array")
        .iter()
        .filter_map(|symbol| symbol["file"].as_str().map(str::to_string))
        .collect();
    assert_eq!(
        files,
        vec!["main.py".to_string()],
        "the absolute worktree path resolves to the top-level file, not a/main.py: {envelope}"
    );
    let names = symbol_names(&envelope);
    assert!(
        names.iter().any(|name| name == "base_symbol"),
        "the top-level main.py answers the absolute path: {envelope}"
    );
    assert!(
        !names.iter().any(|name| name == "nested_symbol"),
        "a/main.py must not answer for the top-level path: {envelope}"
    );
    let text = envelope.to_string();
    assert!(
        !text.contains(&main_given) && !text.contains(&main_canonical),
        "no main-checkout path in the answer: {envelope}"
    );

    // `symbols_in_files` keys its result object by the requested path. After
    // the input mapping the key is a main-checkout row path, so the output
    // pass must rewrite object keys as well as values.
    let worktree_given = fixture.worktree.to_string_lossy().into_owned();
    let keyed = query_mode(
        "symbols_in_files",
        json!({
            "repoRoot": fixture.worktree.clone(),
            "filePaths": [fixture.worktree.join("main.py")]
        }),
    );
    assert_eq!(keyed["ok"], true, "{keyed}");
    let object = keyed["data"]
        .as_object()
        .expect("symbols_in_files data is an object");
    assert_eq!(object.len(), 1, "{keyed}");
    let key = object.keys().next().expect("one key");
    assert!(
        key.starts_with(&worktree_given),
        "symbols_in_files keys the worktree, not the main checkout: {keyed}"
    );
    let keyed_text = keyed.to_string();
    assert!(
        !keyed_text.contains(&main_given) && !keyed_text.contains(&main_canonical),
        "symbols_in_files leaks a main-checkout path: {keyed}"
    );

    // A batch sub-call routes through the same dispatch, so its result must
    // not leak a main-checkout path either.
    let batch = query_mode(
        "batch",
        json!({
            "repoRoot": fixture.worktree.clone(),
            "calls": [{
                "mode": "symbols_in_files",
                "filePaths": [fixture.worktree.join("main.py")]
            }]
        }),
    );
    assert_eq!(batch["ok"], true, "{batch}");
    let batch_text = batch.to_string();
    assert!(
        !batch_text.contains(&main_given) && !batch_text.contains(&main_canonical),
        "a batch symbols_in_files sub-call leaks a main-checkout path: {batch}"
    );
}

/// An index built through a differently spelled main root (a symlinked
/// directory alias, as macOS `/tmp` vs `/private/tmp`) keeps that spelling in
/// its rows. The canonical main root and the caller's re-spelled root both
/// miss it, so the mapped input would otherwise fall through to the ambiguous
/// basename suffix match; the build-time root is recovered from an indexed
/// row instead. A nested `a/main.py` proves the mapped path resolves to the
/// exact row rather than the first path ending in `/main.py`.
#[cfg(unix)]
#[test]
fn absolute_worktree_path_resolves_against_the_build_time_root_spelling() {
    let _lock = ENV_LOCK.lock().unwrap_or_else(|err| err.into_inner());
    let fixture = Fixture::new("build-spelling");
    let _env = EnvGuard::new(&fixture.root);

    std::fs::create_dir_all(fixture.main.join("a")).expect("a/ creates");
    std::fs::write(
        fixture.main.join("a/main.py"),
        "def nested_symbol():\n    return 2\n",
    )
    .expect("a/main.py writes");

    // Build the index through a symlinked spelling of the main checkout, so
    // its rows name `alias/main/...` while the canonical root is
    // `<root>/main` and the caller's worktree is spelled plainly.
    let alias = fixture.root.join("alias");
    std::os::unix::fs::symlink(&fixture.root, &alias).expect("alias symlink creates");
    let build_root = alias.join("main");
    varde_code::build::run(build_root.to_str().expect("utf-8 build path"))
        .expect("main index builds through the alias spelling");

    let main_given = fixture.main.to_string_lossy().into_owned();
    let main_canonical = std::fs::canonicalize(&fixture.main)
        .expect("main checkout canonicalizes")
        .to_string_lossy()
        .into_owned();

    let top = query(json!({
        "repoRoot": fixture.worktree.clone(),
        "filePath": fixture.worktree.join("main.py")
    }));
    assert_eq!(top["ok"], true, "{top}");
    assert!(!top["meta"]["base_index"].is_null(), "{top}");
    let top_names = symbol_names(&top);
    assert!(
        top_names.iter().any(|name| name == "base_symbol"),
        "the top-level main.py answers the absolute path: {top}"
    );
    assert!(
        !top_names.iter().any(|name| name == "nested_symbol"),
        "a/main.py must not answer for the top-level path: {top}"
    );

    let nested = query(json!({
        "repoRoot": fixture.worktree.clone(),
        "filePath": fixture.worktree.join("a").join("main.py")
    }));
    assert_eq!(nested["ok"], true, "{nested}");
    let nested_names = symbol_names(&nested);
    assert!(
        nested_names.iter().any(|name| name == "nested_symbol"),
        "the nested path still resolves to a/main.py: {nested}"
    );
    assert!(
        !nested_names.iter().any(|name| name == "base_symbol"),
        "a/main.py must not fall back to the top-level file: {nested}"
    );

    for envelope in [&top, &nested] {
        let text = envelope.to_string();
        assert!(
            !text.contains(&main_given) && !text.contains(&main_canonical),
            "no main-checkout path in the answer: {envelope}"
        );
    }
}

#[test]
fn worktree_with_its_own_index_uses_it_and_omits_the_base_note() {
    let _lock = ENV_LOCK.lock().unwrap_or_else(|err| err.into_inner());
    let fixture = Fixture::new("own-index");
    let _env = EnvGuard::new(&fixture.root);

    varde_code::build::run(fixture.main.to_str().expect("utf-8 main path"))
        .expect("main index builds");
    std::fs::write(
        fixture.worktree.join("main.py"),
        "def base_symbol():\n    return 1\n\ndef worktree_only():\n    return 2\n",
    )
    .expect("worktree edit writes");
    varde_code::build::run(fixture.worktree.to_str().expect("utf-8 worktree path"))
        .expect("worktree index builds");

    let envelope = query(json!({"repoRoot": fixture.worktree.clone(), "filePath": "main.py"}));
    assert_eq!(envelope["ok"], true, "{envelope}");
    assert!(
        symbol_names(&envelope)
            .iter()
            .any(|name| name == "worktree_only"),
        "the worktree's own index answers, not the main checkout's: {envelope}"
    );
    assert!(
        envelope["meta"]["base_index"].is_null(),
        "a local index needs no base_index note: {envelope}"
    );
}

#[test]
fn worktree_without_any_index_still_reports_index_missing() {
    let _lock = ENV_LOCK.lock().unwrap_or_else(|err| err.into_inner());
    let fixture = Fixture::new("no-index");
    let _env = EnvGuard::new(&fixture.root);

    let envelope = query(json!({"repoRoot": fixture.worktree.clone(), "filePath": "main.py"}));
    assert_eq!(
        envelope["data"]["error"]["code"], "index_missing",
        "no index anywhere keeps today's error: {envelope}"
    );
}
