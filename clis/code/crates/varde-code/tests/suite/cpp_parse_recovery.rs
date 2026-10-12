use ast_grep_language::SupportLang;
use varde_code::model::{Entity, EntityKind};
use varde_code::parse::parse_source_for_path;
use varde_code::scan;

const SPLIT_EXTERN_C: &str = "#ifdef __cplusplus\nextern \"C\" {\n#endif\nint f(int value) { return value; }\n#ifdef __cplusplus\n}\n#endif\n";

fn write_source(name: &str, extension: &str, source: &str) -> std::path::PathBuf {
    let directory =
        std::env::temp_dir().join(format!("varde-cpp-recovery-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&directory);
    std::fs::create_dir_all(&directory).expect("create temporary test directory");
    let path = directory.join(format!("{name}.{extension}"));
    std::fs::write(&path, source).expect("write parser repro");
    path
}

fn scanned(path: &std::path::Path) -> varde_code::model::ExtractOutput {
    scan::run(path.to_str().expect("UTF-8 temporary path")).expect("scan parser repro")
}

fn assert_clean_output(output: &varde_code::model::ExtractOutput, name: &str) {
    assert!(
        !output
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("syntax error")),
        "{name} still produced a syntax diagnostic: {:?}",
        output.diagnostics
    );
}

fn function<'a>(entities: &'a [Entity], name: &str) -> &'a Entity {
    entities
        .iter()
        .find(|entity| entity.kind == EntityKind::Function && entity.name == name)
        .unwrap_or_else(|| panic!("callable {name} was not extracted: {entities:?}"))
}

fn assert_function_span(source: &str, entity: &Entity, text: &str, line: u32) {
    let start = source.find(text).expect("callable source text");
    assert_eq!(entity.span.start_byte as usize, start);
    assert_eq!(entity.span.end_byte as usize, start + text.len());
    assert_eq!(entity.span.start_line, line);
    assert_eq!(entity.span.end_line, line);
}

#[test]
fn split_extern_c_reparses_for_c_and_cpp_paths() {
    let cases = [
        ("header", "h", SupportLang::C),
        ("source", "cpp", SupportLang::Cpp),
    ];

    for (name, extension, lang) in cases {
        let path = write_source(name, extension, SPLIT_EXTERN_C);
        let parsed = parse_source_for_path(&lang, &path, SPLIT_EXTERN_C);
        assert!(
            !parsed.has_error(),
            "{name} split extern-C source did not parse cleanly"
        );
        assert_eq!(parsed.root.root().range().end, SPLIT_EXTERN_C.len());

        let output = scanned(&path);
        assert_clean_output(&output, name);
        assert_function_span(
            SPLIT_EXTERN_C,
            function(&output.entities, "f"),
            "int f(int value) { return value; }",
            4,
        );
    }
}

#[test]
fn guarded_header_restores_only_inner_directive_regions() {
    let source = "#ifndef API_H\n#define API_H\n#ifdef __cplusplus\nextern \"C\" {\n#endif\nint f(int value) { return value; }\n#ifdef __cplusplus\n}\n#endif\n#endif\n";
    let path = write_source("guarded", "h", source);
    let output = scanned(&path);

    assert_clean_output(&output, "guarded header");
    assert_function_span(
        source,
        function(&output.entities, "f"),
        "int f(int value) { return value; }",
        6,
    );
    let conditions: Vec<_> = output
        .entities
        .iter()
        .filter(|entity| entity.kind == EntityKind::ControlFlow && entity.name == "preproc_if")
        .collect();
    assert_eq!(conditions.len(), 2, "include guard must stay excluded");
    assert_eq!(conditions[0].span.start_line, 3);
    assert_eq!(conditions[1].span.start_line, 7);
}

#[test]
fn alternative_branch_retry_keeps_first_valid_initializer() {
    let source = "int f(int value) {\n    int chosen =\n#if A\n        1\n#else\n        2\n#endif\n        ;\n    return chosen + value;\n}\n";
    let path = write_source("alternative", "cpp", source);
    let parsed = parse_source_for_path(&SupportLang::Cpp, &path, source);
    assert!(
        !parsed.has_error(),
        "first-branch masked reparse should produce a clean tree"
    );
    assert_eq!(parsed.root.root().text().len(), source.len());

    let output = scanned(&path);
    assert_clean_output(&output, "alternative pair");
    let callable = function(&output.entities, "f");
    assert_eq!(
        callable.span.start_byte as usize,
        source.find("int f").unwrap()
    );
    assert_eq!(
        callable.span.end_byte as usize,
        source.rfind('}').unwrap() + 1
    );
    assert_eq!(callable.span.start_line, 1);
    assert_eq!(callable.span.end_line, 10);
    assert!(
        output.entities.iter().any(|entity| {
            entity.kind == EntityKind::ControlFlow && entity.name == "preproc_if"
        })
    );
}

#[test]
fn already_clean_file_keeps_its_original_tree() {
    let source = "#if FEATURE\nint clean(int value) { return value; }\n#endif\n";
    let path = write_source("clean", "cpp", source);
    let parsed = parse_source_for_path(&SupportLang::Cpp, &path, source);

    assert!(!parsed.has_error(), "clean source must stay clean");
    assert_eq!(parsed.root.root().text(), source);
    assert_eq!(parsed.root.root().text().len(), source.len());

    let output = scanned(&path);
    assert_clean_output(&output, "already-clean file");
    assert_function_span(
        source,
        function(&output.entities, "clean"),
        "int clean(int value) { return value; }",
        2,
    );
}

#[test]
fn unrelated_syntax_error_still_reports_a_diagnostic() {
    let source = "int f(int value) { return value; }\n#if FEATURE\nint g() { return 1; }\n#endif\nint broken( { return 0; }\n";
    let path = write_source("broken", "cpp", source);
    let parsed = parse_source_for_path(&SupportLang::Cpp, &path, source);

    assert!(parsed.has_error(), "unrelated syntax error was hidden");
    let output = scanned(&path);
    assert!(
        output
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.message.contains("syntax error")),
        "unrelated syntax error must remain diagnostic: {:?}",
        output.diagnostics
    );
}
