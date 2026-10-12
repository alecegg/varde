use std::collections::BTreeSet;
use varde_code::rules::{
    ConstraintSpec, Rule, RuleKind, TestCase, builtin_rules, test_runner::run_pattern_rule_tests,
};

/// One rule's fixture contract: snippets that must not match (`valid`) and
/// must match (`invalid`), scoped to the languages the rule declares.
pub struct Case {
    pub id: &'static str,
    pub languages: &'static [&'static str],
    pub invalid: Vec<String>,
    pub valid: Vec<String>,
}

impl Case {
    pub fn new(
        id: &'static str,
        languages: &'static [&'static str],
        invalid: Vec<String>,
        valid: Vec<String>,
    ) -> Case {
        Case {
            id,
            languages,
            invalid,
            valid,
        }
    }
}

// Each pack's contracts live in its own module, included by path so Cargo does
// not auto-discover them as separate test targets.
#[path = "../builtin_pattern_contracts/credential_go.rs"]
mod credential_go;
#[path = "../builtin_pattern_contracts/credential_jvm_dotnet.rs"]
mod credential_jvm_dotnet;
#[path = "../builtin_pattern_contracts/credential_native_apple.rs"]
mod credential_native_apple;
#[path = "../builtin_pattern_contracts/credential_native_apple_class.rs"]
mod credential_native_apple_class;
#[path = "../builtin_pattern_contracts/credential_other.rs"]
mod credential_other;
#[path = "../builtin_pattern_contracts/credential_rust.rs"]
mod credential_rust;
#[path = "../builtin_pattern_contracts/credential_scripting.rs"]
mod credential_scripting;
#[path = "../builtin_pattern_contracts/debug_more_a.rs"]
mod debug_more_a;
#[path = "../builtin_pattern_contracts/debug_more_b.rs"]
mod debug_more_b;
#[path = "../builtin_pattern_contracts/eval_more.rs"]
mod eval_more;
#[path = "../builtin_pattern_contracts/swallow_c_scala_solidity.rs"]
mod swallow_c_scala_solidity;
#[path = "../builtin_pattern_contracts/swallow_elixir_haskell.rs"]
mod swallow_elixir_haskell;
#[path = "../builtin_pattern_contracts/swallow_go.rs"]
mod swallow_go;
#[path = "../builtin_pattern_contracts/swallow_lua_bash.rs"]
mod swallow_lua_bash;
#[path = "../builtin_pattern_contracts/swallow_rust.rs"]
mod swallow_rust;

fn contract(rule: &Rule, language: &str, invalid: Vec<String>, valid: Vec<String>) {
    let grammar = varde_code::parse::language_from_name(language).expect("declared grammar");
    for snippet in invalid.iter().chain(&valid) {
        assert!(
            !varde_code::parse::parse_source(&grammar, snippet).has_error(),
            "{} {language} fixture must parse: {snippet}",
            rule.id
        );
    }
    let mut scoped = rule.clone();
    scoped.languages = Some(vec![language.to_string()]);
    scoped.test = Some(vec![TestCase {
        name: format!("{language} contract"),
        valid: Some(valid),
        invalid: Some(invalid),
        expect_rewrite: None,
        fixture: None,
        expect_rows: None,
    }]);
    let results = run_pattern_rule_tests(&scoped);
    assert_eq!(results.len(), 1, "{} {language}", rule.id);
    assert!(
        results[0].pass,
        "{} {language}: {:?}",
        rule.id, results[0].detail
    );
}

fn shipped(id: &str) -> Rule {
    builtin_rules()
        .into_iter()
        .find(|rule| rule.id == id)
        .unwrap_or_else(|| panic!("missing builtin rule {id}"))
}

fn strings(values: &[&str]) -> Vec<String> {
    values.iter().map(|value| (*value).to_string()).collect()
}

#[test]
fn debug_na_languages_have_no_debug_or_console_rules() {
    let no_debug_rule_languages = ["c", "cpp", "csharp", "go", "java", "kotlin", "scala", "swift", "dart", "lua", "bash", "haskell", "solidity"];
    for rule in builtin_rules().into_iter().filter(|rule| {
        let id = rule.id.to_ascii_lowercase();
        let pattern = rule.pattern.as_deref().unwrap_or_default().to_ascii_lowercase();
        ["debug", "console", "breakpoint", "byebug", "pry", "dump", "dbg"]
            .iter().any(|family| id.contains(family) || pattern.contains(family))
            || ["console.", "debugger", "dbg!", "io.inspect", "print_r", "var_dump"]
                .iter().any(|family| pattern.contains(family))
    }) {
        let languages = rule.languages.as_deref().unwrap_or_default();
        for language in no_debug_rule_languages {
            assert!(!languages.iter().any(|declared| declared == language), "{} must not cover {language}: debug/console family is N/A", rule.id);
        }
    }
}

