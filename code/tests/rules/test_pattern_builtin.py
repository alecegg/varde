# ruff: noqa: UP034 - Explicit grouping preserves split fixture strings in calls.
from pathlib import Path

from varde_code.rules.pattern import run_pattern_rules


def _run_builtin_fixture_rules(tmp_path, files, packs, rule_ids):
    import sqlite3
    import subprocess

    from varde_code.rules.loader import parse_pack_file

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607 - Test initializes a temporary repository using the host Git executable.
    for relative, source in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    builtin_dir = Path(__file__).parents[2] / "src/varde_code/rules/builtin"
    rules = []
    for pack in packs:
        parsed, diagnostics = parse_pack_file(builtin_dir / pack)
        assert diagnostics == []
        rules.extend(rule for rule in parsed if rule.id in rule_ids)

    db = sqlite3.connect(":memory:")
    db.execute(
        (
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, "
            "is_test_path INTEGER, is_tooling_path INTEGER)"
        )
    )
    db.execute(
        (
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, name TEXT, is_async INTEGER)"
        )
    )
    findings, diagnostics = run_pattern_rules(rules, tmp_path, db)
    db.close()
    assert diagnostics == []
    return [finding.rule_id for finding in findings]


def test_builtin_empty_catch_and_eval_rules_fire_end_to_end(tmp_path):
    ids = _run_builtin_fixture_rules(
        tmp_path,
        {
            "sample.ts": """function sample() {
  try { risky(); } catch (err) { }
  try { risky(); } catch (err) { /* intentional */ }
  try { risky(); } catch (err) { handle(err); }
  eval(userInput);
  obj.eval("not-a-match");
}
""",
            "sample.py": """def sample():
    try:
        risky()
    except ValueError as e:
        pass
    try:
        risky()
    except KeyError as e:
        handle(e)
    try:
        risky()
    except OSError as e:
        # intentional: retry loop owns it
        pass
    eval(user_input)
""",
            "sample.swift": """func sample() {
    do { try risky() } catch { }
    do { try risky() } catch { note() }
    do { try risky() } catch let err { }
}
""",
        },
        ("empty_catch_block.toml", "eval_usage.toml"),
        {
            "empty-catch-block",
            "empty-except-block",
            "empty-catch-block-swift",
            "eval-usage",
        },
    )
    assert ids.count("empty-catch-block") == 1
    assert ids.count("empty-except-block") == 1
    assert ids.count("empty-catch-block-swift") == 1
    assert ids.count("eval-usage") == 2
    assert len(ids) == 5
    assert "churn-complexity-hotspot" not in ids


def test_builtin_debug_rules_fire_end_to_end(tmp_path):
    ts_content = """function a() {
  const x = 1;
  console.log(x);
  console.log("hi", x);
  console.warn(x);
  console.error(x);
  debugger;
}
class C {
  m() {
    debugger;
  }
}
"""
    ids = _run_builtin_fixture_rules(
        tmp_path,
        {
            "sample.rs": """fn sample() {
    let x = 42;
    dbg!(x);
    dbg!(x, x);
    println!("x = {}", x);
    println!("dbg: {}", x);
    let mut v = vec![1, 2];
    v.push(dbg!(v.len()));
}
""",
            "sample.ts": ts_content,
            "sample.js": ts_content,
            "sample.tsx": ts_content,
        },
        ("debug_statement_strict.toml",),
        {"debug-macro-strict", "debug-statement-strict", "console-log-strict"},
    )
    assert ids.count("debug-macro-strict") == 3
    assert ids.count("debug-statement-strict") == 6
    assert ids.count("console-log-strict") == 6
    assert len(ids) == 15
    assert all(
        rule_id.startswith("debug-") or rule_id == "console-log-strict"
        for rule_id in ids
    )


def test_builtin_credential_rules_fire_end_to_end(tmp_path):
    ts_content = """const API_KEY = "sk-9f8d7c6b5a4f3e2d1c0b9a8f7d6c5b4a";
let apiKey = "abcd1234abcd1234abcd1234";
const password = "hunter2";
const username = "alice";
const secret = process.env.SECRET;
const api_key = "your-api-key-here";
const client_secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY";
config.api_key = "sk-9f8d7c6b5a4f3e2d1c0b9a8f7d6c5b4a";
session_token = "1234567890abcdef1234567890abcdef";
"""
    ids = _run_builtin_fixture_rules(
        tmp_path,
        {
            "sample.ts": ts_content,
            "sample.js": ts_content,
            "sample.tsx": ts_content,
            "sample.py": """API_KEY = "9f8d7c6b5a4f3e2d1c0b9a8f"
password = "correcthorsebatterystaple"
token = compute_token()
api_key = "changeme"
client_id = "1234567890abcdef1234567890abcdef"
""",
        },
        ("hardcoded_credential_literal.toml",),
        {"hardcoded-credential-declaration", "hardcoded-credential-literal"},
    )
    assert ids.count("hardcoded-credential-declaration") == 6
    assert ids.count("hardcoded-credential-literal") == 4
    assert len(ids) == 10
    assert all(rule_id.startswith("hardcoded-credential-") for rule_id in ids)
