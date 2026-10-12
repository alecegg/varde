use std::fs;
use std::path::PathBuf;

use ast_grep_language::SupportLang;
use tempfile::TempDir;
use varde_code::ast_edit::{ApplyOptions, PreviewOptions, RewriteRule, apply, preview};

struct Fixture {
    extension: &'static str,
    source: &'static str,
    pattern: &'static str,
    replacement: &'static str,
}

fn fixture(language: SupportLang) -> Option<Fixture> {
    use SupportLang::*;
    Some(match language {
        Bash => Fixture {
            extension: "sh",
            source: "echo needle\n",
            pattern: "needle",
            replacement: "target",
        },
        C => Fixture {
            extension: "c",
            source: "int needle = 1;\n",
            pattern: "needle",
            replacement: "target",
        },
        Cpp => Fixture {
            extension: "cpp",
            source: "int needle = 1;\n",
            pattern: "needle",
            replacement: "target",
        },
        CSharp => Fixture {
            extension: "cs",
            source: "class C { void M() { needle(); } }\n",
            pattern: "needle()",
            replacement: "target()",
        },
        Css => Fixture {
            extension: "css",
            source: "a { color: red; }\n",
            pattern: "a { color: red; }",
            replacement: "a { color: blue; }",
        },
        Dart => Fixture {
            extension: "dart",
            source: "void main() { var needle = 1; }\n",
            pattern: "needle",
            replacement: "target",
        },
        Elixir => Fixture {
            extension: "ex",
            source: "needle = 1\n",
            pattern: "needle",
            replacement: "target",
        },
        Go => Fixture {
            extension: "go",
            source: "package p\nfunc f() { needle := 1 }\n",
            pattern: "needle",
            replacement: "target",
        },
        Haskell => Fixture {
            extension: "hs",
            source: "needle = 1\n",
            pattern: "needle",
            replacement: "target",
        },
        Hcl => Fixture {
            extension: "hcl",
            source: "name = \"needle\"\n",
            pattern: "name = \"needle\"",
            replacement: "name = \"target\"",
        },
        Html => Fixture {
            extension: "html",
            source: "<p>needle</p>\n",
            pattern: "needle",
            replacement: "target",
        },
        Java => Fixture {
            extension: "java",
            source: "class C { int needle = 1; }\n",
            pattern: "needle",
            replacement: "target",
        },
        JavaScript => Fixture {
            extension: "js",
            source: "const needle = 1;\n",
            pattern: "needle",
            replacement: "target",
        },
        Json => Fixture {
            extension: "json",
            source: "{\"name\": \"needle\"}\n",
            pattern: "\"needle\"",
            replacement: "\"target\"",
        },
        Kotlin => Fixture {
            extension: "kt",
            source: "val needle = 1\n",
            pattern: "needle",
            replacement: "target",
        },
        Lua => Fixture {
            extension: "lua",
            source: "needle()\n",
            pattern: "needle()",
            replacement: "target()",
        },
        Markdown => Fixture {
            extension: "md",
            source: "needle text\n",
            pattern: "needle text",
            replacement: "target text",
        },
        Nix => Fixture {
            extension: "nix",
            source: "needle = 1;\n",
            pattern: "needle",
            replacement: "target",
        },
        Php => Fixture {
            extension: "php",
            source: "<?php needle();\n",
            pattern: "needle",
            replacement: "target",
        },
        Python => Fixture {
            extension: "py",
            source: "needle = 1\n",
            pattern: "needle",
            replacement: "target",
        },
        Ruby => Fixture {
            extension: "rb",
            source: "needle = 1\n",
            pattern: "needle",
            replacement: "target",
        },
        Rust => Fixture {
            extension: "rs",
            source: "fn main() { let needle = 1; }\n",
            pattern: "needle",
            replacement: "target",
        },
        Scala => Fixture {
            extension: "scala",
            source: "val needle = 1\n",
            pattern: "needle",
            replacement: "target",
        },
        Solidity => Fixture {
            extension: "sol",
            source: "contract C { uint needle; }\n",
            pattern: "needle",
            replacement: "target",
        },
        Swift => Fixture {
            extension: "swift",
            source: "let needle = 1\n",
            pattern: "needle",
            replacement: "target",
        },
        Tsx => Fixture {
            extension: "tsx",
            source: "const view = <div>needle</div>;\n",
            pattern: "const view = <div>needle</div>;",
            replacement: "const view = <div>target</div>;",
        },
        TypeScript => Fixture {
            extension: "ts",
            source: "const needle = 1;\n",
            pattern: "needle",
            replacement: "target",
        },
        Yaml => Fixture {
            extension: "yaml",
            source: "name: needle\n",
            pattern: "needle",
            replacement: "target",
        },
    })
}

fn tempdir() -> TempDir {
    tempfile::Builder::new()
        .prefix("varde-ast-edit-language-")
        .tempdir()
        .expect("temporary directory creates")
}

#[test]
fn every_linked_structural_grammar_has_a_working_rewrite_fixture() {
    let mut failures = Vec::new();
    for &language in SupportLang::all_langs() {
        let fixture = fixture(language)
            .unwrap_or_else(|| panic!("linked grammar {language:?} has no preview fixture"));
        let repo = tempdir();
        let store = tempdir();
        let path = format!("fixture.{}", fixture.extension);
        let original = fixture.source;
        fs::write(repo.path().join(&path), original).unwrap();

        let result = match preview(&PreviewOptions {
            repository_root: repo.path().to_path_buf(),
            invoking_cwd: repo.path().to_path_buf(),
            paths: vec![PathBuf::from(&path)],
            store_dir: store.path().to_path_buf(),
            rules: vec![RewriteRule {
                id: format!("{}-literal-rewrite", language),
                language: language.to_string(),
                pattern: fixture.pattern.into(),
                replacement: fixture.replacement.into(),
                inside: None,
                has: None,
                precedes: None,
                follows: None,
            }],
        }) {
            Ok(result) => result,
            Err(error) => {
                failures.push(format!("{language:?} preview failed: {error:#}"));
                continue;
            }
        };
        let Some(proposal) = result.proposal.as_ref().filter(|_| result.applicable) else {
            failures.push(format!(
                "{language:?} preview was not applicable: {:?}",
                result.diagnostics
            ));
            continue;
        };
        if proposal.files.len() != 1
            || proposal.files[0].original_content != original
            || proposal.files[0].replacement_content == original
            || fs::read_to_string(repo.path().join(&path)).unwrap() != original
        {
            failures.push(format!(
                "{language:?} proposal or source preservation was incorrect"
            ));
            continue;
        }

        let expected = original.replacen(fixture.pattern, fixture.replacement, 1);
        let apply_result = match apply(
            proposal,
            &ApplyOptions {
                repository_root: repo.path().to_path_buf(),
            },
        ) {
            Ok(result) => result,
            Err(error) => {
                failures.push(format!("{language:?} apply failed: {error:#}"));
                continue;
            }
        };
        if apply_result.files.len() != 1
            || !apply_result.files[0].is_applied()
            || fs::read(repo.path().join(&path)).unwrap() != expected.as_bytes()
        {
            failures.push(format!("{language:?} apply output was incorrect"));
        }
    }
    assert!(
        failures.is_empty(),
        "language fixture failures:\n{}",
        failures.join("\n")
    );
}
