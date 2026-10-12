use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use ast_grep_language::SupportLang;
use serde::Deserialize;
use varde_code::complexity::{ComplexityConfidenceReason, FunctionComplexity};
use varde_code::{extract, parse};

#[derive(Clone, Copy)]
struct Language {
    name: &'static str,
    lang: SupportLang,
    extension: &'static str,
}

macro_rules! languages {
    ($callback:ident) => {
        $callback!(conformance_csharp, suite_shape_csharp, csharp, CSharp, cs);
        $callback!(
            conformance_typescript,
            suite_shape_typescript,
            typescript,
            TypeScript,
            ts
        );
        $callback!(conformance_tsx, suite_shape_tsx, tsx, Tsx, tsx);
        $callback!(
            conformance_javascript,
            suite_shape_javascript,
            javascript,
            JavaScript,
            js
        );
        $callback!(conformance_python, suite_shape_python, python, Python, py);
        $callback!(conformance_rust, suite_shape_rust, rust, Rust, rs);
        $callback!(conformance_go, suite_shape_go, go, Go, go);
        $callback!(conformance_java, suite_shape_java, java, Java, java);
        $callback!(conformance_c, suite_shape_c, c, C, c);
        $callback!(conformance_cpp, suite_shape_cpp, cpp, Cpp, cpp);
        $callback!(conformance_kotlin, suite_shape_kotlin, kotlin, Kotlin, kt);
        $callback!(conformance_scala, suite_shape_scala, scala, Scala, scala);
        $callback!(conformance_swift, suite_shape_swift, swift, Swift, swift);
        $callback!(conformance_dart, suite_shape_dart, dart, Dart, dart);
        $callback!(conformance_php, suite_shape_php, php, Php, php);
        $callback!(conformance_ruby, suite_shape_ruby, ruby, Ruby, rb);
        $callback!(conformance_lua, suite_shape_lua, lua, Lua, lua);
        $callback!(conformance_bash, suite_shape_bash, bash, Bash, sh);
        $callback!(conformance_elixir, suite_shape_elixir, elixir, Elixir, ex);
        $callback!(
            conformance_haskell,
            suite_shape_haskell,
            haskell,
            Haskell,
            hs
        );
        $callback!(
            conformance_solidity,
            suite_shape_solidity,
            solidity,
            Solidity,
            sol
        );
    };
}

macro_rules! language_tests {
    ($conformance:ident, $shape:ident, $name:ident, $lang:ident, $extension:ident) => {
        #[test]
        fn $conformance() {
            run_conformance(language(
                stringify!($name),
                SupportLang::$lang,
                stringify!($extension),
            ));
        }
        #[test]
        fn $shape() {
            check_suite_shape(language(
                stringify!($name),
                SupportLang::$lang,
                stringify!($extension),
            ));
        }
    };
}

macro_rules! make_language_tests {
    ($conformance:ident, $shape:ident, $name:ident, $lang:ident, $extension:ident) => {
        language_tests!($conformance, $shape, $name, $lang, $extension);
    };
}

languages!(make_language_tests);

