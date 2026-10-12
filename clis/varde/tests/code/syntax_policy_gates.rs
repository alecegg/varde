use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};
use varde_code::rules::{RuleKind, Severity, builtin_rules};

/// The combined scan emits Elixir/Lua parser diagnostics; contracts live in `builtin_pattern_contracts/eval_more.rs` and `debug_more_a.rs`, with isolated CLI checks in `elixir_lua_rules_are_actionable_in_cli`.
fn is_contract_covered(id: &str) -> bool {
    (id.starts_with("hardcoded-credential-")
        && !matches!(
            id,
            "hardcoded-credential-declaration" | "hardcoded-credential-literal"
        ))
        || id.starts_with("error-swallow-")
        || matches!(
            id,
            "eval-usage-elixir"
                | "eval-usage-lua"
                | "elixir-io-inspect-strict"
                | "elixir-dbg-strict"
        )
}

static NEXT_REPO: AtomicUsize = AtomicUsize::new(0);
struct Repo {
    root: PathBuf,
    home: PathBuf,
}
impl Repo {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "varde-syntax-policy-{}-{}",
            std::process::id(),
            NEXT_REPO.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&root);
        let home = root.with_extension("home");
        let _ = std::fs::remove_dir_all(&home);
        std::fs::create_dir_all(&home).unwrap();
        Self { root, home }
    }
    fn write(&self, path: &str, content: &str) {
        let target = self.root.join(path);
        std::fs::create_dir_all(target.parent().unwrap()).unwrap();
        std::fs::write(target, content).unwrap();
    }
    fn scan(&self, selection: Option<&str>) -> (bool, Value) {
        let build = Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(["map", "build", "--repo-root"])
            .arg(&self.root)
            .env("HOME", &self.home)
            .output()
            .unwrap();
        assert!(
            build.status.success(),
            "index build failed: {:?}",
            build.stderr
        );
        let mut input = serde_json::json!({"repoRoot": self.root});
        if let Some(id) = selection {
            input["gateRules"] = serde_json::json!([id]);
        }
        let output = Command::new(env!("CARGO_BIN_EXE_varde"))
            .args(["scan", "--json", &input.to_string()])
            .env("HOME", &self.home)
            .env("VARDE_USER_RULES_DIR", self.root.join("no-user-rules"))
            .output()
            .unwrap();
        let payload: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(payload["ok"], true, "{payload}");
        assert!(
            payload["data"]["diagnostics"]
                .as_array()
                .unwrap()
                .is_empty(),
            "{payload}"
        );
        (output.status.success(), payload)
    }
}
impl Drop for Repo {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
        let _ = std::fs::remove_dir_all(&self.home);
    }
}

