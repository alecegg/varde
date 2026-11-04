# ruff: noqa: UP034 - Explicit grouping preserves split fixture strings in calls.
from __future__ import annotations

from pathlib import Path

import ast_grep_py
import pytest
from varde_code import ApiError
from varde_code.parse import SUPPORTED_LANGUAGES
from varde_code.rules.model import ConstraintSpec, Rule, RuleKind, Severity
from varde_code.rules.pattern import (
    _match_source,
    apply_constraints,
    capture_names,
    run_pattern_rules,
    validate_rewrite_template,
)


def _match(**captures):
    return {"captures": captures}


def _node(text):
    return {"kind": "identifier", "text": text}


def test_constraints_support_single_and_variadic_capture_and_negation():
    matches = [_match(NAME=_node("getValue")), _match(NAME=_node("getDeprecated"))]
    spec = {"NAME": ConstraintSpec(("^get", "!^getDeprecated$"))}
    assert apply_constraints(matches, spec) == [matches[0]]
    args = [_match(ARGS=[_node("left"), _node("right")])]
    assert apply_constraints(args, {"ARGS": ConstraintSpec(("^leftright$",))}) == args


def test_constraints_apply_and_semantics_and_passthrough():
    matches = [_match(NAME=_node("Foo9"), TARGET=_node("baz"))]
    assert apply_constraints(matches, {}) == matches
    assert (
        apply_constraints(
            matches,
            {
                "NAME": ConstraintSpec(("^[A-Z]", "[0-9]$")),
                "TARGET": ConstraintSpec(("^[A-Z]",)),
            },
        )
        == []
    )


def test_constraints_reject_missing_capture_and_invalid_or_empty_regex():
    assert (
        apply_constraints([_match(OTHER=_node("x"))], {"NAME": ConstraintSpec(("x",))})
        == []
    )
    with pytest.raises(ApiError, match="invalid_constraint"):
        apply_constraints([], {"NAME": ConstraintSpec(("[",))})
    with pytest.raises(ApiError, match="must not be empty"):
        apply_constraints([], {"NAME": ConstraintSpec(())})


def test_constraints_translate_rust_inline_flags_and_reject_unsupported_constructs():
    matches = [_match(NAME=_node("prefixAPI")), _match(NAME=_node("PREFIXAPI"))]
    assert apply_constraints(
        matches,
        {
            "NAME": ConstraintSpec(("^prefix(?i)(api|token)$",)),
        },
    ) == [matches[0]]
    for unsupported in (r"foo(?=bar)", r"(foo)\1"):
        with pytest.raises(ApiError, match="invalid_constraint"):
            apply_constraints([], {"NAME": ConstraintSpec((unsupported,))})


def test_capture_names_and_rewrite_validation_follow_template_token_rules():
    assert capture_names("f($$$ARGS, $NAME, $NAME)") == ["ARGS", "NAME"]
    validate_rewrite_template("f($NAME)", "f($NAME)")
    with pytest.raises(ValueError, match="`OTHER`"):
        validate_rewrite_template("f($OTHER)", "f($NAME)")
    assert capture_names("a $ b $$$ tail cost $; end $5 $A_B $A2 $MSG then $MSG") == [
        "5",
        "A_B",
        "A2",
        "MSG",
    ]
    validate_rewrite_template("f($$$ARGS)", "f($ARGS)")
    validate_rewrite_template("f($ARGS)", "f($$$ARGS)")


def test_pattern_pipeline_collects_ast_grep_captures(tmp_path):
    source = tmp_path / "calls.rs"
    source.write_text("fn main() { alpha(1); alpha(2, 3); beta(4); }", encoding="utf-8")
    import sqlite3

    db = sqlite3.connect(":memory:")
    db.execute(
        (
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, "
            "is_test_path INTEGER, is_tooling_path INTEGER)"
        )
    )
    db.execute(
        (
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, name TEXT, is_async INTEGER)"
        )
    )
    rule = Rule(
        id="alpha",
        kind=RuleKind.PATTERN,
        severity=Severity.WARNING,
        message="found",
        pattern="alpha($$$ARGS)",
        languages=["rust"],
    )
    findings, diagnostics = run_pattern_rules([rule], tmp_path, db)
    assert diagnostics == []
    assert len(findings) == 2
    assert findings[0].evidence["ARGS"][0]["text"] == "1"
    assert findings[1].evidence["ARGS"][1]["text"] == "3"


