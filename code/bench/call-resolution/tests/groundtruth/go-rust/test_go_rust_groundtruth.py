from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "groundtruth" / "go-rust"))

from audit.records import validate_record
from export import (
    CALL_CLASSES,
    cargo_package_name,
    definition_location,
    distinct_calls,
    filter_go_calls,
    finalize_rust_site,
    module_name,
    name_mismatches,
    repo_cap,
    resolve_rust_scip,
    rust_candidates,
    rust_source_calls,
    sample_sites,
    target_kind,
)
from sample import class_counts, review_stubs
from verify_manifest import verify_manifest


class FakeDefinitionRunner:
    def __init__(self, definition: dict[str, object] | None) -> None:
        self._definition = definition

    def definition(self, _site: dict[str, object]) -> dict[str, object] | None:
        return self._definition


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _int_field(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _bytes_field(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _scip_occurrence(symbol: str, line: int, character: int, roles: int) -> bytes:
    location = b"".join(
        (
            _int_field(1, line),
            _int_field(2, character),
            _int_field(3, character + len(symbol)),
        )
    )
    return b"".join(
        (
            _bytes_field(8, location),
            _bytes_field(2, symbol.encode()),
            _int_field(3, roles),
        )
    )


def _site(
    repo: str, language: str, call_class: str, line: int = 9
) -> dict[str, object]:
    return {
        "repo": repo,
        "language": language,
        "file": "src/lib.rs",
        "line": line,
        "call_name": "target",
        "call_class": call_class,
        "ground_truth": "unknown",
        "measured_edge": None,
        "measured_status": "opaque",
        "truth_source": "rust-analyzer",
        "function_id": "src/lib.rs:7:caller",
        "module": "lib",
        "_uri": "file:///repo/src/lib.rs",
        "_identifier": "target",
        "_syntax": "same_file",
    }


def _scip_index_bytes(source: str) -> bytes:
    source_lines = source.splitlines()
    call_line = source_lines[1]
    call_character = len(call_line[: call_line.index("target")].encode("utf-8"))
    document = b"".join(
        (
            _bytes_field(1, b"src/lib.rs"),
            _bytes_field(2, _scip_occurrence("local 1", 0, 3, 1)),
            _bytes_field(2, _scip_occurrence("local 1", 1, call_character, 8)),
        )
    )
    return _bytes_field(2, document)


def _write_rust_repo_manifest(path: Path, sha: str) -> None:
    path.write_text(
        "[[repo]]\n"
        'language = "rust"\n'
        'name = "example/example"\n'
        'url = "https://example.invalid/example.git"\n'
        f'sha = "{sha}"\n'
        'license = "MIT"\n'
        'license_file = "LICENSE"\n'
        'kind = "library"\n'
        'role = "dev"\n'
        "commit_count = 1\n"
    )


def test_fake_rust_analyzer_definition_maps_to_declaration(tmp_path: Path) -> None:
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text("fn target() {}\n")
    site = _site("repo", "rust", "same_file")
    fake = FakeDefinitionRunner(
        {"uri": f"file://{source}", "range": {"start": {"line": 0, "character": 3}}}
    )

    finalize_rust_site(site, fake.definition(site), tmp_path)

    assert site["ground_truth"] == "src/lib.rs:1:target"
    assert site["call_class"] == "same_file"
    assert site["measured_status"] == "unresolved"


def test_missing_tool_definition_stays_opaque_dynamic() -> None:
    site = _site("repo", "rust", "same_file")
    site["_syntax"] = "member"
    fake = FakeDefinitionRunner(None)

    finalize_rust_site(site, fake.definition(site), Path("/repo"))

    assert site["ground_truth"] == "unknown"
    assert site["call_class"] == "dynamic"
    assert site["measured_status"] == "opaque"


def test_sampling_respects_reserved_repo_roles_and_class_quotas() -> None:
    roles = {
        "dev-a": "dev",
        "dev-b": "dev",
        "dev-c": "dev",
        "test-a": "test-only",
        "test-b": "test-only",
        "test-c": "test-only",
    }
    sites = [
        _site(repo, "rust", call_class, line)
        for repo in roles
        for call_class in CALL_CLASSES
        for line in (9, 10)
    ]

    dev = sample_sites(sites, roles, "rust", "dev", seed=9, size=18)
    test = sample_sites(sites, roles, "rust", "test-only", seed=9, size=18)

    assert Counter(row["call_class"] for row in dev) == Counter(
        dict.fromkeys(CALL_CLASSES, 3)
    )
    assert Counter(row["call_class"] for row in test) == Counter(
        dict.fromkeys(CALL_CLASSES, 3)
    )
    assert {row["repo"] for row in dev} == {"dev-a", "dev-b", "dev-c"}
    assert {row["repo"] for row in test} == {"test-a", "test-b", "test-c"}
    assert {row["repo"] for row in dev}.isdisjoint({row["repo"] for row in test})
    for row in dev + test:
        validate_record(row)
        assert isinstance(row["call_name"], str)
    per_repo = Counter(row["repo"] for row in dev)
    assert max(per_repo.values()) <= repo_cap(18)


def test_multiple_tool_definitions_are_not_guessed() -> None:
    definitions = [
        {"uri": "file:///repo/a.rs", "range": {"start": {"line": 2}}},
        {"uri": "file:///repo/b.rs", "range": {"start": {"line": 4}}},
    ]

    assert definition_location(definitions) is None


def test_unresolved_sites_get_two_independent_review_slots() -> None:
    site = _site("repo", "rust", "dynamic")

    stubs = review_stubs([site])

    assert len(stubs) == 1
    assert [review["reviewer"] for review in stubs[0]["reviewers"]] == [
        "reviewer-a",
        "reviewer-b",
    ]
    assert stubs[0]["agreement"] is None


def test_manifest_verification_checks_only_artifact_hashes(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    artifact = notes / "restricted" / "call-audit" / "go-rust" / "test.jsonl"
    artifact.parent.mkdir(parents=True)
    content = b"small fixture\n"
    artifact.write_bytes(content)
    import hashlib
    import json

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "sets": [
                    {
                        "path": "notes/restricted/call-audit/go-rust/test.jsonl",
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "review_stubs_path": (
                            "notes/restricted/call-audit/go-rust/stubs.json"
                        ),
                        "review_stubs_sha256": "missing",
                    }
                ]
            }
        )
    )

    assert verify_manifest(manifest, notes) == [
        "missing notes/restricted/call-audit/go-rust/stubs.json"
    ]