#[test]
fn every_pattern_language_pair_is_actionable_in_cli_and_suppressible() {
    let javascript = "debugger;\neval(input);\nconsole.log(input);\napi_key = \"9abcdefghijklmno\";\nconst password = \"9abcdefghijklmno\";\ntry { work(); } catch (error) {}\ntry { work(); } catch {}\n";
    let sources = [
        ("javascript", "js", javascript),
        ("typescript", "ts", javascript),
        ("tsx", "tsx", javascript),
        ("rust", "rs", "fn main() { dbg!(value); }\n"),
        (
            "python",
            "py",
            "eval(value)\nbreakpoint()\npdb.set_trace()\napi_key = \"9abcdefghijklmno\"\ntry:\n    work()\nexcept ValueError:\n    pass\ntry:\n    work()\nexcept:\n    pass\n",
        ),
        ("swift", "swift", "do { try work() } catch {}\n"),
        (
            "java",
            "java",
            "class Sample { void run() { try { work(); } catch (Exception error) {} } }\n",
        ),
        (
            "csharp",
            "cs",
            "class Sample { void Run() { try { Work(); } catch (Exception error) {} } }\n",
        ),
        (
            "kotlin",
            "kt",
            "fun run() { try { work() } catch (error: Exception) {} }\n",
        ),
        (
            "cpp",
            "cpp",
            "void run() { try { work(); } catch (...) {} }\n",
        ),
        (
            "dart",
            "dart",
            "void run() { try { work(); } catch (error) {} try { work(); } on Exception catch (error) {} }\n",
        ),
        (
            "php",
            "php",
            "<?php eval($input); var_dump($input); dd($input); try { work(); } catch (Exception $error) {}\n",
        ),
        (
            "ruby",
            "rb",
            "eval(input)\nbegin\n  work()\nrescue => error\nend\n",
        ),
        ("bash", "sh", "eval \"$input\"\n"),
    ];
    let repo = Repo::new();
    for (index, (_, ext, source)) in sources.iter().enumerate() {
        repo.write(&format!("src/policy-{index}.{ext}"), source);
    }
    let (success, payload) = repo.scan(None);
    assert!(!success);
    assert_eq!(payload["data"]["gate"]["status"], "fail");
    let mut actual = BTreeSet::new();
    for finding in payload["data"]["findings"].as_array().unwrap() {
        let file = finding["location"]["file"].as_str().unwrap();
        let lang = sources
            .iter()
            .find(|(_, ext, _)| file.ends_with(&format!(".{ext}")))
            .unwrap()
            .0;
        actual.insert((
            finding["rule_id"].as_str().unwrap().to_string(),
            lang.to_string(),
        ));
    }
    let expected: BTreeSet<_> = builtin_rules()
        .into_iter()
        .filter(|r| r.kind == RuleKind::Pattern)
        .filter(|r| !is_contract_covered(&r.id))
        .flat_map(|r| {
            let id = r.id;
            r.languages
                .unwrap()
                .into_iter()
                .map(move |lang| (id.clone(), lang))
        })
        .collect();
    assert_eq!(
        actual, expected,
        "CLI coverage must include every declared pattern/language pair"
    );
    for finding in payload["data"]["findings"].as_array().unwrap() {
        assert_eq!(
            finding["severity"],
            if finding["rule_id"] == "console-log-strict" {
                "info"
            } else if matches!(
                finding["rule_id"].as_str().unwrap(),
                "debug-macro-strict"
                    | "debug-statement-strict"
                    | "python-breakpoint-strict"
                    | "python-pdb-set-trace-strict"
                    | "php-var-dump-strict"
                    | "php-dd-strict"
                    | "elixir-io-inspect-strict"
                    | "elixir-dbg-strict"
                    | "eval-usage-ruby"
                    | "eval-usage-php"
                    | "eval-usage-lua"
                    | "eval-usage-bash"
                    | "eval-usage-elixir"
            )
            {
                "warning"
            } else {
                "error"
            }
        );
    }
    for (index, (lang, ext, source)) in sources.into_iter().enumerate() {
        let text = if lang == "php" {
            source.replacen(
                "<?php",
                "<?php\n// varde-ignore-file -- accepted policy fixture",
                1,
            )
        } else {
            format!(
                "{} varde-ignore-file -- accepted policy fixture\n{source}",
                if matches!(lang, "python" | "ruby" | "bash") {
                    "#"
                } else {
                    "//"
                }
            )
        };
        repo.write(&format!("src/policy-{index}.{ext}"), &text);
    }
    let (success, payload) = repo.scan(None);
    assert!(success, "{payload}");
    assert_eq!(payload["data"]["gate"]["status"], "pass");
    assert!(
        payload["data"]["findings"].as_array().unwrap().is_empty(),
        "{payload}"
    );
}

#[test]
fn elixir_lua_rules_are_actionable_in_cli() {
    for (rule, ext, source) in [
        ("eval-usage-elixir", "ex", "Code.eval_string(input)\n"),
        ("elixir-io-inspect-strict", "ex", "IO.inspect(input)\n"),
        ("elixir-dbg-strict", "ex", "dbg(input)\n"),
        ("eval-usage-lua", "lua", "load(input)\n"),
    ] {
        let repo = Repo::new();
        repo.write(&format!("src/policy.{ext}"), source);
        let (_, payload) = repo.scan(None);
        let findings = payload["data"]["findings"].as_array().unwrap();
        assert_eq!(findings.len(), 1, "{rule}: {payload}");
        assert_eq!(findings[0]["rule_id"], rule, "{rule}");
        assert_eq!(findings[0]["severity"], "warning", "{rule}");
    }
}

