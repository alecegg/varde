//! `varde msg send` / `varde msg read` over the append-only inbox store.

use std::fs;
use std::path::PathBuf;
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(0);

struct Fixture {
    root: PathBuf,
    config: PathBuf,
    working: PathBuf,
}

impl Fixture {
    fn new(tag: &str) -> Self {
        let nonce = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
        let base =
            std::env::temp_dir().join(format!("varde-msg-{tag}-{}-{nonce}", std::process::id()));
        let root = base.join("root");
        let config = base.join("config");
        let working = base.join("working");
        for dir in [&root, &config, &working] {
            fs::create_dir_all(dir).unwrap();
        }
        Self {
            root,
            config,
            working,
        }
    }

    fn run(&self, args: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(args)
            .current_dir(&self.root)
            .env("VARDE_CONFIG_DIR", &self.config)
            .env("VARDE_WORKING_DIR", &self.working)
            .env_remove("VARDE_KNOWLEDGE_DIR")
            .env_remove("VARDE_LEARN_STORE")
            .output()
            .unwrap()
    }

    fn store(&self) -> PathBuf {
        fs::canonicalize(&self.working)
            .unwrap()
            .join(".cache")
            .join("inbox")
            .join("messages.jsonl")
    }

    fn cursor(&self, reader: &str) -> PathBuf {
        fs::canonicalize(&self.working)
            .unwrap()
            .join(".cache")
            .join("inbox")
            .join("cursors")
            .join(reader)
    }
}

fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).into_owned()
}

fn stdout(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).into_owned()
}

#[test]
fn send_then_read_delivers_once() {
    let f = Fixture::new("once");
    let sent = f.run(&[
        "msg",
        "send",
        "--from",
        "orch",
        "--to",
        "main",
        "--kind",
        "done",
        "wave published",
    ]);
    assert!(sent.status.success(), "{}", stderr(&sent));
    assert!(sent.stdout.is_empty(), "send must print nothing");

    let first = f.run(&["msg", "read"]);
    assert!(first.status.success(), "{}", stderr(&first));
    let line = stdout(&first);
    assert_eq!(line.lines().count(), 1, "{line}");
    assert!(line.contains("orch"), "{line}");
    assert!(line.contains("done"), "{line}");
    assert!(line.contains("wave published"), "{line}");

    let second = f.run(&["msg", "read"]);
    assert!(second.status.success(), "{}", stderr(&second));
    assert!(second.stdout.is_empty(), "{}", stdout(&second));
}

#[test]
fn msg_store_uses_repository_root_when_run_from_nested_directory() {
    let f = Fixture::new("store-root");
    let nested = f.root.join("clis");
    fs::create_dir_all(&nested).unwrap();
    let init = Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&f.root)
        .status()
        .unwrap();
    assert!(init.success());

    let output = Command::new(env!("CARGO_BIN_EXE_varde"))
        .args([
            "msg", "send", "--from", "orch", "--to", "main", "--kind", "info", "rooted",
        ])
        .current_dir(&nested)
        .env("VARDE_CONFIG_DIR", &f.config)
        .env_remove("VARDE_WORKING_DIR")
        .env_remove("VARDE_KNOWLEDGE_DIR")
        .env_remove("VARDE_LEARN_STORE")
        .output()
        .unwrap();
    assert!(output.status.success(), "{}", stderr(&output));
    assert!(
        f.root
            .join("memory-bank/working/.cache/inbox/messages.jsonl")
            .exists()
    );
    assert!(!nested.join("memory-bank").exists());
}

#[test]
fn read_as_isolates_addresses_and_all_leaves_cursors() {
    let f = Fixture::new("addresses");
    for (to, text) in [("main", "one"), ("main", "two"), ("agent-a", "three")] {
        let sent = f.run(&[
            "msg", "send", "--from", "orch", "--to", to, "--kind", "info", text,
        ]);
        assert!(sent.status.success(), "{}", stderr(&sent));
    }

    let as_a = f.run(&["msg", "read", "--as", "agent-a"]);
    let a = stdout(&as_a);
    assert_eq!(a.lines().count(), 1, "{a}");
    assert!(a.contains("three"), "{a}");
    assert!(!a.contains("one") && !a.contains("two"), "{a}");

    let all = f.run(&["msg", "read", "--all"]);
    let all_text = stdout(&all);
    assert_eq!(all_text.lines().count(), 3, "{all_text}");
    assert!(all_text.contains("one"), "{all_text}");
    assert!(all_text.contains("two"), "{all_text}");
    assert!(all_text.contains("three"), "{all_text}");

    // `--all` moved no cursor: main still holds its two, agent-a stays drained.
    let main = f.run(&["msg", "read"]);
    let main_text = stdout(&main);
    assert_eq!(main_text.lines().count(), 2, "{main_text}");
    let a_again = f.run(&["msg", "read", "--as", "agent-a"]);
    assert!(a_again.stdout.is_empty(), "{}", stdout(&a_again));
}