def test_pattern_evidence_uses_tree_sitter_node_kinds():
    matches = _match_source("subprocess.run(value)", "subprocess.run($ARG)", "python")

    assert matches[0]["kind"] == "call"
    assert matches[0]["captures"]["ARG"]["kind"] == "identifier"


def test_pattern_evidence_uses_rust_tree_sitter_node_text_and_kind():
    call = _match_source("consume(work());", "consume($ARG)", "javascript")[0]
    php = _match_source(
        "<?php function f() { try { work(); } catch (Exception $error) {} }",
        "catch ($TYPE $ERR) { }",
        "php",
    )[0]

    assert call["captures"]["ARG"]["kind"] == "call_expression"
    assert call["captures"]["ARG"]["text"] == "work()"
    assert php["captures"]["ERR"]["kind"] == "name"
    assert php["captures"]["ERR"]["text"] == "error"


def test_multinode_empty_catch_patterns_match_tree_sitter_nodes():
    csharp = _match_source(
        "class X { void F() { try { Work(); } catch (Exception error) { } } }",
        "catch ($TYPE $ERR) { }",
        "csharp",
    )[0]
    dart = _match_source(
        "void f() { try { work(); } catch (error) { } }",
        "try { $$$A; } catch ($ERR) { }",
        "dart",
    )[0]

    assert csharp["kind"] == "catch_clause"
    assert csharp["captures"]["TYPE"]["text"] == "Exception"
    assert csharp["captures"]["ERR"]["text"] == "error"
    assert dart["captures"]["A"][0]["kind"] == "call_expression"
    assert dart["captures"]["A"][0]["text"] == "work()"


def test_bash_boolean_list_and_go_result_assignment_match_rust_patterns():
    bash = _match_source("false || true", "$CMD $$$ARGS || $NOOP", "bash")
    go = _match_source("_, _ = doWork()", "_ = $CALL($$$ARGS)", "go")
    rust = _match_source(
        'fn f() { let token: &str = "secret-token"; }',
        "$$$MOD let $KEY: $TYPE = $VAL;",
        "rust",
    )

    assert len(bash) == 1
    assert bash[0]["captures"]["CMD"]["text"] == "false"
    assert bash[0]["captures"]["NOOP"]["text"] == "true"
    assert go == []
    assert len(rust) == 1
    assert rust[0]["captures"]["TYPE"]["kind"] == "reference_type"


def test_java_field_pattern_excludes_local_variable_declarations():
    pattern = "$$$MOD $TYPE $KEY = $VAL"
    source = (
        'class X { String token = "field-secret"; '
        'void f() { String password = "local-secret"; } }'
    )

    matches = _match_source(source, pattern, "java")

    assert [match["kind"] for match in matches] == ["field_declaration"]


def test_csharp_property_pattern_handles_multinode_matcher():
    pattern = "$$$MOD $TYPE $KEY { get; } = $VAL"

    assert _match_source("class X { void F() { } }", pattern, "csharp") == []
    matches = _match_source(
        'class X { string Token { get; } = "fixture-secret"; }', pattern, "csharp"
    )

    assert len(matches) == 1
    assert matches[0]["kind"] == "property_declaration"
    assert matches[0]["captures"]["KEY"]["text"] == "Token"


def test_pattern_pipeline_honors_gitignore_and_sorts_matches(tmp_path):
    import sqlite3
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "hidden.rs").write_text("fn hit() {}", encoding="utf-8")
    (tmp_path / "z.rs").write_text("fn hit() {}", encoding="utf-8")
    (tmp_path / ".hidden.rs").write_text("fn hit() {}", encoding="utf-8")
    (tmp_path / "a.rs").write_text("fn hit() {}", encoding="utf-8")

    db = sqlite3.connect(":memory:")
    db.execute(
        (
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, "
            "is_test_path INTEGER, is_tooling_path INTEGER)"
        )
    )
    db.execute(
        (
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, name TEXT, is_async INTEGER)"
        )
    )
    rule = Rule(
        id="hit",
        kind=RuleKind.PATTERN,
        severity=Severity.WARNING,
        message="found",
        pattern="fn hit() {}",
        languages=["rust"],
    )

    findings, diagnostics = run_pattern_rules([rule], tmp_path, db)

    assert diagnostics == []
    assert [Path(item.location.file).name for item in findings] == [
        ".hidden.rs",
        "a.rs",
        "z.rs",
    ]