#[test]
fn every_shipped_pattern_rule_has_language_contracts() {
    let existing = [
        (
            "debug-macro-strict",
            &["rust"][..],
            strings(&["fn main() { dbg!(value); }"]),
            strings(&["fn main() { let value = 1; }"]),
        ),
        (
            "debug-statement-strict",
            &["javascript", "typescript", "tsx"][..],
            strings(&["debugger;"]),
            strings(&["const value = 1;"]),
        ),
        (
            "console-log-strict",
            &["javascript", "typescript", "tsx"][..],
            strings(&["console.log(value);"]),
            strings(&["console.info(value);"]),
        ),
        (
            "eval-usage",
            &["javascript", "typescript", "tsx"][..],
            strings(&["eval(value);"]),
            strings(&["safe_eval(value);", "obj.eval(value);"]),
        ),
        (
            "eval-usage",
            &["python"][..],
            strings(&["eval(value)"]),
            strings(&["safe_eval(value)", "obj.eval(value)"]),
        ),
        (
            "empty-catch-block",
            &["javascript", "typescript", "tsx"][..],
            strings(&[
                "try { work(); } catch (error) { }",
                "try { work(); } catch (error) {}",
                "try { work(); } catch (error) {\n}",
            ]),
            strings(&[
                "try { work(); } catch (error) { log(error); }",
                "try { work(); } catch (error) { /* intentional */ }",
            ]),
        ),
        (
            "empty-catch-block-unbound",
            &["javascript", "typescript", "tsx"][..],
            strings(&[
                "try { work(); } catch { }",
                "try { work(); } catch {}",
                "try { work(); } catch {\n}",
            ]),
            strings(&[
                "try { work(); } catch { log(); }",
                "try { work(); } catch { /* intentional */ }",
            ]),
        ),
        (
            "empty-except-block",
            &["python"][..],
            strings(&["try:\n    pass\nexcept ValueError: pass"]),
            strings(&[
                "try:\n    pass\nexcept ValueError: handle()",
                "try:\n    pass\nexcept ImportError: pass",
                "try:\n    pass\nexcept ValueError: # intentional\n    pass",
            ]),
        ),
        (
            "empty-except-block-bare",
            &["python"][..],
            strings(&["try:\n    risky()\nexcept: pass"]),
            strings(&[
                "try:\n    risky()\nexcept: handle()",
                "try:\n    risky()\nexcept: # intentional\n    pass",
            ]),
        ),
        (
            "empty-catch-block-java",
            &["java"][..],
            strings(&[
                "try { work(); } catch (IOException error) { }",
                "try { work(); } catch (IOException error) {}",
                "try { work(); } catch (IOException error) {\n}",
            ]),
            strings(&[
                "try { work(); } catch (IOException error) { log(error); }",
                "try { work(); } catch (IOException error) { /* intentional */ }",
            ]),
        ),
        (
            "empty-catch-block-csharp",
            &["csharp"][..],
            strings(&[
                "class C { void M() { try { work(); } catch (Exception error) { } } }",
                "class C { void M() { try { work(); } catch (Exception error) {} } }",
                "class C { void M() { try { work(); } catch (Exception error) {\n} } }",
            ]),
            strings(&[
                "class C { void M() { try { work(); } catch (Exception error) { log(error); } } }",
                "class C { void M() { try { work(); } catch (Exception error) { /* intentional */ } } }",
            ]),
        ),
        (
            "empty-catch-block-kotlin",
            &["kotlin"][..],
            strings(&[
                "try { work() } catch (error: IOException) { }",
                "try { work() } catch (error: IOException) {}",
                "try { work() } catch (error: IOException) {\n}",
            ]),
            strings(&[
                "try { work() } catch (error: IOException) { log(error) }",
                "try { work() } catch (error: IOException) { /* intentional */ }",
            ]),
        ),
        (
            "empty-catch-block-dart",
            &["dart"][..],
            strings(&[
                "void main() { try { work(); } catch (error) { } }",
                "void main() { try { work(); } catch (error) {} }",
                "void main() { try { work(); } catch (error) {\n} }",
            ]),
            strings(&[
                "void main() { try { work(); } catch (error) { log(error); } }",
                "void main() { try { work(); } catch (error) { /* intentional */ } }",
            ]),
        ),
        (
            "empty-catch-block-dart-typed",
            &["dart"][..],
            strings(&[
                "void main() { try { work(); } on IOException catch (error) { } }",
                "void main() { try { work(); } on IOException catch (error) {} }",
                "void main() { try { work(); } on IOException catch (error) {\n} }",
            ]),
            strings(&[
                "void main() { try { work(); } on IOException catch (error) { log(error); } }",
                "void main() { try { work(); } on IOException catch (error) { /* intentional */ } }",
            ]),
        ),
        (
            "empty-catch-block-php",
            &["php"][..],
            strings(&[
                "<?php try { work(); } catch (Exception $error) { }",
                "<?php try { work(); } catch (Exception $error) {}",
                "<?php try { work(); } catch (Exception $error) {\n}",
            ]),
            strings(&[
                "<?php try { work(); } catch (Exception $error) { log($error); }",
                "<?php try { work(); } catch (Exception $error) { /* intentional */ }",
            ]),
        ),
        (
            "empty-catch-block-cpp",
            &["cpp"][..],
            strings(&[
                "void f() { try { work(); } catch (const std::exception& error) { } }",
                "void f() { try { work(); } catch (...) { } }",
                "void f() { try { work(); } catch (...) {} }",
                "void f() { try { work(); } catch (...) {\n} }",
            ]),
            strings(&[
                "void f() { try { work(); } catch (const std::exception& error) { log(error); } }",
                "void f() { try { work(); } catch (const std::exception& error) { /* intentional */ } }",
            ]),
        ),
        (
            "empty-catch-block-ruby",
            &["ruby"][..],
            strings(&["begin\n  work\nrescue => error\nend"]),
            strings(&[
                "begin\n  work\nrescue => error\n  log(error)\nend",
                "begin\n  work\nrescue => error\n  # intentional\nend",
            ]),
        ),
        (
            "empty-catch-block-swift",
            &["swift"][..],
            strings(&[
                "do { try work() } catch { }",
                "do { try work() } catch {}",
                "do { try work() } catch {\n}",
            ]),
            strings(&[
                "do { try work() } catch { print(\"error\") }",
                "do { try work() } catch { /* intentional */ }",
            ]),
        ),
        (
            "hardcoded-credential-literal",
            &["python", "javascript", "typescript", "tsx"][..],
            strings(&["api_key = \"9abcdefghijklmno\""]),
            strings(&["api_key = \"9abcdefghijklmn\""]),
        ),
        (
            "hardcoded-credential-declaration",
            &["javascript", "typescript", "tsx"][..],
            strings(&["const api_key = \"9abcdefghijklmno\";"]),
            strings(&["const api_key = \"9abcdefghijklmn\";"]),
        ),
        // Widened shared VAL: backtick/template literals (JS/TS/TSX) and raw,
        // triple-quoted and f/b-prefixed literals (Python). Interpolated forms
        // stay valid.
        (
            "hardcoded-credential-literal",
            &["javascript", "typescript", "tsx"][..],
            strings(&[
                "api_key = `9abcdefghijklmno`",
                "api_key = `\n9abcdefghijklmno\n`",
            ]),
            strings(&[
                "api_key = `abc${secret}9abcdefghijklmno`",
                "api_key = `9abcdefghijklmn`",
            ]),
        ),
        (
            "hardcoded-credential-literal",
            &["python"][..],
            strings(&[
                "api_key = r\"9abcdefghijklmno\"",
                "api_key = r'9abcdefghijklmno'",
                "api_key = '''9abcdefghijklmno'''",
                "api_key = \"\"\"\n9abcdefghijklmno\n\"\"\"",
                "api_key = f\"9abcdefghijklmno\"",
                "api_key = b\"9abcdefghijklmno\"",
            ]),
            strings(&[
                "api_key = f\"abc{secret}9abcdefghijklmno\"",
                "api_key = b\"9abcdefghijklmn\"",
            ]),
        ),
        (
            "hardcoded-credential-declaration",
            &["javascript", "typescript", "tsx"][..],
            strings(&["const api_key = `9abcdefghijklmno`;"]),
            strings(&["const api_key = `abc${secret}9abcdefghijklmno`;"]),
        ),
    ];
    let mut cases: Vec<Case> = existing
        .into_iter()
        .map(|(id, languages, invalid, valid)| Case::new(id, languages, invalid, valid))
        .collect();
    cases.extend(credential_rust::cases());
    cases.extend(credential_go::cases());
    cases.extend(credential_jvm_dotnet::cases());
    cases.extend(credential_native_apple::cases());
    cases.extend(credential_native_apple_class::cases());
    cases.extend(credential_scripting::cases());
    cases.extend(credential_other::cases());
    cases.extend(eval_more::cases());
    cases.extend(debug_more_a::cases());
    cases.extend(debug_more_b::cases());
    cases.extend(swallow_rust::cases());
    cases.extend(swallow_go::cases());
    cases.extend(swallow_c_scala_solidity::cases());
    cases.extend(swallow_lua_bash::cases());
    cases.extend(swallow_elixir_haskell::cases());
    let mut covered = BTreeSet::new();
    for case in cases {
        let rule = shipped(case.id);
        assert_eq!(rule.kind, RuleKind::Pattern);
        for language in case.languages {
            covered.insert((case.id.to_string(), (*language).to_string()));
            contract(&rule, language, case.invalid.clone(), case.valid.clone());
        }
    }
    let expected: BTreeSet<_> = builtin_rules()
        .into_iter()
        .filter(|rule| rule.kind == RuleKind::Pattern)
        .flat_map(|rule| {
            let id = rule.id;
            let languages = rule
                .languages
                .expect("shipped pattern has explicit coverage");
            assert!(!languages.is_empty(), "{id} must declare tested languages");
            languages
                .into_iter()
                .map(move |language| (id.clone(), language))
        })
        .collect();
    assert_eq!(
        covered, expected,
        "pattern language contract coverage drifted"
    );
}

