use ast_grep_language::SupportLang;
use varde_code::complexity::{
    ComplexityConfidenceReason, FunctionComplexity, function_complexities,
};
use varde_code::{extract, parse};

struct Fixture {
    name: &'static str,
    lang: SupportLang,
    source: &'static str,
    callable: &'static str,
    cyclomatic: u32,
}

fn metrics(fixture: &Fixture) -> Vec<FunctionComplexity> {
    let parsed = parse::parse_source(&fixture.lang, fixture.source);
    assert!(!parsed.has_error(), "{} fixture must parse", fixture.name);
    let entities = extract::extract(&parsed, 0).entities;
    let metrics = function_complexities(&entities);
    assert!(!metrics.is_empty(), "{} emitted no metrics", fixture.name);
    for metric in &metrics {
        assert!(
            metric.confidence_reasons.iter().all(|reason| !matches!(
                reason,
                ComplexityConfidenceReason::UnknownControlFlowRole { .. }
            )),
            "{} emitted unknown flow roles: {metric:?}",
            fixture.name
        );
    }
    metrics
}

fn assert_fixture(fixture: &Fixture) {
    let metrics = metrics(fixture);
    let metric = metrics
        .iter()
        .find(|metric| metric.name == fixture.callable)
        .unwrap_or_else(|| panic!("{} missing {}: {metrics:?}", fixture.name, fixture.callable));
    assert_eq!(
        metric.cyclomatic, fixture.cyclomatic,
        "{} decision count: {metric:?}",
        fixture.name
    );
}

#[test]
fn every_supported_language_emits_trusted_function_complexity() {
    let fixtures = [
        Fixture {
            name: "typescript",
            lang: SupportLang::TypeScript,
            source: "function f(a: boolean): number { if (a) return 1; return 0; }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "tsx",
            lang: SupportLang::Tsx,
            source: "function View(a: boolean) { if (a) return <A />; return <B />; }",
            callable: "View",
            cyclomatic: 2,
        },
        Fixture {
            name: "javascript",
            lang: SupportLang::JavaScript,
            source: "function f(a) { if (a) return 1; return 0; }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "c",
            lang: SupportLang::C,
            source: "int f(int a) { if (a) return 1; return 0; }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "cpp",
            lang: SupportLang::Cpp,
            source: "int f(bool a) { if (a) return 1; return 0; }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "go",
            lang: SupportLang::Go,
            source: "package p\nfunc f(a bool) int { if a { return 1 }; return 0 }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "java",
            lang: SupportLang::Java,
            source: "class C { static int f(boolean a) { if (a) return 1; return 0; } }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "csharp",
            lang: SupportLang::CSharp,
            source: "class C { static int F(bool a) { if (a) return 1; return 0; } }",
            callable: "F",
            cyclomatic: 2,
        },
        Fixture {
            name: "kotlin",
            lang: SupportLang::Kotlin,
            source: "fun f(a: Boolean): Int { if (a) return 1; return 0 }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "swift",
            lang: SupportLang::Swift,
            source: "func f(_ a: Bool) -> Int { if a { return 1 }; return 0 }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "python",
            lang: SupportLang::Python,
            source: "def f(a):\n    if a:\n        return 1\n    return 0\n",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "ruby",
            lang: SupportLang::Ruby,
            source: "def f(a)\n  if a\n    return 1\n  end\n  0\nend\n",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "php",
            lang: SupportLang::Php,
            source: "<?php function f($a) { if ($a) return 1; return 0; }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "scala",
            lang: SupportLang::Scala,
            source: "object C { def f(a: Boolean): Int = { if (a) 1 else 0 } }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "dart",
            lang: SupportLang::Dart,
            source: "int f(bool a) { if (a) return 1; return 0; }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "lua",
            lang: SupportLang::Lua,
            source: "function f(a)\n  if a then return 1 end\n  return 0\nend\n",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "elixir",
            lang: SupportLang::Elixir,
            source: "defmodule M do\n  def f(a) do\n    if a, do: 1, else: 0\n  end\nend\n",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "solidity",
            lang: SupportLang::Solidity,
            source: "pragma solidity ^0.8.0; contract C { function f(bool a) public pure returns (uint) { if (a) return 1; return 0; } }",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "haskell",
            lang: SupportLang::Haskell,
            source: "f a = if a then 1 else 0\n",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "bash",
            lang: SupportLang::Bash,
            source: "f() { if true; then return 0; fi; return 1; }\n",
            callable: "f",
            cyclomatic: 2,
        },
        Fixture {
            name: "rust",
            lang: SupportLang::Rust,
            source: "fn f(a: bool) -> i32 { if a { return 1; } 0 }",
            callable: "f",
            cyclomatic: 2,
        },
    ];

    assert_eq!(fixtures.len(), parse::SUPPORTED_LANGUAGES.len());
    for fixture in &fixtures {
        assert!(parse::SUPPORTED_LANGUAGES.contains(&fixture.lang));
        assert_fixture(fixture);
    }
}

