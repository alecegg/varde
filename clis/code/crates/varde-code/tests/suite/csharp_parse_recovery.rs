use ast_grep_language::SupportLang;
use varde_code::parse::{parse_source, parse_source_for_path};
use varde_code::scan;

const IFDEF_REPROS: &[(&str, &str)] = &[
    (
        "expression-split",
        "class C { bool M(bool p, bool a, bool b, bool q) => p &&\n#if NET\n a &&\n#else\n b &&\n#endif\n q; }\n",
    ),
    (
        "condition-split",
        "class C { void M(bool a, bool b) { if (a\n#if NET\n && b\n#else\n || b\n#endif\n ) { } } }\n",
    ),
    (
        "switch-arm-split",
        "class C { void M(int n) { switch (n) { case 0:\n#if NET\n case 1:\n#else\n case 2:\n#endif\n break; } } }\n",
    ),
    (
        "statement-split",
        "class C { void M(bool value) { if (value)\n#if NET\n System.Console.WriteLine(1);\n#else\n System.Console.WriteLine(2);\n#endif\n } }\n",
    ),
];

#[test]
fn csharp_ifdef_masked_reparse() {
    let dir = std::env::temp_dir().join(format!("varde-csharp-recovery-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("create temporary test directory");

    for (name, source) in IFDEF_REPROS {
        let path = dir.join(format!("{name}.cs"));
        std::fs::write(&path, source).expect("write repro");
        let parsed = parse_source_for_path(&SupportLang::CSharp, &path, source);
        assert!(
            !parsed.has_error(),
            "{name} did not parse cleanly after masking"
        );
        assert_eq!(
            parsed.root.root().text().len(),
            source.len(),
            "{name} changed byte offsets"
        );

        let output =
            scan::run(path.to_str().expect("UTF-8 temporary path")).expect("scan recovered source");
        assert!(
            !output
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.message.contains("syntax error")),
            "{name} still produced a syntax diagnostic: {:?}",
            output.diagnostics
        );
        let marker = output
            .entities
            .iter()
            .find(|entity| entity.name == "preproc_if")
            .unwrap_or_else(|| panic!("{name} lost directive markers from the original source"));
        assert_eq!(
            marker.span.start_byte as usize,
            source.find("#if").expect("if directive"),
            "{name} directive marker must use original-source offsets"
        );
    }

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn csharp_known_grammar_gaps() {
    let gaps = [
        (
            "required identifier",
            "class C { void M() { required.Add(\"x\"); } }",
        ),
        (
            "lambda parameter in",
            "using System; class C { void M() { Func<int, int> f = (in int x) => x; } }",
        ),
        (
            "async named argument",
            "class C { void M() { G(async: true); } static void G(bool async) { } }",
        ),
        (
            "field access in collection expression",
            "class C { void M() { int[] values = [field.Number]; } }",
        ),
    ];

    for (name, source) in gaps {
        let parsed = parse_source(&SupportLang::CSharp, source);
        assert!(
            parsed.has_error(),
            "known_grammar_gap {name} unexpectedly parsed cleanly"
        );
    }

    let mixed_error =
        "class C { void M() { required.Add(\"x\");\n#if NET\n int value = 1;\n#endif\n } }";
    assert!(
        parse_source_for_path(
            &SupportLang::CSharp,
            std::path::Path::new("mixed-error.cs"),
            mixed_error
        )
        .has_error(),
        "a non-directive grammar error must remain after masked retry"
    );
}
