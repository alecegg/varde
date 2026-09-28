use std::collections::BTreeSet;
use varde_code::rules::{
    Rule, RuleKind, TestCase, builtin_rules, test_runner::run_pattern_rule_tests,
};

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
fn every_shipped_pattern_rule_has_language_contracts() {
    let cases = [
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
    ];
    let mut covered = BTreeSet::new();
    for (id, languages, invalid, valid) in cases {
        let rule = shipped(id);
        assert_eq!(rule.kind, RuleKind::Pattern);
        for language in languages {
            covered.insert((id.to_string(), (*language).to_string()));
            contract(&rule, language, invalid.clone(), valid.clone());
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