def test_rust_source_scan_finds_member_and_constructor_sites(tmp_path: Path) -> None:
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        "fn caller() {\n    target();\n    thing.run();\n    Thing::new();\n}\n"
    )

    sites = rust_source_calls(source, tmp_path, "fixture/rust")

    assert [(site["_identifier"], site["call_class"]) for site in sites] == [
        ("target", "same_file"),
        ("run", "member"),
        ("new", "constructor"),
    ]
    assert [site["call_name"] for site in sites] == ["target", "run", "new"]
    assert {site["function_id"] for site in sites} == {"src/lib.rs:1:caller"}


def test_scip_occurrence_maps_call_name_to_in_repo_definition(tmp_path: Path) -> None:
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text('fn target() {}\nfn caller() { let café = "ø"; target(); }\n')
    symbol = "local 1"
    call_line = source.read_text().splitlines()[1]
    call_character = len(call_line[: call_line.index("target")].encode("utf-8"))
    document = b"".join(
        (
            _bytes_field(1, b"src/lib.rs"),
            _bytes_field(2, _scip_occurrence(symbol, 0, 3, 1)),
            _bytes_field(2, _scip_occurrence(symbol, 1, call_character, 8)),
        )
    )
    index = tmp_path / "index.scip"
    index.write_bytes(_bytes_field(2, document))
    sites = rust_source_calls(source, tmp_path, "repo/rust")

    resolved = resolve_rust_scip(tmp_path, sites, index)

    assert resolved[0]["call_name"] == "target"
    assert resolved[0]["ground_truth"] == "src/lib.rs:1:target"
    assert resolved[0]["call_class"] == "same_file"


def test_one_call_name_per_source_line_is_kept(tmp_path: Path) -> None:
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text("fn caller() {\n    target(); target();\n}\n")

    sites = rust_candidates(tmp_path, "fixture/rust")

    assert [site["call_name"] for site in sites] == ["target"]