fn language(name: &'static str, lang: SupportLang, extension: &'static str) -> Language {
    Language {
        name,
        lang,
        extension,
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Matrix {
    id: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Expected {
    #[serde(default)]
    case: Vec<Case>,
    #[serde(default, rename = "n/a")]
    not_applicable: Vec<NotApplicable>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    callable: String,
    cognitive: u32,
    cyclomatic: u32,
    rule: String,
    #[serde(default)]
    matrix: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct NotApplicable {
    matrix_id: String,
    reason: String,
}

#[derive(Debug)]
struct Suite {
    source: String,
    expected: Expected,
    metrics: Vec<FunctionComplexity>,
}

fn fixture_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/complexity")
}

fn read_matrix(path: &Path) -> Result<BTreeSet<String>, String> {
    let contents =
        fs::read_to_string(path).map_err(|error| format!("{}: {error}", path.display()))?;
    let matrix: Matrix =
        toml::from_str(&contents).map_err(|error| format!("{}: {error}", path.display()))?;
    let ids: BTreeSet<_> = matrix.id.into_iter().collect();
    if ids.is_empty() {
        return Err(format!("{} contains no matrix ids", path.display()));
    }
    Ok(ids)
}

fn expected_path(root: &Path, language: Language) -> PathBuf {
    root.join(language.name).join("expected.toml")
}

fn source_path(root: &Path, language: Language) -> PathBuf {
    root.join(language.name)
        .join(format!("conformance.{}", language.extension))
}

fn read_suite(root: &Path, language: Language) -> Result<Suite, String> {
    let source_path = source_path(root, language);
    let source = fs::read_to_string(&source_path)
        .map_err(|error| format!("{}: {error}", source_path.display()))?;
    let expected_path = expected_path(root, language);
    let contents = fs::read_to_string(&expected_path)
        .map_err(|error| format!("{}: {error}", expected_path.display()))?;
    let expected: Expected = toml::from_str(&contents)
        .map_err(|error| format!("{}: {error}", expected_path.display()))?;
    let parsed = parse::parse_source_for_path(&language.lang, &source_path, &source);
    if parsed.has_error() {
        return Err(format!(
            "{}: source has a parse error",
            source_path.display()
        ));
    }
    let mut entities = extract::extract(&parsed, 0).entities;
    if parsed.masked_preprocessor {
        // The masked retry parses directive-blanked text, so the tree has no
        // preprocessor entities. Restore them from the original source exactly
        // as `scan::extract_source_file` does. Masked retries only occur for C,
        // C++, and C#, whose flags there are `(true, false)`.
        let mut markers = extract::preproc::scan(&source, 0, true, false);
        extract::preproc::attribute_top_level_regions(&mut markers, &entities);
        entities.extend(markers);
    }
    let metrics = varde_code::complexity::function_complexities(&entities);
    for metric in &metrics {
        if metric.confidence_reasons.iter().any(|reason| {
            matches!(
                reason,
                ComplexityConfidenceReason::UnknownControlFlowRole { .. }
            )
        }) {
            return Err(format!(
                "{}: {} has an UnknownControlFlowRole",
                source_path.display(),
                metric.name
            ));
        }
    }
    if expected
        .not_applicable
        .iter()
        .any(|entry| entry.reason.trim().is_empty())
    {
        return Err(format!(
            "{}: an n/a entry has an empty reason",
            expected_path.display()
        ));
    }
    if expected.case.iter().any(|case| case.rule.trim().is_empty()) {
        return Err(format!(
            "{}: a case has an empty rule note",
            expected_path.display()
        ));
    }
    Ok(Suite {
        source,
        expected,
        metrics,
    })
}

fn covered_matrix_ids(expected: &Expected) -> BTreeSet<String> {
    expected
        .case
        .iter()
        .filter_map(|case| {
            case.matrix
                .clone()
                .or_else(|| matrix_id_from_rule(&case.rule))
        })
        .chain(
            expected
                .not_applicable
                .iter()
                .map(|entry| entry.matrix_id.clone()),
        )
        .collect()
}

fn matrix_id_from_rule(rule: &str) -> Option<String> {
    let (_, rest) = rule.split_once("matrix:")?;
    let id = rest
        .split(|character: char| character.is_whitespace() || character == ';')
        .next()?;
    (!id.is_empty()).then(|| id.to_owned())
}

fn validate_suite_coverage(
    expected: &Expected,
    matrix: &BTreeSet<String>,
    label: &str,
) -> Vec<String> {
    let mut errors = Vec::new();
    let mut covered = BTreeSet::new();
    for id in covered_matrix_ids(expected) {
        if !matrix.contains(&id) {
            errors.push(format!("{label}: unknown matrix id {id}"));
        }
        if !covered.insert(id.clone()) {
            errors.push(format!("{label}: duplicate matrix id {id}"));
        }
    }
    for id in matrix.difference(&covered) {
        errors.push(format!("{label}: missing matrix id {id}"));
    }
    errors
}

fn coverage_errors(root: &Path, languages: &[Language], matrix_path: &Path) -> Vec<String> {
    let mut errors = Vec::new();
    let matrix = match read_matrix(matrix_path) {
        Ok(matrix) => matrix,
        Err(error) => return vec![error],
    };
    for language in languages {
        let directory = root.join(language.name);
        if !directory.is_dir() {
            errors.push(format!("missing suite directory {}", directory.display()));
            continue;
        }
        let expected_path = expected_path(root, *language);
        let contents = match fs::read_to_string(&expected_path) {
            Ok(contents) => contents,
            Err(error) => {
                errors.push(format!("{}: {error}", expected_path.display()));
                continue;
            }
        };
        match toml::from_str::<Expected>(&contents) {
            Ok(expected) => {
                errors.extend(validate_suite_coverage(&expected, &matrix, &language.name))
            }
            Err(error) => errors.push(format!("{}: {error}", expected_path.display())),
        }
    }
    errors
}

fn check_suite_shape(language: Language) {
    let root = fixture_root();
    let matrix = read_matrix(&root.join("matrix.toml")).unwrap();
    let suite = read_suite(&root, language).unwrap_or_else(|error| panic!("{error}"));
    assert!(
        !suite.source.is_empty(),
        "{} conformance source is empty",
        language.name
    );
    assert!(
        !suite.expected.case.is_empty(),
        "{} has no conformance cases",
        language.name
    );
    for case in &suite.expected.case {
        assert!(
            suite
                .metrics
                .iter()
                .any(|metric| metric.name == case.callable),
            "{} is missing callable {}",
            language.name,
            case.callable
        );
    }
    let case_names: BTreeSet<_> = suite
        .expected
        .case
        .iter()
        .map(|case| case.callable.as_str())
        .collect();
    let unlabelled: Vec<_> = suite
        .metrics
        .iter()
        .filter(|metric| !case_names.contains(metric.name.as_str()))
        .map(|metric| metric.name.as_str())
        .collect();
    assert!(
        unlabelled.is_empty(),
        "{} has unlabelled callables: {unlabelled:?}",
        language.name
    );
    let errors = validate_suite_coverage(&suite.expected, &matrix, language.name);
    assert!(
        errors.is_empty(),
        "{}: {}",
        language.name,
        errors.join("; ")
    );
}

fn run_conformance(language: Language) {
    check_suite_shape(language);
    let suite = read_suite(&fixture_root(), language).unwrap();
    for case in &suite.expected.case {
        let metric = suite
            .metrics
            .iter()
            .find(|metric| metric.name == case.callable)
            .unwrap();
        assert_eq!(
            metric.cognitive, case.cognitive,
            "{}: {} ({})",
            language.name, case.callable, case.rule
        );
        assert_eq!(
            metric.cyclomatic, case.cyclomatic,
            "{}: {} ({})",
            language.name, case.callable, case.rule
        );
    }
}

fn coverage_report(root: &Path, languages: &[Language], matrix_path: &Path) -> String {
    coverage_errors(root, languages, matrix_path).join("\n")
}

#[test]
fn certified_list_is_the_original_21() {
    let actual = varde_code::certified::CERTIFIED_COMPLEXITY_LANGUAGES;
    let expected = [
        SupportLang::Bash,
        SupportLang::C,
        SupportLang::Cpp,
        SupportLang::CSharp,
        SupportLang::Dart,
        SupportLang::Elixir,
        SupportLang::Go,
        SupportLang::Haskell,
        SupportLang::Java,
        SupportLang::JavaScript,
        SupportLang::Kotlin,
        SupportLang::Lua,
        SupportLang::Php,
        SupportLang::Python,
        SupportLang::Ruby,
        SupportLang::Rust,
        SupportLang::Scala,
        SupportLang::Solidity,
        SupportLang::Swift,
        SupportLang::Tsx,
        SupportLang::TypeScript,
    ];
    assert_eq!(actual, expected);
}

#[test]
fn coverage_check() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("complexity");
    fs::create_dir_all(root.join("rust")).unwrap();
    fs::create_dir_all(root.join("javascript")).unwrap();
    fs::write(root.join("matrix.toml"), "id = [\"if\", \"loops\"]\n").unwrap();
    fs::write(
        root.join("rust/expected.toml"),
        "[[case]]\ncallable = \"f\"\ncognitive = 1\ncyclomatic = 2\nrule = \"matrix:if spec:491\"\n",
    )
    .unwrap();
    fs::write(
        root.join("javascript/expected.toml"),
        "[[case]]\ncallable = \"f\"\ncognitive = 1\ncyclomatic = 2\nrule = \"matrix:if spec:491\"\nskip = true\n",
    )
    .unwrap();
    let listed = [
        language("python", SupportLang::Python, "py"),
        language("rust", SupportLang::Rust, "rs"),
        language("javascript", SupportLang::JavaScript, "js"),
    ];
    let report = coverage_report(&root, &listed, &root.join("matrix.toml"));
    assert!(report.contains("missing suite directory"), "{report}");
    assert!(report.contains("missing matrix id loops"), "{report}");
    assert!(report.contains("unknown field `skip`"), "{report}");
}

/// A source whose parse needs the directive-masked retry (split `extern "C"`
/// block) must still expose its `#if` regions: the masked tree is
/// directive-blanked, so `read_suite` restores them from the original source
/// exactly as `scan::extract_source_file` does. The spec's `#if DEBUG` example
/// (spec:281-291) scores 4 with a lambda and 3 with a plain `if`, matching
/// `scan::run`.
#[test]
fn masked_parse_restores_directive_regions() {
    const C_SOURCE: &str = concat!(
        "#ifdef __cplusplus\n",
        "extern \"C\" {\n",
        "#endif\n",
        "#if DEBUG\n",
        "void myMethod2(void) {\n",
        "  if (ready) { }\n",
        "}\n",
        "#endif\n",
        "#ifdef __cplusplus\n",
        "}\n",
        "#endif\n",
    );
    const CPP_SOURCE: &str = concat!(
        "#ifdef __cplusplus\n",
        "extern \"C\" {\n",
        "#endif\n",
        "#if DEBUG\n",
        "void myMethod2(void) {\n",
        "  auto cb = [] { if (ready) { } };\n",
        "}\n",
        "#endif\n",
        "#ifdef __cplusplus\n",
        "}\n",
        "#endif\n",
    );
    let cases = [
        (language("c", SupportLang::C, "c"), C_SOURCE, 3, 2),
        (language("cpp", SupportLang::Cpp, "cpp"), CPP_SOURCE, 4, 1),
    ];

    for (language, source, cognitive, cyclomatic) in cases {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("complexity");
        let suite_root = root.join(language.name);
        fs::create_dir_all(&suite_root).unwrap();
        let path = suite_root.join(format!("conformance.{}", language.extension));
        fs::write(&path, source).unwrap();
        fs::write(
            suite_root.join("expected.toml"),
            format!(
                "[[case]]\ncallable = \"myMethod2\"\ncognitive = {cognitive}\ncyclomatic = {cyclomatic}\nrule = \"spec:281-291\"\n"
            ),
        )
        .unwrap();

        let parsed = parse::parse_source_for_path(&language.lang, &path, source);
        assert!(
            parsed.masked_preprocessor,
            "{}: fixture must need the masked reparse",
            language.name
        );

        let suite = read_suite(&root, language)
            .unwrap_or_else(|error| panic!("{}: {error}", language.name));
        let runner = suite
            .metrics
            .iter()
            .find(|metric| metric.name == "myMethod2")
            .unwrap_or_else(|| panic!("{}: myMethod2 missing: {:?}", language.name, suite.metrics));
        assert_eq!(
            runner.cognitive, cognitive,
            "{}: runner cognitive",
            language.name
        );

        let output = varde_code::scan::run(path.to_str().unwrap())
            .unwrap_or_else(|error| panic!("{}: scan::run failed: {error}", language.name));
        let production: Vec<_> = varde_code::complexity::function_complexities(&output.entities)
            .into_iter()
            .filter(|metric| metric.name == "myMethod2")
            .collect();
        assert_eq!(
            vec![runner.clone()],
            production,
            "{}: runner metrics must match scan::run",
            language.name
        );
    }
}
