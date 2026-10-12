use std::fs;
use std::path::PathBuf;

use tempfile::TempDir;
use varde_code::ast_edit::{PreviewOptions, Relation, RewriteRule, preview};

fn tempdir() -> TempDir {
    tempfile::Builder::new()
        .prefix("varde-ast-edit-pattern-")
        .tempdir()
        .expect("temporary directory creates")
}

fn rule(id: &str, pattern: &str, replacement: &str) -> RewriteRule {
    RewriteRule {
        id: id.into(),
        language: "typescript".into(),
        pattern: pattern.into(),
        replacement: replacement.into(),
        inside: None,
        has: None,
        precedes: None,
        follows: None,
    }
}

fn run(source: &str, rules: Vec<RewriteRule>) -> varde_code::ast_edit::PreviewResult {
    let repo = tempdir();
    let store = tempdir();
    fs::write(repo.path().join("main.ts"), source).unwrap();
    let result = preview(&PreviewOptions {
        repository_root: repo.path().to_path_buf(),
        invoking_cwd: repo.path().to_path_buf(),
        paths: vec![PathBuf::from("main.ts")],
        store_dir: store.path().to_path_buf(),
        rules,
    })
    .unwrap();
    assert_eq!(
        fs::read_to_string(repo.path().join("main.ts")).unwrap(),
        source
    );
    result
}

#[test]
fn structural_calls_ignore_formatting_comments_and_string_contents() {
    let result = run(
        "oldCall( 1 ); // oldCall(1)\nconst text = \"oldCall(1)\";\n",
        vec![rule("call", "oldCall($ARG)", "newCall($ARG)")],
    );

    assert!(result.applicable, "{:?}", result.diagnostics);
    let file = &result.proposal.as_ref().unwrap().files[0];
    assert_eq!(file.replacement_count, 1);
    assert_eq!(
        file.replacement_content,
        "newCall(1); // oldCall(1)\nconst text = \"oldCall(1)\";\n"
    );
}

#[test]
fn variadic_capture_preserves_original_separators_and_statement_fragments_match() {
    let result = run(
        "function f() { oldCall(a,  b,\n  c); }\n",
        vec![rule("call", "oldCall($$$ARGS)", "newCall($$$ARGS)")],
    );

    assert!(result.applicable, "{:?}", result.diagnostics);
    assert_eq!(
        result.proposal.as_ref().unwrap().files[0].replacement_content,
        "function f() { newCall(a,  b,\n  c); }\n"
    );
}

#[test]
fn repeated_captures_and_kind_constraints_keep_existing_matcher_semantics() {
    let repeated = run(
        "same(left); same(right);\n",
        vec![rule(
            "repeat-template",
            "same($VALUE)",
            "equal($VALUE, $VALUE)",
        )],
    );
    assert!(repeated.applicable, "{:?}", repeated.diagnostics);
    assert_eq!(
        repeated.proposal.as_ref().unwrap().files[0].replacement_count,
        2
    );
    assert_eq!(
        repeated.proposal.as_ref().unwrap().files[0].replacement_content,
        "equal(left, left); equal(right, right);\n"
    );

    let constrained = run(
        "oldCall(1); oldCall(value);\n",
        vec![rule(
            "identifier-only",
            "oldCall($ARG:identifier)",
            "newCall($ARG)",
        )],
    );
    assert!(constrained.applicable, "{:?}", constrained.diagnostics);
    assert_eq!(
        constrained.proposal.as_ref().unwrap().files[0].replacement_content,
        "oldCall(1); newCall(value);\n"
    );
}

#[test]
fn inside_has_precedes_and_follows_filters_use_structural_relations() {
    let mut inside = rule("inside", "oldCall($ARG)", "newCall($ARG)");
    inside.inside = Some(Relation {
        kind: "function_declaration".into(),
    });
    let nested = run("oldCall(0);\nfunction f() { oldCall(1); }\n", vec![inside]);
    assert!(nested.applicable, "{:?}", nested.diagnostics);
    assert_eq!(
        nested.proposal.as_ref().unwrap().files[0].replacement_count,
        1
    );
    assert_eq!(
        nested.proposal.as_ref().unwrap().files[0].replacement_content,
        "oldCall(0);\nfunction f() { newCall(1); }\n"
    );

    let mut has = rule("has-number", "oldCall($ARG)", "newCall($ARG)");
    has.has = Some(Relation {
        kind: "number".into(),
    });
    let with_descendant = run("oldCall(value); oldCall(2);\n", vec![has]);
    assert!(
        with_descendant.applicable,
        "{:?}",
        with_descendant.diagnostics
    );
    assert_eq!(
        with_descendant.proposal.as_ref().unwrap().files[0].replacement_count,
        1
    );

    let mut precedes = rule("precedes", "oldCall($ARG);", "newCall($ARG);");
    precedes.precedes = Some(Relation {
        kind: "expression_statement".into(),
    });
    let before = run("oldCall(1); nextCall(2);\n", vec![precedes]);
    assert!(before.applicable, "{:?}", before.diagnostics);
    assert_eq!(
        before.proposal.as_ref().unwrap().files[0].replacement_count,
        1
    );

    let mut follows = rule("follows", "oldCall($ARG);", "newCall($ARG);");
    follows.follows = Some(Relation {
        kind: "expression_statement".into(),
    });
    let after = run("previousCall(0); oldCall(1);\n", vec![follows]);
    assert!(after.applicable, "{:?}", after.diagnostics);
    assert_eq!(
        after.proposal.as_ref().unwrap().files[0].replacement_count,
        1
    );
}

#[test]
fn unsupported_relation_shapes_and_invalid_patterns_are_diagnostics() {
    let bad_pattern = run(
        "oldCall(1);\n",
        vec![rule("bad", "oldCall($ARG", "newCall($ARG)")],
    );
    assert!(!bad_pattern.complete);
    assert!(bad_pattern.proposal.is_none());
    assert!(bad_pattern.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "invalid_pattern" || diagnostic.code == "invalid_rule"
    }));
}