#[test]
fn read_json_uses_the_envelope_and_rejects_a_traversing_reader() {
    let f = Fixture::new("json");
    let sent = f.run(&[
        "msg", "send", "--from", "orch", "--to", "main", "--kind", "done", "wave published",
    ]);
    assert!(sent.status.success(), "{}", stderr(&sent));

    let json_out = f.run(&["msg", "read", "--json"]);
    assert!(json_out.status.success(), "{}", stderr(&json_out));
    let value: serde_json::Value = serde_json::from_slice(&json_out.stdout).unwrap();
    assert_eq!(value["ok"], true, "{value}");
    assert_eq!(value["outcome"], "success", "{value}");
    let messages = value["data"]["messages"].as_array().unwrap();
    assert_eq!(messages.len(), 1, "{value}");
    assert_eq!(messages[0]["from"], "orch", "{value}");
    assert_eq!(messages[0]["to"], "main", "{value}");
    assert_eq!(messages[0]["kind"], "done", "{value}");
    assert_eq!(messages[0]["text"], "wave published", "{value}");

    // `--json` still commits the cursor: the next plain read is empty.
    let second = f.run(&["msg", "read"]);
    assert!(second.status.success(), "{}", stderr(&second));
    assert!(second.stdout.is_empty(), "{}", stdout(&second));

    // A reader name that could escape the cursor directory is rejected.
    let bad = f.run(&["msg", "read", "--as", "../x"]);
    assert!(
        !bad.status.success(),
        "traversing --as must fail: {}",
        stdout(&bad)
    );
    assert!(!f.cursor("x").exists(), "no cursor escaped the directory");
}

#[test]
fn hook_keeps_messages_unread_when_stdout_is_closed() {
    let f = Fixture::new("hook-epipe");
    let sent = f.run(&[
        "msg", "send", "--from", "orch", "--to", "main", "--kind", "done", "wave published",
    ]);
    assert!(sent.status.success(), "{}", stderr(&sent));

    let (reader, writer) = std::io::pipe().expect("pipe");
    drop(reader);
    let hook = Command::new(env!("CARGO_BIN_EXE_varde"))
        .args(["hook", "user-prompt-submit", "--harness", "pi"])
        .current_dir(&f.root)
        .env("VARDE_CONFIG_DIR", &f.config)
        .env("VARDE_WORKING_DIR", &f.working)
        .stdout(std::process::Stdio::from(writer))
        .stderr(std::process::Stdio::piped())
        .output()
        .unwrap();
    assert_eq!(hook.status.code(), Some(0), "{}", stderr(&hook));

    // The undelivered message stays unread for the next read.
    let read = f.run(&["msg", "read"]);
    assert!(
        stdout(&read).contains("wave published"),
        "{}",
        stdout(&read)
    );
}

#[test]
fn msg_send_rejects_newline_overlong_text_and_unknown_kind() {
    let f = Fixture::new("reject");

    let newline = f.run(&[
        "msg",
        "send",
        "--from",
        "orch",
        "--to",
        "main",
        "--kind",
        "info",
        "two\nlines",
    ]);
    assert!(!newline.status.success(), "newline text must fail");

    let over = "x".repeat(301);
    let over_output = f.run(&[
        "msg", "send", "--from", "orch", "--to", "main", "--kind", "info", &over,
    ]);
    assert!(!over_output.status.success(), "over-limit text must fail");
    let err = stderr(&over_output);
    assert!(err.contains("300"), "{err}");
    assert!(err.contains("1000"), "{err}");
    assert!(err.trim_end().ends_with("use --notes <path>"), "{err}");

    // Text within 300 chars, but the encoded line crosses the byte cap.
    let long_from = "a".repeat(900);
    let long_text = "y".repeat(100);
    let long_line = f.run(&[
        "msg", "send", "--from", &long_from, "--to", "main", "--kind", "info", &long_text,
    ]);
    assert!(!long_line.status.success(), "over-limit line must fail");
    let err = stderr(&long_line);
    assert!(err.contains("1000"), "{err}");

    let kind = f.run(&[
        "msg", "send", "--from", "orch", "--to", "main", "--kind", "shout", "hello",
    ]);
    assert!(!kind.status.success(), "unknown kind must fail");
    let err = stderr(&kind);
    for allowed in ["blocked", "needs-user", "done", "info"] {
        assert!(err.contains(allowed), "{err}");
    }

    let all = f.run(&["msg", "read", "--all"]);
    assert!(
        all.stdout.is_empty(),
        "rejected sends wrote nothing: {}",
        stdout(&all)
    );
}

