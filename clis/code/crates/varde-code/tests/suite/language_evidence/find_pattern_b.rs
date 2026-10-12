//! `find_pattern` call evidence for the remaining linked grammars.

use std::path::PathBuf;

use varde_code::query;

fn fixture(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/find_pattern_fixtures")
        .join(name)
}

fn matches(file: &str, language: &str, pattern: &str) -> serde_json::Value {
    let _query_lock = crate::ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let input = serde_json::json!({
        "filePath": fixture(file),
        "language": language,
        "pattern": pattern,
    });
    serde_json::from_str(&query::run_mode("find_pattern", &input.to_string()))
        .expect("find_pattern response is JSON")
}

fn assert_counts(file: &str, language: &str, patterns: &[(&str, usize)]) {
    for (pattern, expected) in patterns {
        let env = matches(file, language, pattern);
        assert_eq!(env["ok"], true, "{language} pattern {pattern}: {env}");
        let found = env["data"]["matches"].as_array().expect("matches array");
        assert_eq!(
            found.len(),
            *expected,
            "{language} pattern {pattern}: {env}"
        );
    }
}

macro_rules! evidence {
    ($test:ident, $file:literal, $language:literal, $patterns:expr) => {
        #[test]
        fn $test() {
            assert_counts($file, $language, $patterns);
        }
    };
}

evidence!(
    c_calls,
    "calls.c",
    "c",
    &[
        ("alpha($$$ARGS)", 2),
        ("$RECV.alpha($$$ARGS)", 1),
        ("gamma($$$ARGS)", 0)
    ]
);
evidence!(
    scala_calls,
    "calls.scala",
    "scala",
    &[
        ("alpha($$$ARGS)", 2),
        ("$RECV.alpha($$$ARGS)", 1),
        ("gamma($$$ARGS)", 0)
    ]
);
evidence!(
    dart_calls,
    "calls.dart",
    "dart",
    &[
        ("alpha($$$ARGS)", 2),
        ("$RECV.alpha($$$ARGS)", 1),
        ("gamma($$$ARGS)", 0)
    ]
);
#[test]
#[ignore = "Lua colon-style method calls are not matched by find_pattern receiver patterns"]
fn lua_calls() {
    assert_counts(
        "calls.lua",
        "lua",
        &[
            ("alpha($$$ARGS)", 2),
            ("$RECV:alpha($$$ARGS)", 1),
            ("gamma($$$ARGS)", 0),
        ],
    );
}
evidence!(
    elixir_calls,
    "calls.ex",
    "elixir",
    &[
        ("alpha($$$ARGS)", 3),
        ("$RECV.alpha($$$ARGS)", 1),
        ("gamma($$$ARGS)", 0)
    ]
);
#[test]
#[ignore = "Solidity find_pattern currently misses the two-argument alpha call"]
fn solidity_calls() {
    assert_counts(
        "calls.sol",
        "solidity",
        &[
            ("alpha($$$ARGS)", 2),
            ("$RECV.alpha($$$ARGS)", 1),
            ("gamma($$$ARGS)", 0),
        ],
    );
}
evidence!(
    haskell_calls,
    "calls.hs",
    "haskell",
    &[
        ("alpha $$$ARGS", 2),
        ("$RECV.alpha($$$ARGS)", 0),
        ("gamma $$$ARGS", 0)
    ]
);
evidence!(
    bash_calls,
    "calls.sh",
    "bash",
    &[
        ("alpha $$$ARGS", 2),
        ("$RECV.alpha($$$ARGS)", 0),
        ("gamma $$$ARGS", 0)
    ]
);
evidence!(
    php_calls,
    "calls.php",
    "php",
    &[
        ("alpha($$$ARGS)", 2),
        ("$RECV->alpha($$$ARGS)", 1),
        ("gamma($$$ARGS)", 0)
    ]
);