/// Findings in `payload` whose rule id is `rule`.
fn findings_for<'a>(payload: &'a Value, rule: &str) -> Vec<&'a Value> {
    payload["data"]["findings"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|finding| finding["rule_id"] == rule)
        .collect()
}

/// Representative end-to-end coverage for the packs `is_contract_covered`
/// exempts from `every_pattern_language_pair_is_actionable_in_cli_and_suppressible`.
/// One snippet per pack proves the CLI scan path, the severity contract,
/// `varde-ignore-file` suppression and `exclude_test_paths` without a fixture
/// per rule-language pair.
#[test]
fn representative_pack_rules_are_actionable_in_cli_and_test_paths_excluded() {
    let cases = [
        (
            "hardcoded-credential-go-short-var",
            "go",
            "package p\nfunc main() { apiKey := \"9abcdefghijklmno\" }\n",
            "//",
        ),
        (
            "hardcoded-credential-kotlin",
            "kt",
            "fun m() { val password = \"9abcdefghijklmno\" }\n",
            "//",
        ),
        (
            "hardcoded-credential-swift-let",
            "swift",
            "let password = \"9abcdefghijklmno\"\n",
            "//",
        ),
        (
            "error-swallow-rust-ok",
            "rs",
            "fn main() { std::fs::remove_file(&path).ok(); }\n",
            "//",
        ),
        ("error-swallow-bash", "sh", "rm -rf /tmp/foo || true\n", "#"),
    ];
    let severities: BTreeMap<String, &'static str> = builtin_rules()
        .into_iter()
        .map(|rule| {
            let name = match rule.severity {
                Severity::Error => "error",
                Severity::Warning => "warning",
                Severity::Info => "info",
            };
            (rule.id, name)
        })
        .collect();

    let repo = Repo::new();
    for (_, ext, snippet, _) in cases {
        repo.write(&format!("src/policy.{ext}"), snippet);
    }
    let (_, payload) = repo.scan(None);
    for (rule, _, _, _) in cases {
        let findings = findings_for(&payload, rule);
        let severity = severities.get(rule).copied().expect("known rule");
        assert_eq!(findings.len(), 1, "{rule}: {payload}");
        assert_eq!(findings[0]["severity"], severity, "{rule}");
    }

    for (_, ext, snippet, comment) in cases {
        repo.write(
            &format!("src/policy.{ext}"),
            &format!("{comment} varde-ignore-file -- accepted policy fixture\n{snippet}"),
        );
    }
    let (_, payload) = repo.scan(None);
    for (rule, _, _, _) in cases {
        assert!(
            findings_for(&payload, rule).is_empty(),
            "{rule} not suppressed: {payload}"
        );
    }

    let tests_repo = Repo::new();
    for (_, ext, snippet, _) in cases {
        tests_repo.write(&format!("tests/policy.{ext}"), snippet);
    }
    let (_, payload) = tests_repo.scan(None);
    for (rule, _, _, _) in cases {
        assert!(
            findings_for(&payload, rule).is_empty(),
            "{rule} reported in a test path: {payload}"
        );
    }
}

#[test]
fn console_is_opt_in_and_debug_test_paths_remain_excluded() {
    let repo = Repo::new();
    repo.write("src/app.ts", "console.log(value);\n");
    repo.write("tests/debug.test.ts", "debugger;\n");
    let (success, payload) = repo.scan(None);
    assert!(success);
    assert_eq!(payload["data"]["gate"]["status"], "pass");
    assert_eq!(payload["data"]["findings"].as_array().unwrap().len(), 1);
    let (success, payload) = repo.scan(Some("console-log-strict"));
    assert!(!success);
    assert_eq!(payload["data"]["gate"]["status"], "fail");
    assert_eq!(payload["data"]["gate"]["blocking_findings"], 1);
}