#[test]
fn missing_store_torn_line_and_cursor_past_end_read_safely() {
    let f = Fixture::new("edges");

    let missing = f.run(&["msg", "read"]);
    assert!(missing.status.success(), "{}", stderr(&missing));
    assert!(missing.stdout.is_empty(), "{}", stdout(&missing));

    let store = f.store();
    fs::create_dir_all(store.parent().unwrap()).unwrap();
    let complete = r#"{"ts":"2026-01-01T00:00:00Z","from":"orch","to":"main","kind":"done","text":"complete"}"#;
    let torn = format!("{complete}\n{{\"ts\":\"2026-01-01T00:00:01Z\",\"from\":\"orch\"");
    fs::write(&store, &torn).unwrap();

    let first = f.run(&["msg", "read"]);
    assert!(first.status.success(), "{}", stderr(&first));
    let text = stdout(&first);
    assert_eq!(text.lines().count(), 1, "{text}");
    assert!(text.contains("complete"), "{text}");

    // The torn line was left for the next read: completing it delivers it.
    let mut completed = torn.clone();
    completed.push_str(",\"to\":\"main\",\"kind\":\"info\",\"text\":\"recovered\"}\n");
    fs::write(&store, &completed).unwrap();
    let second = f.run(&["msg", "read"]);
    let text = stdout(&second);
    assert_eq!(text.lines().count(), 1, "{text}");
    assert!(text.contains("recovered"), "{text}");

    // A cursor past the end of the file resets to zero and replays.
    fs::write(f.cursor("main"), "999999\n").unwrap();
    let replayed = f.run(&["msg", "read"]);
    let text = stdout(&replayed);
    assert_eq!(text.lines().count(), 2, "{text}");
}

#[test]
fn user_prompt_submit_hook_prints_unread_once_and_nothing_when_empty() {
    let f = Fixture::new("hook");

    let empty = f.run(&["hook", "user-prompt-submit", "--harness", "claude"]);
    assert!(empty.status.success(), "{}", stderr(&empty));
    assert!(empty.stdout.is_empty(), "{}", stdout(&empty));

    let sent = f.run(&[
        "msg",
        "send",
        "--from",
        "orch",
        "--to",
        "main",
        "--kind",
        "done",
        "wave published",
    ]);
    assert!(sent.status.success(), "{}", stderr(&sent));

    let first = f.run(&["hook", "user-prompt-submit", "--harness", "claude"]);
    assert!(first.status.success(), "{}", stderr(&first));
    let value: serde_json::Value = serde_json::from_slice(&first.stdout).unwrap();
    assert_eq!(
        value["hookSpecificOutput"]["hookEventName"],
        "UserPromptSubmit"
    );
    let context = value["hookSpecificOutput"]["additionalContext"]
        .as_str()
        .unwrap();
    assert!(
        context.contains("inbox: orch done: wave published"),
        "{context}"
    );

    let second = f.run(&["hook", "user-prompt-submit", "--harness", "claude"]);
    assert!(second.status.success(), "{}", stderr(&second));
    assert!(second.stdout.is_empty(), "{}", stdout(&second));
}

