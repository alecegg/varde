from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from groundtruth.cpp.export import (
    MEMBER_CALL,
    RepoContext,
    _enclosing_function,
    _hierarchy_record,
    _higher_order_names,
    _higher_order_records,
    _position,
    _site_call_name,
    export_sites,
    export_unresolved_member_candidates,
    iter_calls,
)
from groundtruth.cpp.review import stub
from groundtruth.cpp.sample import (
    CLASSES,
    _is_test_path,
    manifest_file,
    read_jsonl,
    stratified_sample,
    stubs_for_unknown,
    unknown_count,
    write_jsonl,
)
from groundtruth.cpp.sample import (
    main as sample_main,
)


def _record(
    repo: str, line: int, call_class: str, file: str | None = None
) -> dict[str, object]:
    return {
        "repo": repo,
        "language": "cpp",
        "file": file or f"src/module_{repo.replace('-', '_')}.cpp",
        "line": line,
        "call_name": f"target_{call_class}",
        "call_class": call_class,
        "ground_truth": f"src/module.cpp:{line}:target_{call_class}",
        "measured_edge": None,
        "measured_status": "unresolved",
        "truth_source": "clangd-test-double",
        "function_id": "src/module.cpp:1:caller",
        "module": "src",
        "ground_truth_module": "src",
        "measured_module": None,
    }


def _corpus(
    repos: tuple[str, ...],
    *,
    per_class: int = 6,
    file: str | None = None,
) -> list[dict[str, object]]:
    return [
        _record(repo, index + repeat * 100, call_class, file)
        for repo in repos
        for index, call_class in enumerate(CLASSES, start=1)
        for repeat in range(per_class)
    ]


def _roles(dev: tuple[str, ...], test: tuple[str, ...]) -> dict[str, str]:
    return {**dict.fromkeys(dev, "dev"), **dict.fromkeys(test, "test-only")}


def test_iter_calls_skips_control_flow_and_comments() -> None:
    source = """void run() {
  call_target();
  if (ready) call_again();
  // ignored_call();
}
"""

    assert [match.group("name") for match in iter_calls(source)] == [
        "call_target",
        "call_again",
    ]


def test_iter_calls_excludes_assertion_macros_but_keeps_argument_calls() -> None:
    source = "void test() { EXPECT_EQ(left(), right()); assert(ready()); }\n"

    assert [match.group("name") for match in iter_calls(source)] == [
        "left",
        "right",
        "ready",
    ]


def test_iter_calls_skips_keywords_and_macro_calls() -> None:
    source = """void run() {
  for (int i = 0; i < n; ++i) {}
  while (ready()) {}
  switch (state()) {}
  static_assert(sizeof(int) == 4);
  ABSL_INTERNAL_LOG(FATAL, "stop");
  auto value = std::min(left(), right());
}
"""

    assert [match.group("name") for match in iter_calls(source)] == [
        "ready",
        "state",
        "std::min",
        "left",
        "right",
    ]


def test_member_calls_do_not_span_lines() -> None:
    source = (
        "void run() {\n"
        "  // move infoz instructions out of line.\n"
        "  if (common.has_infoz()) {}\n"
        "}\n"
    )

    assert [match.group("name") for match in MEMBER_CALL.finditer(source)] == [
        "has_infoz"
    ]


def test_site_call_name_uses_callable_expression() -> None:
    assert (
        _site_call_name("void run() { callback(1); }", 13, "operator()") == "callback"
    )
    assert _site_call_name("  if (ready()) {}", 2, "ready") == "ready"