def test_pattern_pipeline_skips_unreadable_utf8_file(tmp_path):
    import sqlite3

    (tmp_path / "bad.rs").write_bytes(b"fn broken() { \xff }")
    (tmp_path / "good.rs").write_text("fn hit() {}", encoding="utf-8")
    db = sqlite3.connect(":memory:")
    db.execute(
        (
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, "
            "is_test_path INTEGER, is_tooling_path INTEGER)"
        )
    )
    db.execute(
        (
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, name TEXT, is_async INTEGER)"
        )
    )
    rule = Rule(
        id="hit",
        kind=RuleKind.PATTERN,
        severity=Severity.WARNING,
        message="found",
        pattern="fn hit() {}",
        languages=["rust"],
    )

    findings, diagnostics = run_pattern_rules([rule], tmp_path, db)

    assert [Path(item.location.file).name for item in findings] == ["good.rs"]
    assert diagnostics == []


def _run_fixture_rules(tmp_path, files, rules):
    import sqlite3
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for relative, source in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    db = sqlite3.connect(":memory:")
    db.execute(
        (
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, "
            "is_test_path INTEGER, is_tooling_path INTEGER)"
        )
    )
    db.execute(
        (
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, name TEXT, is_async INTEGER)"
        )
    )
    findings, diagnostics = run_pattern_rules(rules, tmp_path, db)
    assert diagnostics == []
    db.close()
    return [finding.rule_id for finding in findings]


def _builtin_rules(pack, rule_ids):
    from varde_code.rules.loader import parse_pack_file

    builtin_dir = Path(__file__).parents[2] / "src/varde_code/rules/builtin"
    rules, diagnostics = parse_pack_file(builtin_dir / pack)
    assert diagnostics == []
    return [rule for rule in rules if rule.id in rule_ids]


def test_builtin_empty_handler_and_eval_rules_fire_end_to_end(tmp_path):
    empty = _builtin_rules("empty_catch_block.toml", {"empty-catch-block"})
    eval_rule = _builtin_rules("eval_usage.toml", {"eval-usage"})
    ids = _run_fixture_rules(
        tmp_path,
        {
            "sample.ts": (
                "function sample() {\n  try { risky(); } catch (err) { }\n  "
                "try { risky(); } catch (err) { handle(err); }\n  eval(userInput);\n  "
                'obj.eval("not-a-match");\n}\n'
            ),
        },
        empty + eval_rule,
    )
    assert ids.count("empty-catch-block") == 1
    assert ids.count("eval-usage") == 1


def test_builtin_debug_rules_fire_end_to_end(tmp_path):
    rules = _builtin_rules(
        "debug_statement_strict.toml",
        {
            "debug-macro-strict",
            "debug-statement-strict",
            "console-log-strict",
        },
    )
    ids = _run_fixture_rules(
        tmp_path,
        {
            "sample.rs": (
                "fn sample() { let x = 42; dbg!(x); dbg!(x, x); "
                'println!("x = {}", x); }\n'
            ),
            "sample.js": (
                "function a() { const x = 1; console.log(x); "
                "console.warn(x); debugger; }\n"
            ),
        },
        rules,
    )
    assert ids.count("debug-macro-strict") == 2
    assert ids.count("debug-statement-strict") == 1
    assert ids.count("console-log-strict") == 1


def test_unsupported_language_is_reported_and_sql_rules_are_ignored(tmp_path):
    import sqlite3

    db = sqlite3.connect(":memory:")
    db.execute(
        (
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, "
            "is_test_path INTEGER, is_tooling_path INTEGER)"
        )
    )
    db.execute(
        (
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, name TEXT, is_async INTEGER)"
        )
    )
    invalid = Rule(
        id="bad",
        kind=RuleKind.PATTERN,
        severity=Severity.WARNING,
        message="bad",
        pattern="foo($A)",
        languages=["cobol"],
    )
    sql = Rule(id="sql", kind=RuleKind.SQL, severity=Severity.WARNING, message="sql")
    findings, diagnostics = run_pattern_rules([invalid, sql], tmp_path, db)
    assert findings == []
    assert len(diagnostics) == 1 and "cobol" in diagnostics[0].reason


def test_invalid_pattern_is_reported_without_stopping_other_rules(tmp_path):
    import sqlite3

    db = sqlite3.connect(":memory:")
    db.execute(
        (
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, "
            "is_test_path INTEGER, is_tooling_path INTEGER)"
        )
    )
    db.execute(
        (
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, name TEXT, is_async INTEGER)"
        )
    )
    (tmp_path / "sample.rs").write_text("fn main() { alpha(1); }", encoding="utf-8")
    broken = Rule(
        id="broken",
        kind=RuleKind.PATTERN,
        severity=Severity.WARNING,
        message="broken",
        pattern="(((",
        languages=["rust"],
    )
    valid = Rule(
        id="valid",
        kind=RuleKind.PATTERN,
        severity=Severity.WARNING,
        message="valid",
        pattern="alpha($A)",
        languages=["rust"],
    )
    findings, diagnostics = run_pattern_rules([broken, valid], tmp_path, db)
    assert [finding.rule_id for finding in findings] == ["valid"]
    assert len(diagnostics) == 1 and diagnostics[0].rule_id == "broken"