#[test]
fn user_prompt_submit_hook_is_plain_text_for_pi_and_honours_the_provider_list() {
    let f = Fixture::new("hook-pi");
    let sent = f.run(&[
        "msg", "send", "--from", "a", "--to", "main", "--kind", "info", "one",
    ]);
    assert!(sent.status.success(), "{}", stderr(&sent));

    let pi = f.run(&["hook", "user-prompt-submit", "--harness", "pi"]);
    assert!(pi.status.success(), "{}", stderr(&pi));
    assert_eq!(stdout(&pi).trim(), "inbox: a info: one");
    assert!(!stdout(&pi).contains("hookSpecificOutput"));

    // A second run prints nothing, and an empty provider list reads nothing.
    assert!(
        f.run(&["hook", "user-prompt-submit", "--harness", "pi"])
            .stdout
            .is_empty()
    );
    let sent = f.run(&[
        "msg", "send", "--from", "a", "--to", "main", "--kind", "info", "two",
    ]);
    assert!(sent.status.success(), "{}", stderr(&sent));
    fs::write(
        f.config.join("config.toml"),
        "[hooks.user_prompt_submit]\nproviders = []\n",
    )
    .unwrap();
    let disabled = f.run(&["hook", "user-prompt-submit", "--harness", "pi"]);
    assert!(disabled.status.success(), "{}", stderr(&disabled));
    assert!(disabled.stdout.is_empty(), "{}", stdout(&disabled));
}

#[test]
fn user_prompt_submit_hook_reports_an_unknown_provider_and_leaves_messages_unread() {
    let f = Fixture::new("hook-unknown");
    fs::write(
        f.config.join("config.toml"),
        "[hooks.user_prompt_submit]\nproviders = [\"bogus\"]\n",
    )
    .unwrap();
    let sent = f.run(&[
        "msg", "send", "--from", "a", "--to", "main", "--kind", "info", "one",
    ]);
    assert!(sent.status.success(), "{}", stderr(&sent));

    let out = f.run(&["hook", "user-prompt-submit", "--harness", "claude"]);
    assert!(out.status.success(), "{}", stderr(&out));
    assert!(out.stdout.is_empty(), "{}", stdout(&out));
    assert!(
        stderr(&out).contains("unknown provider `bogus`"),
        "{}",
        stderr(&out)
    );

    let read = f.run(&["msg", "read"]);
    assert!(stdout(&read).contains("one"), "{}", stdout(&read));
}

#[test]
fn user_prompt_submit_hook_reads_a_torn_store_as_empty_and_exits_zero() {
    let f = Fixture::new("hook-edges");
    let store = f.store();
    fs::create_dir_all(store.parent().unwrap()).unwrap();
    fs::write(
        &store,
        "{\"ts\":\"x\",\"from\":\"a\",\"to\":\"main\",\"kind\":\"info\",\"text\":\"torn\"",
    )
    .unwrap();
    let out = f.run(&["hook", "user-prompt-submit", "--harness", "claude"]);
    assert!(out.status.success(), "{}", stderr(&out));
    assert!(out.stdout.is_empty(), "{}", stdout(&out));
}

#[test]
fn concurrent_senders_append_complete_lines() {
    let f = Fixture::new("concurrent");
    std::thread::scope(|scope| {
        for worker in 0..8 {
            let f = &f;
            scope.spawn(move || {
                for index in 0..50 {
                    let from = format!("worker-{worker}");
                    let text = format!("message {worker}-{index}");
                    let out = f.run(&[
                        "msg", "send", "--from", &from, "--to", "main", "--kind", "info", &text,
                    ]);
                    assert!(out.status.success(), "{}", stderr(&out));
                }
            });
        }
    });

    let all = f.run(&["msg", "read", "--all"]);
    assert!(all.status.success(), "{}", stderr(&all));
    let text = stdout(&all);
    let lines: Vec<&str> = text.lines().collect();
    assert_eq!(lines.len(), 400, "{}", lines.len());
    for line in &lines {
        assert!(line.starts_with("worker-"), "{line}");
        assert!(line.contains(" info: message "), "{line}");
    }

    // Every append stayed one whole JSON line: no interleaving or torn writes.
    let store = fs::read_to_string(f.store()).unwrap();
    let stored: Vec<&str> = store.lines().collect();
    assert_eq!(stored.len(), 400, "{}", stored.len());
    for line in stored {
        let value: serde_json::Value =
            serde_json::from_str(line).unwrap_or_else(|error| panic!("bad line {line}: {error}"));
        assert!(value["text"].is_string(), "{line}");
        assert!(value["from"].is_string(), "{line}");
    }
}