def test_nested_checkout_sources_are_excluded(tmp_path: Path) -> None:
    vendored = tmp_path / "runtime" / "grammars" / "sources" / "tree"
    (vendored / "src").mkdir(parents=True)
    (vendored / ".git").mkdir()
    (vendored / "src" / "lib.rs").write_text("fn vendored() { target(); }\n")
    own = tmp_path / "src"
    own.mkdir()
    (own / "lib.rs").write_text("fn own() { target(); }\n")

    sites = rust_candidates(tmp_path, "fixture/rust")

    assert {site["file"] for site in sites} == {"src/lib.rs"}


def test_unparseable_manifest_falls_back_to_path_module(tmp_path: Path) -> None:
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text("[package\nname = broken\n")
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text("fn caller() { target(); }\n")

    assert cargo_package_name(manifest) is None
    assert module_name(source, tmp_path) == "src"


def test_go_builtins_and_conversions_are_dropped() -> None:
    rows = [
        {"call_name": "len", "_callee_kind": "builtin"},
        {"call_name": "uint32", "_callee_kind": "conversion"},
        {"call_name": "helper", "_callee_kind": "function"},
        {"call_name": "callback", "_callee_kind": "value"},
    ]

    kept = filter_go_calls([dict(row) for row in rows])

    assert [row["call_name"] for row in kept] == ["helper", "callback"]
    assert all("_callee_kind" not in row for row in kept)


def test_export_go_deduplicates_repeated_calls_on_one_line(tmp_path: Path) -> None:
    def row(line: int) -> dict[str, object]:
        return {
            "repo": "example/example",
            "language": "go",
            "file": "main.go",
            "line": line,
            "call_name": "helper",
            "call_class": "same_file",
            "ground_truth": "main.go:1:helper",
            "measured_edge": None,
            "measured_status": "unresolved",
            "truth_source": "go/types",
            "function_id": "main.go:1:caller",
            "module": "main",
            "_callee_kind": "function",
        }

    sites = distinct_calls([row(3), row(3), row(4)])

    assert [site["line"] for site in sites] == [3, 4]


def test_attributes_and_variant_constructors_are_not_calls(tmp_path: Path) -> None:
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        "#[derive(Clone, Debug)]\n"
        "struct Thing { value: u32 }\n"
        "fn caller(input: Option<u32>) -> Result<u32, u32> {\n"
        '    println!("value {:?}", input);\n'
        "    let Some(value) = input else { return Err(2); };\n"
        "    Ok(helper(value))\n"
        "}\n"
        "fn helper(value: u32) -> u32 { value }\n"
    )

    sites = rust_source_calls(source, tmp_path, "fixture/rust")

    assert [site["call_name"] for site in sites] == ["helper"]


def test_parenthesised_callback_call_is_a_candidate(tmp_path: Path) -> None:
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        "struct Runner { callback: Option<fn(u32) -> u32> }\n"
        "fn run(self) {\n"
        "    (self.callback)(1);\n"
        "}\n"
    )

    sites = rust_source_calls(source, tmp_path, "fixture/rust")

    assert [(site["call_name"], site["_syntax"]) for site in sites] == [
        ("callback", "member")
    ]


def test_target_kind_recognises_callable_bindings() -> None:
    assert target_kind("    fn helper(&self) -> u32 {", "helper") == "function"
    assert target_kind("    let callback = |x| x;", "callback") == "higher_order"
    assert target_kind("    f: fn(u32) -> u32,", "f") == "higher_order"
    assert target_kind("    handler: Box<dyn Fn(u32)>,", "handler") == "higher_order"
    assert target_kind("    Pattern(PatternID),", "Pattern") == "other"
    assert target_kind("    pub const fn as_usize(&self) -> usize {", "as_usize") == (
        "function"
    )
    assert target_kind("    let big_bytes = dfa.to_bytes();", "pred") == "missing"


def test_resolved_target_must_declare_the_called_name(tmp_path: Path) -> None:
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text("fn other() {}\nfn caller() { target(); }\n")
    index = tmp_path / "index.scip"
    index.write_bytes(_scip_index_bytes(source.read_text()))
    sites = rust_source_calls(source, tmp_path, "repo/rust")
    assert [site["call_name"] for site in sites] == ["target"]

    resolved = resolve_rust_scip(tmp_path, sites, index)

    assert resolved[0]["ground_truth"] == "unknown"
    assert resolved[0]["call_class"] == "dynamic"


