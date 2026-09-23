use serde_json::Value;
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};
use varde_code::rules::{RuleKind, builtin_rules};

static NEXT_REPO: AtomicUsize = AtomicUsize::new(0);
struct Repo {
    root: PathBuf,
}
impl Repo {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "varde-syntax-policy-{}-{}",
            std::process::id(),
            NEXT_REPO.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(root.join("home")).unwrap();
        Self { root }
    }
    fn write(&self, path: &str, content: &str) {
        let target = self.root.join(path);
        std::fs::create_dir_all(target.parent().unwrap()).unwrap();
        std::fs::write(target, content).unwrap();
    }
    fn scan(&self, selection: Option<&str>) -> (bool, Value) {
        let mut input = serde_json::json!({"repoRoot": self.root});
        if let Some(id) = selection {
            input["gateRules"] = serde_json::json!([id]);
        }
        let output = Command::new(env!("CARGO_BIN_EXE_varde-code"))
            .args(["scan", "--json", &input.to_string()])
            .env("HOME", self.root.join("home"))
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
            "eval(value)\napi_key = \"9abcdefghijklmno\"\ntry:\n    work()\nexcept ValueError:\n    pass\ntry:\n    work()\nexcept:\n    pass\n",
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
            "<?php try { work(); } catch (Exception $error) {}\n",
        ),
        ("ruby", "rb", "begin\n  work()\nrescue => error\nend\n"),
    ];
    let repo = Repo::new();
    for (_, ext, source) in sources {
        repo.write(&format!("src/policy.{ext}"), source);
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
            } else {
                "error"
            }
        );
    }
    for (lang, ext, source) in sources {
        let text = if lang == "php" {
            source.replacen(
                "<?php",
                "<?php\n// varde-ignore-file -- accepted policy fixture",
                1,
            )
        } else {
            format!(
                "{} varde-ignore-file -- accepted policy fixture\n{source}",
                if matches!(lang, "python" | "ruby") {
                    "#"
                } else {
                    "//"
                }
            )
        };
        repo.write(&format!("src/policy.{ext}"), &text);
    }
    let (success, payload) = repo.scan(None);
    assert!(success, "{payload}");
    assert_eq!(payload["data"]["gate"]["status"], "pass");
    assert!(payload["data"]["findings"].as_array().unwrap().is_empty());
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
