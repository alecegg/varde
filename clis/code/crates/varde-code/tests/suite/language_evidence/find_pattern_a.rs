//! Per-language `find_pattern` call-shape evidence for TS, TSX, JS, Python,
//! Java, Kotlin, C#, Swift, and Go.

use std::path::PathBuf;

use varde_code::query;

fn run(language: &str, extension: &str, pattern: &str) -> serde_json::Value {
    let _query_lock = crate::ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let file = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/find_pattern_fixtures")
        .join(format!("calls.{extension}"));
    let input = format!(
        r#"{{"filePath":"{}","language":"{language}","pattern":"{pattern}"}}"#,
        file.display()
    );
    serde_json::from_str(&query::run_mode("find_pattern", &input)).expect("envelope is JSON")
}

fn texts(env: &serde_json::Value) -> Vec<String> {
    env["data"]["matches"]
        .as_array()
        .expect("matches array")
        .iter()
        .map(|item| item["text"].as_str().expect("match text").to_string())
        .collect()
}

fn assert_call_patterns(language: &str, extension: &str) {
    let one_arg = run(language, extension, "alpha($ARG)");
    assert_eq!(one_arg["ok"], true, "{language}: {one_arg}");
    assert_eq!(texts(&one_arg).len(), 1, "{language}: {one_arg}");

    let any_args = run(language, extension, "alpha($$$ARGS)");
    assert_eq!(any_args["ok"], true, "{language}: {any_args}");
    let matches = texts(&any_args);
    assert_eq!(matches.len(), 2, "{language}: {any_args}");
    assert!(matches.iter().any(|text| text.contains("2, 3")), "{any_args}");
    assert!(matches.iter().all(|text| !text.contains("beta")), "{any_args}");

    let method = run(language, extension, "$RECV.name($$$ARGS)");
    assert_eq!(method["ok"], true, "{language}: {method}");
    let method_matches = texts(&method);
    assert_eq!(method_matches.len(), 1, "{language}: {method}");
    assert!(method_matches[0].contains("name(4)"), "{method}");
}

macro_rules! language_test {
    ($name:ident, $language:literal, $extension:literal) => {
        #[test]
        fn $name() {
            assert_call_patterns($language, $extension);
        }
    };
}

language_test!(typescript_calls, "typescript", "ts");
language_test!(tsx_calls, "tsx", "tsx");
language_test!(javascript_calls, "javascript", "js");
language_test!(python_calls, "python", "py");
language_test!(java_calls, "java", "java");
language_test!(kotlin_calls, "kotlin", "kt");
language_test!(csharp_calls, "csharp", "cs");
language_test!(swift_calls, "swift", "swift");
language_test!(go_calls, "go", "go");