def test_variant_constructor_target_is_dropped(tmp_path: Path) -> None:
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        "enum Kind {\n    Pattern(u32),\n}\nfn caller() { Pattern(1); }\n"
    )
    symbol = "local 1"
    call_line = source.read_text().splitlines()[3]
    document = b"".join(
        (
            _bytes_field(1, b"src/lib.rs"),
            _bytes_field(2, _scip_occurrence(symbol, 1, 4, 1)),
            _bytes_field(
                2,
                _scip_occurrence(
                    symbol, 3, len(call_line[: call_line.index("Pattern")]), 8
                ),
            ),
        )
    )
    index = tmp_path / "index.scip"
    index.write_bytes(_bytes_field(2, document))
    sites = rust_source_calls(source, tmp_path, "repo/rust")
    assert [site["call_name"] for site in sites] == ["Pattern"]

    resolved = resolve_rust_scip(tmp_path, sites, index)

    assert resolved == []


def test_name_mismatches_flags_a_target_that_does_not_declare_the_call(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pins" / "example" / "src" / "lib.rs"
    source.parent.mkdir(parents=True)
    source.write_text("fn target() {}\nfn other() {}\n")
    matching = _site("example/example", "rust", "same_file")
    matching["ground_truth"] = "src/lib.rs:1:target"
    mismatching = dict(matching, ground_truth="src/lib.rs:2:target")

    failures = name_mismatches([matching, mismatching], tmp_path / "pins")

    assert failures == [mismatching]


def test_sampling_respects_the_repository_share_cap() -> None:
    roles = {"dev-a": "dev", "dev-b": "dev"}
    sites = [
        _site(f"dev-{name}", "rust", call_class, line)
        for name in ("a", "b")
        for call_class in CALL_CLASSES
        for line in range(1, 201)
    ]

    sample = sample_sites(sites, roles, "rust", "dev", seed=11)

    per_repo = Counter(row["repo"] for row in sample)
    assert max(per_repo.values()) <= repo_cap(300)
    assert len(sample) == 2 * repo_cap(300)


def test_sampling_favours_in_repo_targets_up_to_half_of_each_quota() -> None:
    roles = {"dev-a": "dev"}
    sites = [
        dict(
            _site("dev-a", "rust", "member", line),
            ground_truth=f"src/lib.rs:{line}:target",
        )
        for line in range(1, 101)
    ] + [_site("dev-a", "rust", "member", line) for line in range(200, 300)]
    sites += [_site("dev-a", "rust", "dynamic", line) for line in range(1, 1001)]

    sample = sample_sites(sites, roles, "rust", "dev", seed=13, size=12)

    members = [row for row in sample if row["call_class"] == "member"]
    assert len(members) == 2
    assert sum(1 for row in members if row["ground_truth"] != "unknown") == 1


def test_sampling_never_relabels_a_class_to_reach_the_target() -> None:
    roles = {"dev-a": "dev", "dev-b": "dev"}
    sites = [_site("dev-a", "rust", "member", line) for line in range(1, 121)] + [
        _site("dev-b", "rust", "imported", line) for line in range(1, 121)
    ]

    sample = sample_sites(sites, roles, "rust", "dev", seed=5)

    assert class_counts(sample) == {"imported": 120, "member": 120}
    assert len(sample) == 240


def test_sampling_keeps_a_scarce_class_honest_and_fills_from_surplus() -> None:
    roles = {"dev-a": "dev", "dev-b": "dev", "dev-c": "dev"}
    sites = [
        site
        for name in ("a", "b", "c")
        for site in [
            *(_site(f"dev-{name}", "rust", "member", line) for line in range(1, 8)),
            *(_site(f"dev-{name}", "rust", "dynamic", line) for line in range(1, 301)),
        ]
    ]

    sample = sample_sites(sites, roles, "rust", "dev", seed=17)

    counts = class_counts(sample)
    assert len(sample) == 300
    assert counts["member"] == 21
    assert counts["dynamic"] == 279
    assert counts["member"] < 50


def test_sampling_spreads_surplus_over_the_largest_pools() -> None:
    roles = {"dev-a": "dev", "dev-b": "dev", "dev-c": "dev"}
    sites = [
        site
        for name in ("a", "b", "c")
        for site in [
            *(_site(f"dev-{name}", "rust", "member", line) for line in range(1, 61)),
            *(_site(f"dev-{name}", "rust", "dynamic", line) for line in range(1, 201)),
        ]
    ]

    sample = sample_sites(sites, roles, "rust", "dev", seed=19, size=120)

    counts = class_counts(sample)
    assert sum(counts.values()) == 120
    assert counts["member"] == 60
    assert counts["dynamic"] == 60
    per_repo = Counter(row["repo"] for row in sample)
    assert max(per_repo.values()) <= repo_cap(120)


def test_dev_datasets_name_check_against_pinned_checkouts() -> None:
    repos_root = Path(__file__).parents[3] / "envs" / "go-rust" / "pins"
    dev_root = Path(__file__).parents[3] / "data" / "dev" / "go-rust"
    if not repos_root.is_dir():
        pytest.skip("pinned checkouts are not present")
    builtins = {
        "len",
        "new",
        "make",
        "append",
        "cap",
        "copy",
        "delete",
        "panic",
        "recover",
        "print",
        "println",
        "min",
        "max",
        "clear",
        "close",
    }
    records = [
        json.loads(line)
        for path in sorted(dev_root.glob("*.jsonl"))
        for line in path.read_text().splitlines()
        if line
    ]
    assert records

    assert name_mismatches(records, repos_root) == []
    assert [
        row["call_name"]
        for row in records
        if row["language"] == "go" and row["call_name"] in builtins
    ] == []


def test_collect_reuses_an_existing_scip_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import collect as collect_module

    manifest = tmp_path / "repos.toml"
    _write_rust_repo_manifest(manifest, "abc123")
    checkout = tmp_path / "cache" / "example"
    source = checkout / "src" / "lib.rs"
    source.parent.mkdir(parents=True)
    source.write_text("fn target() {}\nfn caller() { target(); }\n")
    index = tmp_path / "scip" / "example.scip"
    index.parent.mkdir()
    index.write_bytes(_scip_index_bytes(source.read_text()))
    monkeypatch.setattr(collect_module, "REPOS", manifest)
    commands: list[list[str]] = []

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append([str(part) for part in command])
        return subprocess.CompletedProcess(command, 0, stdout="abc123\n", stderr="")

    monkeypatch.setattr(collect_module.subprocess, "run", fake_run)
    output = tmp_path / "candidates.jsonl"

    collect_module.collect(
        tmp_path / "cache",
        output,
        "rust",
        "scip",
        collect_module.RustScip(tmp_path / "rust-analyzer", index.parent, True),
    )

    assert commands == [["git", "-C", str(checkout), "rev-parse", "HEAD"]]
    assert json.loads(output.read_text())["ground_truth"] == "src/lib.rs:1:target"


def test_collect_indexes_a_repository_without_a_cached_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import collect as collect_module

    manifest = tmp_path / "repos.toml"
    _write_rust_repo_manifest(manifest, "abc123")
    checkout = tmp_path / "cache" / "example"
    source = checkout / "src" / "lib.rs"
    source.parent.mkdir(parents=True)
    source.write_text("fn target() {}\nfn caller() { target(); }\n")
    index = tmp_path / "scip" / "example.scip"
    monkeypatch.setattr(collect_module, "REPOS", manifest)
    commands: list[list[str]] = []

    def fake_run(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append([str(part) for part in command])
        if "scip" in command:
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_bytes(_scip_index_bytes(source.read_text()))
        return subprocess.CompletedProcess(command, 0, stdout="abc123\n", stderr="")

    monkeypatch.setattr(collect_module.subprocess, "run", fake_run)

    collect_module.collect(
        tmp_path / "cache",
        tmp_path / "candidates.jsonl",
        "rust",
        "scip",
        collect_module.RustScip(tmp_path / "rust-analyzer", index.parent, False),
    )

    assert [["scip" in command for command in commands]] == [[False, True]]