def test_missing_pattern_and_unusable_database_are_reported(tmp_path):
    import sqlite3

    from varde_code import ApiError

    rule = Rule(
        id="missing",
        kind=RuleKind.PATTERN,
        severity=Severity.WARNING,
        message="missing",
    )
    db = sqlite3.connect(":memory:")
    db.execute(
        (
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, "
            "is_test_path INTEGER, is_tooling_path INTEGER)"
        )
    )
    db.execute(
        (
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, name TEXT, is_async INTEGER)"
        )
    )
    findings, diagnostics = run_pattern_rules([rule], tmp_path, db)
    assert findings == [] and len(diagnostics) == 1
    broken_db = sqlite3.connect(":memory:")
    with pytest.raises(ApiError) as error:
        run_pattern_rules([rule], tmp_path, broken_db)
    assert error.value.code == "db_error"


def test_ast_grep_version_matches_documented_pin():
    import re
    from importlib.metadata import version
    from pathlib import Path

    docs = Path(__file__).parents[3] / "code/tests/rules/fixtures/versions.md"
    match = re.search(
        r"\| ast-grep-py \| ([^ |]+) \|", docs.read_text(encoding="utf-8")
    )
    assert match is not None
    assert version("ast-grep-py") == match.group(1)
    assert ast_grep_py is not None


def test_supported_rule_languages_have_ast_grep_grammars():
    from varde_code import pattern_match

    assert len(SUPPORTED_LANGUAGES) == 21
    assert all(
        pattern_match.language_name(language) == language
        for language in SUPPORTED_LANGUAGES
    )
    assert pattern_match.language_name("c++") == "cpp"
    assert pattern_match.language_name("php") == "php"


def test_builtin_constraint_regexes_compile_and_patterns_parse(tmp_path):
    import sqlite3

    from varde_code.rules.loader import parse_pack_file

    builtin_dir = Path(__file__).parents[2] / "src/varde_code/rules/builtin"
    rules = []
    for pack in sorted(builtin_dir.glob("*.toml")):
        parsed, diagnostics = parse_pack_file(pack)
        assert diagnostics == []
        rules.extend(parsed)

    for rule in rules:
        apply_constraints([], rule.constraints or {})

    # The pipeline validates every rule even when there are no source files;
    # this avoids invoking ast-grep on multi-node patterns unrelated to parse
    # diagnostics while exercising the production diagnostic path.
    db = sqlite3.connect(":memory:")
    db.execute(
        (
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, "
            "is_test_path INTEGER, is_tooling_path INTEGER)"
        )
    )
    db.execute(
        (
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, name TEXT, is_async INTEGER)"
        )
    )
    _, diagnostics = run_pattern_rules(rules, tmp_path, db)
    assert [
        diagnostic for diagnostic in diagnostics if "pattern" in diagnostic.reason
    ] == []
    db.close()


def test_pattern_matches_authored_positive_and_negative_snippets():
    positive = _match_source(
        "def load():\n    fetch(record)\n", "fetch($VALUE)", "python"
    )
    negative = _match_source(
        "def load():\n    save(record)\n", "fetch($VALUE)", "python"
    )

    assert len(positive) == 1
    assert positive[0]["captures"]["VALUE"]["text"] == "record"
    assert negative == []


def test_pattern_pipeline_perf_smoke(tmp_path):
    import sqlite3

    (tmp_path / "sample.rs").write_text(
        "fn main() { " + "alpha(1); " * 100 + "}", encoding="utf-8"
    )
    db = sqlite3.connect(":memory:")
    db.execute(
        (
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, "
            "is_test_path INTEGER, is_tooling_path INTEGER)"
        )
    )
    db.execute(
        (
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, name TEXT, is_async INTEGER)"
        )
    )
    rule = Rule(
        id="perf",
        kind=RuleKind.PATTERN,
        severity=Severity.WARNING,
        message="found",
        pattern="alpha($A)",
        languages=["rust"],
    )
    findings, diagnostics = run_pattern_rules([rule], tmp_path, db)
    assert diagnostics == []
    assert len(findings) == 100