#[test]
fn anonymous_callables_isolate_their_decisions() {
    let fixtures = [
        Fixture {
            name: "javascript closure",
            lang: SupportLang::JavaScript,
            source: "function outer(a) { if (a) work(); const inner = (b) => { if (b) work(); }; }",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "typescript closure",
            lang: SupportLang::TypeScript,
            source: "function outer(a: boolean) { if (a) work(); const inner = (b: boolean) => { if (b) work(); }; }",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "tsx closure",
            lang: SupportLang::Tsx,
            source: "function Outer(a: boolean) { if (a) work(); const Inner = (b: boolean) => { if (b) return <A />; return <B />; }; }",
            callable: "Outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "cpp lambda",
            lang: SupportLang::Cpp,
            source: "void outer(bool a) { if (a) work(); auto inner = [](bool b) { if (b) work(); }; }",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "go function literal",
            lang: SupportLang::Go,
            source: "package p\nfunc outer(a bool) { if a { work() }; inner := func(b bool) { if b { work() } }; _ = inner }",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "java lambda",
            lang: SupportLang::Java,
            source: "class C { void outer(boolean a) { if (a) work(); java.util.function.Consumer<Boolean> inner = b -> { if (b) work(); }; } }",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "csharp lambda",
            lang: SupportLang::CSharp,
            source: "class C { void Outer(bool a) { if (a) Work(); System.Action<bool> inner = b => { if (b) Work(); }; } }",
            callable: "Outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "kotlin lambda",
            lang: SupportLang::Kotlin,
            source: "fun outer(a: Boolean) { if (a) work(); val inner = { b: Boolean -> if (b) work() } }",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "swift closure",
            lang: SupportLang::Swift,
            source: "func outer(_ a: Bool) { if a { work() }; let inner = { (b: Bool) in if b { work() } } }",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "python lambda",
            lang: SupportLang::Python,
            source: "def outer(a):\n    if a:\n        work()\n    inner = lambda b: 1 if b else 0\n",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "scala lambda",
            lang: SupportLang::Scala,
            source: "object C { def outer(a: Boolean): Unit = { if (a) work(); val inner = (b: Boolean) => { if (b) work() } } }",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "dart closure",
            lang: SupportLang::Dart,
            source: "void outer(bool a) { if (a) work(); var inner = (bool b) { if (b) work(); }; }",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "lua closure",
            lang: SupportLang::Lua,
            source: "function outer(a)\n  if a then work() end\n  queue(function(b) if b then work() end end)\nend\n",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "elixir closure",
            lang: SupportLang::Elixir,
            source: "defmodule M do\n  def outer(a) do\n    if a, do: work()\n    inner = fn b -> if b, do: work() end\n    inner\n  end\nend\n",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "haskell lambda",
            lang: SupportLang::Haskell,
            source: "outer a = let inner = \\b -> if b then 1 else 0 in if a then inner a else 0\n",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "rust closure",
            lang: SupportLang::Rust,
            source: "fn outer(a: bool) { if a { work(); } let inner = |b| if b { 1 } else { 0 }; }",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "php closure",
            lang: SupportLang::Php,
            source: "<?php function outer($a) { if ($a) work(); $inner = function ($b) { if ($b) work(); }; }",
            callable: "outer",
            cyclomatic: 2,
        },
        Fixture {
            name: "ruby block",
            lang: SupportLang::Ruby,
            source: "def outer(a)\n  work if a\n  each do |b|\n    work if b\n  end\nend\n",
            callable: "outer",
            cyclomatic: 2,
        },
    ];

    for fixture in &fixtures {
        let metrics = metrics(fixture);
        let outer = metrics
            .iter()
            .find(|metric| metric.name == fixture.callable)
            .expect("outer callable metric");
        let anonymous = metrics
            .iter()
            .find(|metric| metric.name.starts_with("<anonymous>@"))
            .unwrap_or_else(|| panic!("{} missing anonymous metric: {metrics:?}", fixture.name));
        assert_eq!(outer.cyclomatic, 2, "{} outer: {outer:?}", fixture.name);
        assert_eq!(
            anonymous.cyclomatic, 2,
            "{} anonymous: {anonymous:?}",
            fixture.name
        );
    }
}

#[test]
fn malformed_representative_grammars_report_parse_errors() {
    let malformed = [
        ("braced", SupportLang::Rust, "fn f( {"),
        ("indentation", SupportLang::Python, "def f(:\n  pass\n"),
        ("end delimited", SupportLang::Ruby, "def f(\nend\n"),
        ("markup", SupportLang::Tsx, "function F() { return <A>; }"),
        ("shell", SupportLang::Bash, "f() { if true; then\n"),
        ("functional", SupportLang::Haskell, "f = if then else\n"),
    ];

    for (family, lang, source) in malformed {
        let parsed = parse::parse_source(&lang, source);
        assert!(parsed.has_error(), "{family} fixture unexpectedly parsed");
    }
}