#[test]
fn credential_rules_require_length_and_digit_evidence_per_language() {
    let values = ["9abcdefghijklmno", "abcdefg9hijklmno", "abcdefghijklmno9"];
    let mut positive_assignment = Vec::new();
    let mut positive_declaration = Vec::new();
    for value in values {
        positive_assignment.push(format!("api_key = \"{value}\""));
        positive_declaration.push(format!("const api_key = \"{value}\";"));
    }
    let negative = vec![
        "api_key = \"9abcdefghijklmn\"".to_string(),
        "api_key = \"abcdefghijklmnop\"".to_string(),
        "config.api_key = \"9abcdefghijklmnop\"".to_string(),
        "api_key = process.env.API_KEY".to_string(),
    ];
    let literal = shipped("hardcoded-credential-literal");
    for language in ["python", "javascript", "typescript", "tsx"] {
        contract(
            &literal,
            language,
            positive_assignment.clone(),
            negative.clone(),
        );
    }

    let declaration = shipped("hardcoded-credential-declaration");
    for language in ["javascript", "typescript", "tsx"] {
        let declaration_negative = vec![
            "const api_key = \"9abcdefghijklmn\";".to_string(),
            "const api_key = \"abcdefghijklmnop\";".to_string(),
            "const api_key = process.env.API_KEY;".to_string(),
            "const api_key = \"hunter2\";".to_string(),
            "config.api_key = \"9abcdefghijklmno\";".to_string(),
        ];
        contract(
            &declaration,
            language,
            positive_declaration.clone(),
            declaration_negative,
        );
    }
}

fn credential_constraints(rule: &Rule) -> (ConstraintSpec, ConstraintSpec) {
    let constraints = rule
        .constraints
        .as_ref()
        .unwrap_or_else(|| panic!("{} declares constraints", rule.id));
    let key = constraints
        .get("KEY")
        .unwrap_or_else(|| panic!("{} declares a KEY constraint", rule.id))
        .clone();
    let val = constraints
        .get("VAL")
        .unwrap_or_else(|| panic!("{} declares a VAL constraint", rule.id))
        .clone();
    (key, val)
}

#[test]
fn credential_rules_share_key_and_val_constraints() {
    let mut credential_rules: Vec<Rule> = builtin_rules()
        .into_iter()
        .filter(|rule| rule.id.starts_with("hardcoded-credential"))
        .collect();
    assert!(
        !credential_rules.is_empty(),
        "at least one hardcoded-credential rule ships"
    );
    let (key, val) = credential_constraints(&credential_rules.remove(0));
    for rule in &credential_rules {
        let (other_key, other_val) = credential_constraints(rule);
        assert_eq!(other_key, key, "{} KEY regex drifted", rule.id);
        assert_eq!(other_val, val, "{} VAL regexes drifted", rule.id);
    }
}