def test_source_only_candidates_are_unknown_and_reviewer_ready(tmp_path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    source = source_root / "app.cpp"
    source.write_text("void run() { service->send(); if (ready()) {} }\n")

    records = export_unresolved_member_candidates(tmp_path, "fixture/app")

    assert [record["call_name"] for record in records] == ["send"]
    assert records[0]["ground_truth"] == "unknown"
    assert records[0]["truth_source"] == "source-only-partial"


def test_higher_order_syntax_finds_pointer_std_function_lambda_and_callback(
    tmp_path,
) -> None:
    source = """template <class F> void invoke(F callback) {
  void (*pointer)(int);
  std::function<void(int)> handler;
  auto lambda = [](int) {};
  (*pointer)(1);
  handler(1);
  lambda(1);
  callback(1);
}
"""
    file = tmp_path / "callbacks.cpp"
    file.write_text(source)
    symbol = {
        "name": "invoke",
        "range": {"start": {"line": 0}, "end": {"line": 8}},
        "selectionRange": {"start": {"line": 0}},
    }

    names = _higher_order_names(source)
    records = _higher_order_records(
        RepoContext(tmp_path.resolve(), "fixture/callbacks"),
        file,
        source,
        [symbol],
        [],
    )

    assert {"pointer", "handler", "lambda", "callback"} <= names
    assert {row["call_name"] for row in records} == {
        "pointer",
        "handler",
        "lambda",
        "callback",
    }
    assert all(row["call_class"] == "higher_order" for row in records)


def test_higher_order_syntax_finds_alias_typed_callables(tmp_path) -> None:
    source = """using Callback = void (*)(int);
using Handler = std::function<void()>;
void run() {
  Callback callback;
  Handler handler;
  callback(1);
  handler();
}
"""
    file = tmp_path / "aliases.cpp"
    file.write_text(source)
    symbol = {
        "name": "run",
        "range": {"start": {"line": 2}, "end": {"line": 7}},
        "selectionRange": {"start": {"line": 2}},
    }

    names = _higher_order_names(source)
    records = _higher_order_records(
        RepoContext(tmp_path.resolve(), "fixture/aliases"),
        file,
        source,
        [symbol],
        [],
    )

    assert {"callback", "handler"} <= names
    assert {row["call_name"] for row in records} == {"callback", "handler"}
    assert all(row["call_class"] == "higher_order" for row in records)


def test_higher_order_syntax_skips_function_pointer_parameters(tmp_path) -> None:
    source = """void run(void (*handler)(int)) {
  handler(1);
}
"""
    file = tmp_path / "parameter.cpp"
    file.write_text(source)
    symbol = {
        "name": "run",
        "range": {"start": {"line": 0}, "end": {"line": 2}},
        "selectionRange": {"start": {"line": 0}},
    }

    records = _higher_order_records(
        RepoContext(tmp_path.resolve(), "fixture/parameters"),
        file,
        source,
        [symbol],
        [],
    )

    assert [row["call_name"] for row in records] == ["handler"]
    assert records[0]["line"] == 2


def test_higher_order_syntax_skips_qualified_macro_and_type_calls(tmp_path) -> None:
    source = """template <class T> T min(T a, T b);
typedef SummarizingConverter Converter;
void run(T min) {
  auto value = std::min(1, 2);
  ABSL_INTERNAL_LOG(FATAL, "stop");
  Converter(3);
}
"""
    file = tmp_path / "filtered.cpp"
    file.write_text(source)
    symbol = {
        "name": "run",
        "range": {"start": {"line": 2}, "end": {"line": 6}},
        "selectionRange": {"start": {"line": 2}},
    }

    records = _higher_order_records(
        RepoContext(tmp_path.resolve(), "fixture/filtered"),
        file,
        source,
        [symbol],
        [],
    )

    assert records == []


def test_higher_order_runtime_lookup_calls_are_dynamic(tmp_path) -> None:
    source = """void run(void* handle) {
  auto entry = reinterpret_cast<void (*)(int)>(dlsym(handle, "entry"));
  (*entry)(1);
}
"""
    file = tmp_path / "lookup.cpp"
    file.write_text(source)
    symbol = {
        "name": "run",
        "range": {"start": {"line": 0}, "end": {"line": 3}},
        "selectionRange": {"start": {"line": 0}},
    }

    records = _higher_order_records(
        RepoContext(tmp_path.resolve(), "fixture/lookup"),
        file,
        source,
        [symbol],
        [],
    )

    assert [row["call_class"] for row in records] == ["dynamic"]
    assert records[0]["call_name"] == "entry"


def test_position_counts_utf16_code_units() -> None:
    source = "void f() { 😀 target(); }"
    assert _position(source, source.index("target")) == {"line": 0, "character": 14}


def test_enclosing_function_chooses_smallest_range() -> None:
    symbols = [
        {"name": "outer", "range": {"start": {"line": 1}, "end": {"line": 12}}},
        {"name": "inner", "range": {"start": {"line": 4}, "end": {"line": 7}}},
    ]

    assert _enclosing_function(symbols, 5) == symbols[1]


def test_function_object_target_is_higher_order(tmp_path) -> None:
    root = tmp_path.resolve()
    file = root / "caller.cpp"
    file.write_text("void caller() { callback(); }\n")
    caller = {
        "name": "caller",
        "selectionRange": {"start": {"line": 0}},
    }
    target = {
        "name": "operator()",
        "kind": 6,
        "uri": file.as_uri(),
        "selectionRange": {"start": {"line": 4}},
    }
    call_range = {"start": {"line": 0, "character": 16}}

    record = _hierarchy_record(
        RepoContext(root, "fixture/repo"),
        file,
        file.read_text(),
        caller,
        target,
        call_range,
    )

    assert record is not None
    assert record["call_class"] == "higher_order"


def test_virtual_declaration_target_is_dynamic(tmp_path) -> None:
    root = tmp_path.resolve()
    header = root / "include" / "shape.hpp"
    header.parent.mkdir()
    header.write_text("class Shape {\n public:\n  virtual void draw();\n};\n")
    file = root / "src" / "render.cpp"
    file.parent.mkdir()
    file.write_text("void render(Shape* shape) {\n  shape->draw();\n}\n")
    caller = {"name": "render", "selectionRange": {"start": {"line": 0}}}
    target = {
        "name": "draw",
        "kind": 6,
        "uri": header.as_uri(),
        "selectionRange": {"start": {"line": 2, "character": 15}},
    }

    record = _hierarchy_record(
        RepoContext(root, "fixture/repo"),
        file,
        file.read_text(),
        caller,
        target,
        {"start": {"line": 1, "character": 2}},
    )

    assert record is not None
    assert record["call_class"] == "dynamic"
    assert record["ground_truth"] == "include/shape.hpp:3:draw"


def test_keyword_callee_uses_the_reported_target_name(tmp_path) -> None:
    root = tmp_path.resolve()
    file = root / "caller.cpp"
    file.write_text("void caller() { if (ready()) {} }\n")
    caller = {"name": "caller", "selectionRange": {"start": {"line": 0}}}
    target = {
        "name": "ready",
        "kind": 12,
        "uri": file.as_uri(),
        "selectionRange": {"start": {"line": 4}},
    }

    record = _hierarchy_record(
        RepoContext(root, "fixture/repo"),
        file,
        file.read_text(),
        caller,
        target,
        {"start": {"line": 0, "character": 16}},
    )

    assert record is not None
    assert record["call_name"] == "ready"


def test_clangd_location_becomes_an_internal_record(tmp_path) -> None:
    from groundtruth.cpp.export import _record as export_record

    source = "void caller() { target(); }\n"
    caller = {
        "name": "caller",
        "range": {"start": {"line": 0}, "end": {"line": 0}},
    }
    root = tmp_path.resolve()
    file = root / "caller.cpp"
    file.write_text(source)
    target = root / "target.cpp"
    target.write_text("void target() {}\n")
    location = {
        "uri": target.as_uri(),
        "range": {"start": {"line": 0, "character": 5}},
    }
    match = next(iter(iter_calls(source)))
    record = export_record(
        RepoContext(root, "fixture/repo"), file, source, match, caller, [location]
    )

    assert record is not None
    assert record["ground_truth"] == "target.cpp:1:target"
    assert record["call_name"] == "target"
    assert record["call_class"] == "imported"


def _fake_clangd(root, source, target, calls):
    def handle(method, _params):
        calls.append(method)
        if method == "textDocument/documentSymbol":
            return [
                {
                    "name": "caller",
                    "kind": 12,
                    "range": {"start": {"line": 0}, "end": {"line": 0}},
                    "selectionRange": {
                        "start": {"line": 0, "character": 5},
                        "end": {"line": 0, "character": 11},
                    },
                }
            ]
        if method == "textDocument/prepareCallHierarchy":
            return [
                {
                    "name": "caller",
                    "kind": 12,
                    "uri": source.as_uri(),
                    "range": {"start": {"line": 0}, "end": {"line": 0}},
                    "selectionRange": {
                        "start": {"line": 0, "character": 5},
                        "end": {"line": 0, "character": 11},
                    },
                }
            ]
        if method == "textDocument/definition":
            return []
        return [
            {
                "to": {
                    "name": "target",
                    "kind": 12,
                    "uri": target.as_uri(),
                    "range": {"start": {"line": 0, "character": 5}},
                    "selectionRange": {
                        "start": {"line": 0, "character": 5},
                        "end": {"line": 0, "character": 11},
                    },
                },
                "fromRanges": [
                    {
                        "start": {
                            "line": 0,
                            "character": source.read_text().index("target"),
                        },
                        "end": {
                            "line": 0,
                            "character": source.read_text().index("target") + 6,
                        },
                    }
                ],
            }
        ]

    return handle


def test_export_sites_uses_fake_clangd_responses(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "src.cpp"
    source.write_text("void caller() { target(); }\n")
    compile_db = tmp_path / "build" / "compile_commands.json"
    compile_db.parent.mkdir()
    compile_db.write_text(
        json.dumps(
            [{"directory": str(root), "file": str(source), "command": "clang++ -c"}]
        )
    )
    target = root / "target.cpp"
    target.write_text("void target() {}\n")
    calls: list[str] = []

    records = export_sites(
        root,
        compile_db,
        "fixture/repo",
        invoke=_fake_clangd(root, source, target, calls),
    )

    assert len(records) == 1
    assert records[0]["ground_truth"] == "target.cpp:1:target"
    assert records[0]["call_name"] == "target"
    assert "callHierarchy/outgoingCalls" in calls


def test_export_sites_keeps_indirect_calls_unresolved(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "src.cpp"
    source.write_text(
        "void caller() {\n  void (*callback)(int);\n  (*callback)(1);\n}\n"
    )
    compile_db = tmp_path / "build" / "compile_commands.json"
    compile_db.parent.mkdir()
    compile_db.write_text(
        json.dumps(
            [{"directory": str(root), "file": str(source), "command": "clang++ -c"}]
        )
    )
    calls: list[str] = []

    def indirect_clangd(method, _params):
        calls.append(method)
        if method == "textDocument/documentSymbol":
            return [
                {
                    "name": "caller",
                    "kind": 12,
                    "range": {"start": {"line": 0}, "end": {"line": 3}},
                    "selectionRange": {
                        "start": {"line": 0, "character": 5},
                        "end": {"line": 0, "character": 11},
                    },
                }
            ]
        if method == "textDocument/prepareCallHierarchy":
            return [
                {
                    "name": "caller",
                    "kind": 12,
                    "uri": source.as_uri(),
                    "range": {"start": {"line": 0}, "end": {"line": 3}},
                    "selectionRange": {
                        "start": {"line": 0, "character": 5},
                        "end": {"line": 0, "character": 11},
                    },
                }
            ]
        return []

    records = export_sites(root, compile_db, "fixture/repo", invoke=indirect_clangd)

    assert len(records) == 1
    assert records[0]["call_class"] == "higher_order"
    assert records[0]["call_name"] == "callback"
    assert records[0]["ground_truth"] == "unknown"
    assert records[0]["truth_source"] == "two_human_stub"


def test_export_sites_skips_vendored_source_paths(tmp_path) -> None:
    root = tmp_path / "repo"
    source = root / "src" / "app.cpp"
    vendored = root / "third_party" / "dep" / "dep.cpp"
    for file in (source, vendored):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("void caller() { target(); }\n")
    compile_db = tmp_path / "build" / "compile_commands.json"
    compile_db.parent.mkdir()
    compile_db.write_text(
        json.dumps(
            [
                {
                    "directory": str(root),
                    "file": str(file),
                    "command": "clang++ -c file.cpp",
                }
                for file in (source, vendored)
            ]
        )
    )
    opened: list[str] = []

    def fake_clangd(method, params):
        if method == "textDocument/documentSymbol":
            opened.append(str(params["textDocument"]["uri"]))
        return []

    export_sites(root, compile_db, "fixture/repo", invoke=fake_clangd)

    assert opened == [source.as_uri()]


def test_match_rule_records_reported_declaration_location(tmp_path) -> None:
    root = tmp_path.resolve()
    header = root / "include" / "target.hpp"
    header.parent.mkdir()
    header.write_text("int target();\n")
    file = root / "src" / "caller.cpp"
    file.parent.mkdir()
    file.write_text("void caller() {\n  target();\n}\n")
    caller = {"name": "caller", "selectionRange": {"start": {"line": 0}}}
    target = {
        "name": "target",
        "kind": 12,
        "uri": header.as_uri(),
        "selectionRange": {"start": {"line": 6, "character": 4}},
    }

    record = _hierarchy_record(
        RepoContext(root, "fixture/repo"),
        file,
        file.read_text(),
        caller,
        target,
        {"start": {"line": 1, "character": 2}},
    )

    assert record is not None
    assert record["ground_truth"] == "include/target.hpp:7:target"
    assert record["call_name"] == "target"
    assert record["call_class"] == "imported"
    assert record["ground_truth_module"] == "include"


def test_match_rule_ignores_unreachable_targets() -> None:
    root = Path("/nonexistent/repo")
    file = root / "src" / "caller.cpp"
    caller = {"name": "caller", "selectionRange": {"start": {"line": 0}}}

    assert (
        _hierarchy_record(
            RepoContext(root, "fixture/repo"),
            file,
            "void caller() { target(); }\n",
            caller,
            {"name": "target", "kind": 12},
            {"start": {"line": 0, "character": 16}},
        )
        is None
    )


def test_match_rule_excludes_test_macros_but_keeps_project_calls() -> None:
    source = """void run() {
  EXPECT_EQ(left(), right());
  ASSERT_TRUE(ready());
  TEST_F(Fixture, case_name);
  Message(1);
  Check(2);
}
"""

    assert [match.group("name") for match in iter_calls(source)] == [
        "left",
        "right",
        "ready",
        "Message",
        "Check",
    ]


def test_stratified_sample_uses_declared_repo_roles() -> None:
    records = _corpus(("dev-a", "dev-b", "dev-c"), per_class=60) + _corpus(
        ("test-a", "test-b", "test-c"), per_class=60
    )
    roles = _roles(("dev-a", "dev-b", "dev-c"), ("test-a", "test-b", "test-c"))

    result = stratified_sample(records, roles, seed=23)

    assert len(result["dev"]) == 300
    assert len(result["test"]) == 300
    assert {
        call_class: sum(row["call_class"] == call_class for row in result["dev"])
        for call_class in CLASSES
    } == dict.fromkeys(CLASSES, 50)
    assert {row["repo"] for row in result["dev"]} <= {"dev-a", "dev-b", "dev-c"}
    assert {row["repo"] for row in result["test"]} <= {"test-a", "test-b", "test-c"}
    repeated = stratified_sample([*records, dict(records[0])], roles, seed=23)
    assert result == repeated
    keys = [
        (row["repo"], row["file"], row["line"], row["call_name"])
        for row in repeated["dev"]
    ]
    assert len(keys) == len(set(keys))


def test_stratified_sample_caps_a_single_repo_share() -> None:
    records = _corpus(("dev-a", "dev-b", "dev-c"), per_class=10)
    records += _corpus(("test-a", "test-b", "test-c"), per_class=10)
    roles = _roles(("dev-a", "dev-b", "dev-c"), ("test-a", "test-b", "test-c"))

    result = stratified_sample(records, roles, size=30)

    counts: dict[str, int] = {}
    for row in result["dev"]:
        counts[str(row["repo"])] = counts.get(str(row["repo"]), 0) + 1
    assert max(counts.values()) <= 12
    assert len(counts) >= 3


def test_stratified_sample_caps_a_repo_within_a_class() -> None:
    records = _corpus(("dev-a", "dev-b", "dev-c"), per_class=10)
    records += _corpus(("test-a", "test-b", "test-c"), per_class=10)
    roles = _roles(("dev-a", "dev-b", "dev-c"), ("test-a", "test-b", "test-c"))

    result = stratified_sample(records, roles, size=12)

    pairs: dict[tuple[str, str], int] = {}
    for row in result["dev"]:
        key = (str(row["repo"]), str(row["call_class"]))
        pairs[key] = pairs.get(key, 0) + 1
    assert max(pairs.values()) <= 1
    assert len({repo for repo, _ in pairs}) >= 3


def test_stratified_sample_requires_enough_sites() -> None:
    with pytest.raises(ValueError, match="same_file shortfall"):
        stratified_sample([_record("dev-a", 1, "same_file")], {"dev-a": "dev"})


def test_stratified_sample_reports_class_shortfall() -> None:
    rows = [
        _record("dev-a", index, call_class)
        for index, call_class in enumerate(CLASSES[:-1], start=1)
    ]
    rows.extend(
        _record("test-a", index, call_class)
        for index, call_class in enumerate(CLASSES, start=10)
    )

    with pytest.raises(ValueError, match="dev dynamic shortfall"):
        stratified_sample(rows, {"dev-a": "dev", "test-a": "test-only"}, size=6)


def test_stratified_sample_caps_test_path_sites() -> None:
    rows = []
    for repo in ("dev-a", "dev-b", "dev-c"):
        for index, call_class in enumerate(CLASSES):
            file = "tests/spec.cpp" if index < 4 else "src/library.cpp"
            rows.extend(
                _record(repo, line + index * 10, call_class, file)
                for line in range(1, 3)
            )
    rows.extend(_corpus(("test-a", "test-b", "test-c"), per_class=3))

    with pytest.raises(ValueError, match="test-path cap exceeded"):
        stratified_sample(
            rows,
            _roles(("dev-a", "dev-b", "dev-c"), ("test-a", "test-b", "test-c")),
            size=12,
        )


def test_stratified_sample_deduplicates_call_sites() -> None:
    dev = _corpus(("dev-a", "dev-b", "dev-c"), per_class=2)
    test = _corpus(("test-a", "test-b", "test-c"), per_class=2)
    duplicated = [*dev, *test, *(dict(row) for row in dev)]

    result = stratified_sample(
        duplicated,
        _roles(("dev-a", "dev-b", "dev-c"), ("test-a", "test-b", "test-c")),
        size=len(CLASSES),
    )

    assert len(result["dev"]) == len(CLASSES)
    keys = [
        (row["repo"], row["file"], row["line"], row["call_name"])
        for row in result["dev"]
    ]
    assert len(keys) == len(set(keys))


def test_stratified_sample_prefers_production_paths() -> None:
    rows = []
    for repo in ("dev-a", "dev-b", "dev-c"):
        rows.extend(_corpus((repo,), per_class=2))
        rows.extend(_corpus((repo,), per_class=2, file="tests/unit.cpp"))
    rows.extend(_corpus(("test-a", "test-b", "test-c"), per_class=2))

    result = stratified_sample(
        rows,
        _roles(("dev-a", "dev-b", "dev-c"), ("test-a", "test-b", "test-c")),
        size=len(CLASSES),
    )

    assert not any(_is_test_path(str(row["file"])) for row in result["dev"])


def test_stratified_sample_fills_from_test_paths_within_the_cap() -> None:
    rows = []
    for repo in ("dev-a", "dev-b", "dev-c"):
        for index, call_class in enumerate(CLASSES):
            if call_class == "higher_order":
                rows.extend(
                    _record(repo, line + index * 10, call_class, "tests/unit.cpp")
                    for line in range(1, 3)
                )
                continue
            rows.extend(
                _record(repo, line + index * 10, call_class) for line in range(1, 3)
            )
    rows.extend(_corpus(("test-a", "test-b", "test-c"), per_class=3))

    result = stratified_sample(
        rows,
        _roles(("dev-a", "dev-b", "dev-c"), ("test-a", "test-b", "test-c")),
        size=12,
    )

    test_sites = [row for row in result["dev"] if _is_test_path(str(row["file"]))]
    assert len(test_sites) == 2
    assert {row["call_class"] for row in test_sites} == {"higher_order"}


def test_stratified_sample_ignores_vendored_call_sites() -> None:
    rows = [
        _record("dev-a", index, call_class, "third_party/dep/dep.cpp")
        for index, call_class in enumerate(CLASSES, start=1)
    ]

    with pytest.raises(ValueError, match="dev same_file shortfall"):
        stratified_sample(rows, {"dev-a": "dev"}, size=len(CLASSES))


def test_stratified_sample_spreads_classes_across_dev_repos() -> None:
    repos = ("dev-a", "dev-b", "dev-c")
    rows = _corpus(repos, per_class=5)
    rows += _corpus(("test-a", "test-b", "test-c"), per_class=3)
    roles = _roles(repos, ("test-a", "test-b", "test-c"))

    result = stratified_sample(rows, roles, size=len(CLASSES) * 3)

    assert {row["repo"] for row in result["dev"]} == set(repos)
    assert {
        (call_class, repo): sum(
            row["call_class"] == call_class and row["repo"] == repo
            for row in result["dev"]
        )
        for call_class in CLASSES
        for repo in repos
    } == {(call_class, repo): 1 for call_class in CLASSES for repo in repos}


def test_stubs_match_unknown_records_and_keep_call_name() -> None:
    records = [_record("dev-a", 1, "dynamic"), _record("dev-a", 2, "member")]
    records[0]["ground_truth"] = "unknown"

    stubs = stubs_for_unknown(records)

    assert len(stubs) == sum(row["ground_truth"] == "unknown" for row in records)
    assert stubs[0]["call_name"] == records[0]["call_name"]


def test_review_stub_keeps_reviewers_independent() -> None:
    result = stub(_record("test-a", 10, "dynamic"))

    assert result["reviewer_1"] == {"target": None, "reason": None}
    assert result["reviewer_2"] == {"target": None, "reason": None}
    assert result["agreement"] is None


def test_frozen_manifest_states_records_and_unknown_counts(tmp_path) -> None:
    sites = [_record("test-a", 1, "dynamic"), _record("test-a", 2, "member")]
    sites[0]["ground_truth"] = "unknown"
    path = tmp_path / "test-sites.jsonl"
    write_jsonl(path, sites)

    entry = manifest_file(
        "notes/restricted/call-audit/cpp/test-sites.jsonl",
        path,
        len(sites),
        unknown_count(sites),
    )

    assert entry["records"] == 2
    assert entry["unknown_records"] == 1
    assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert entry["bytes"] == path.stat().st_size


def test_sample_main_writes_dev_frozen_and_manifest(tmp_path) -> None:
    records = _corpus(("dev-a", "dev-b", "dev-c"), per_class=1) + _corpus(
        ("test-a", "test-b", "test-c"), per_class=1
    )
    paths = {
        "dev_sites": tmp_path / "dev" / "sites.jsonl",
        "dev_stubs": tmp_path / "dev" / "stubs" / "review-stubs.jsonl",
        "test_sites": tmp_path / "frozen" / "test-sites.jsonl",
        "test_stubs": tmp_path / "frozen" / "review-stubs.jsonl",
        "manifest": tmp_path / "test-manifest-cpp.json",
    }
    records_path = tmp_path / "records.jsonl"
    write_jsonl(records_path, records)
    repos_path = tmp_path / "cpp.toml"
    repos_path.write_text(
        '[[repos]]\nrepo = "dev-a"\nrole = "dev"\n'
        '[[repos]]\nrepo = "dev-b"\nrole = "dev"\n'
        '[[repos]]\nrepo = "dev-c"\nrole = "dev"\n'
        '[[repos]]\nrepo = "test-a"\nrole = "test-only"\n'
        '[[repos]]\nrepo = "test-b"\nrole = "test-only"\n'
        '[[repos]]\nrepo = "test-c"\nrole = "test-only"\n'
    )

    exit_code = sample_main(
        [
            "--records",
            str(records_path),
            "--repos",
            str(repos_path),
            "--dev-sites",
            str(paths["dev_sites"]),
            "--dev-stubs",
            str(paths["dev_stubs"]),
            "--test-sites",
            str(paths["test_sites"]),
            "--test-stubs",
            str(paths["test_stubs"]),
            "--manifest",
            str(paths["manifest"]),
            "--manifest-prefix",
            "notes/restricted/call-audit/cpp",
            "--size",
            str(len(CLASSES)),
        ]
    )

    manifest = json.loads(paths["manifest"].read_text())
    assert exit_code == 0
    assert len(read_jsonl(paths["dev_sites"])) == len(CLASSES)
    assert len(read_jsonl(paths["test_sites"])) == len(CLASSES)
    assert manifest["records"] == len(CLASSES)
    assert manifest["unknown_records"] == 0
    assert [entry["path"] for entry in manifest["files"]] == [
        "notes/restricted/call-audit/cpp/test-sites.jsonl",
        "notes/restricted/call-audit/cpp/review-stubs.jsonl",
    ]
    assert all(
        entry["records"] == count
        for entry, count in zip(manifest["files"], (len(CLASSES), 0), strict=True)
    )
    assert all(entry["unknown_records"] == 0 for entry in manifest["files"])


def test_manifest_reports_repo_and_class_breaking_counts(tmp_path) -> None:
    records = _corpus(("dev-a", "dev-b", "dev-c"), per_class=1) + _corpus(
        ("test-a", "test-b", "test-c"), per_class=1
    )
    records[0]["ground_truth"] = "unknown"
    records_path = tmp_path / "records.jsonl"
    write_jsonl(records_path, records)
    repos_path = tmp_path / "cpp.toml"
    repos_path.write_text(
        "".join(
            f'[[repos]]\nrepo = "{repo}"\nrole = "{role}"\n'
            for repo, role in (
                ("dev-a", "dev"),
                ("dev-b", "dev"),
                ("dev-c", "dev"),
                ("test-a", "test-only"),
                ("test-b", "test-only"),
                ("test-c", "test-only"),
            )
        )
    )

    sample_main(
        [
            "--records",
            str(records_path),
            "--repos",
            str(repos_path),
            "--dev-sites",
            str(tmp_path / "dev.jsonl"),
            "--dev-stubs",
            str(tmp_path / "dev-stubs.jsonl"),
            "--test-sites",
            str(tmp_path / "test-sites.jsonl"),
            "--test-stubs",
            str(tmp_path / "test-stubs.jsonl"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--manifest-prefix",
            "notes/restricted/call-audit/cpp",
            "--size",
            str(len(CLASSES)),
        ]
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    breakdown = manifest["dev"]["repo_class_breakdown"]
    first = records[0]
    entry = next(
        row
        for row in breakdown
        if row["repo"] == first["repo"] and row["call_class"] == first["call_class"]
    )
    assert entry["records"] == 1
    assert entry["unknown_records"] == 1
    assert manifest["dev"]["unknown_by_class"][str(first["call_class"])] == 1
    assert manifest["dev"]["unknown_by_repo"][str(first["repo"])] == 1


def test_higher_order_syntax_skips_signature_declarations_and_initializers(
    tmp_path,
) -> None:
    source = """struct Worker {
  Worker(void (*function)(void*))
      : function(function) {}
  void (*const function)(void*);
  const char* (*name)(void*);
};
void run() {
  (*name)(nullptr);
}
"""
    file = tmp_path / "members.cpp"
    file.write_text(source)
    symbol = {
        "name": "run",
        "range": {"start": {"line": 6}, "end": {"line": 8}},
        "selectionRange": {"start": {"line": 6}},
    }

    records = _higher_order_records(
        RepoContext(tmp_path.resolve(), "fixture/members"),
        file,
        source,
        [symbol],
        [],
    )

    assert [row["call_name"] for row in records] == ["name"]
    assert records[0]["line"] == 8


def test_sample_main_reports_frozen_breakdown(tmp_path) -> None:
    records = _corpus(("dev-a", "dev-b", "dev-c"), per_class=1) + _corpus(
        ("test-a", "test-b", "test-c"), per_class=1
    )
    records_path = tmp_path / "records.jsonl"
    write_jsonl(records_path, records)
    repos_path = tmp_path / "cpp.toml"
    repos_path.write_text(
        "".join(
            f'[[repos]]\nrepo = "{repo}"\nrole = "{role}"\n'
            for repo, role in (
                ("dev-a", "dev"),
                ("dev-b", "dev"),
                ("dev-c", "dev"),
                ("test-a", "test-only"),
                ("test-b", "test-only"),
                ("test-c", "test-only"),
            )
        )
    )

    sample_main(
        [
            "--records",
            str(records_path),
            "--repos",
            str(repos_path),
            "--dev-sites",
            str(tmp_path / "dev.jsonl"),
            "--dev-stubs",
            str(tmp_path / "dev-stubs.jsonl"),
            "--test-sites",
            str(tmp_path / "test-sites.jsonl"),
            "--test-stubs",
            str(tmp_path / "test-stubs.jsonl"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--manifest-prefix",
            "notes/restricted/call-audit/cpp",
            "--size",
            str(len(CLASSES)),
        ]
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    frozen = manifest["frozen"]
    assert frozen["records"] == len(CLASSES)
    assert set(frozen["class_counts"]) == set(CLASSES)
    assert sum(frozen["repo_counts"].values()) == len(CLASSES)
    assert len(frozen["repo_class_breakdown"]) == len(CLASSES)
    assert frozen["unknown_by_repo"] == {}
