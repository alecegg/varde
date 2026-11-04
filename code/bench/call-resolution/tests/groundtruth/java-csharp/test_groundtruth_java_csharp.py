import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "groundtruth" / "java-csharp"),
)

from export_repositories import _records_current, _verify_license
from pipeline import (
    CALL_CLASSES,
    export_tool_output,
    sample_by_role,
    verification_stub,
    verify_manifest,
    write_jsonl,
    write_manifest,
)
from tools import (
    _dotnet_root,
    _global_usings_file,
    _link_framework_references,
    _msbuild_properties,
    _package_versions,
    _unusable_packages,
    exporter_digest,
    run_csharp,
    run_java,
)


def _records() -> tuple[list[dict[str, object]], dict[str, str]]:
    roles = {
        "dev-a": "dev",
        "dev-b": "dev",
        "dev-c": "dev",
        "test-a": "test-only",
        "test-b": "test-only",
        "test-c": "test-only",
    }
    records = []
    for repo in roles:
        for call_class in CALL_CLASSES:
            for line in range(2):
                target = None if call_class == "dynamic" else "target"
                records.extend(
                    export_tool_output(
                        [
                            {
                                "file": "src/calls.cs",
                                "line": CALL_CLASSES.index(call_class) * 2 + line + 1,
                                "call_name": "run",
                                "call_class": call_class,
                                "target": target,
                                "target_kind": None,
                                "caller": "src/calls.cs::Caller",
                                "module": "src",
                                "truth_source": "roslyn:test-double",
                            }
                        ],
                        repo=repo,
                        language="csharp",
                    )
                )
    return records, roles


def _files_outside(root: Path, allowed: Path) -> set[str]:
    return {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and allowed not in path.parents
    }


def test_export_maps_compiler_targets_and_dynamic_calls() -> None:
    records = export_tool_output(
        [
            {
                "file": "src/Calls.java",
                "line": 7,
                "call_name": "run",
                "call_class": "same_file",
                "target": "src/Calls.java::Worker.run",
                "target_kind": "project",
                "caller": "src/Calls.java::Main.start",
                "module": "src",
                "target_module": "src",
                "truth_source": "javac:test-double",
            },
            {
                "file": "src/Calls.java",
                "line": 8,
                "call_name": "invoke",
                "call_class": "dynamic",
                "target": None,
                "target_kind": None,
                "caller": "src/Calls.java::Main.start",
                "module": "src",
                "truth_source": "javac:test-double",
            },
            {
                "file": "src/Calls.java",
                "line": 9,
                "call_name": "accept",
                "call_class": "higher_order",
                "target": None,
                "target_kind": "dynamic",
                "caller": "src/Calls.java::Main.start",
                "module": "src",
                "truth_source": "javac:test-double",
            },
            {
                "file": "src/Calls.java",
                "line": 10,
                "call_name": "of",
                "call_class": "member",
                "target": None,
                "target_kind": "external",
                "caller": "src/Calls.java::Main.start",
                "module": "src",
                "truth_source": "javac:test-double",
            },
        ],
        repo="repo",
        language="java",
    )

    assert records[0]["ground_truth"] == "src/Calls.java::Worker.run"
    assert records[0]["call_name"] == "run"
    assert records[0]["measured_edge"] is None
    assert records[0]["measured_status"] == "unresolved"
    assert records[1]["ground_truth"] == "unknown"
    assert records[1]["call_class"] == "dynamic"
    assert records[2]["ground_truth"] == "unknown"
    assert records[2]["call_class"] == "higher_order"
    assert records[3]["ground_truth"] == "external"
    assert all(record["measured_status"] == "unresolved" for record in records)


def test_export_keeps_virtual_declaration_targets() -> None:
    record = export_tool_output(
        [
            {
                "file": "src/Calls.cs",
                "line": 3,
                "call_name": "Run",
                "call_class": "member",
                "target": "src/Base.cs::Base.Run()",
                "target_kind": "project",
                "truth_source": "roslyn:test-double",
            },
            {
                "file": "src/Calls.cs",
                "line": 4,
                "call_name": "MoveNext",
                "call_class": "member",
                "target": "src/Enumerator.cs::IEnumerator.MoveNext()",
                "target_kind": "project",
                "truth_source": "roslyn:test-double",
            },
        ],
        repo="repo",
        language="csharp",
    )

    assert record[0]["ground_truth"] == "src/Base.cs::Base.Run()"
    assert record[0]["call_class"] == "member"
    assert record[1]["ground_truth"] == "src/Enumerator.cs::IEnumerator.MoveNext()"


def test_license_verification_checks_first_nonblank_evidence_line() -> None:
    text = "Copyright (c) .NET Foundation and Contributors.\n\n"
    text += (
        "Permission is hereby granted, free of charge, to any person obtaining a copy."
    )

    _verify_license(
        text,
        "MIT",
        "Copyright (c) .NET Foundation and Contributors.",
    )

    with pytest.raises(ValueError, match="does not verify"):
        _verify_license(text, "MIT", "The MIT License")

    with pytest.raises(ValueError, match="does not verify"):
        _verify_license(
            "Apache License\nVersion 2.0, January 2004\n",
            "MIT",
            "Apache License",
        )


def test_sampling_balances_repositories_paths_and_unique_sites() -> None:
    records, roles = _records()
    for record in records[:6]:
        record["file"] = "src/tests/calls.cs"
    records.append(dict(records[0]))
    sampled = sample_by_role(records, roles, seed=2, size=12)[0]["dev"]

    sites = [
        (row["repo"], row["file"], row["line"], row["call_name"]) for row in sampled
    ]
    assert len(sites) == len(set(sites))
    assert max(Counter(row["repo"] for row in sampled).values()) <= 4
    assert sum("tests" in row["file"] for row in sampled) <= 3


def test_sampling_keeps_sites_that_differ_only_by_call_name() -> None:
    records, roles = _records()
    pool = []
    for role_repos in (("dev-a", "dev-b", "dev-c"), ("test-a", "test-b", "test-c")):
        for index, call_class in enumerate(CALL_CLASSES):
            repo = role_repos[index // 2]
            site = next(
                row
                for row in records
                if row["repo"] == repo and row["call_class"] == call_class
            )
            pool.append(dict(site, line=index + 1, call_name="call1"))
            pool.append(dict(site, line=index + 1, call_name="call2"))

    sampled = sample_by_role(pool, roles, seed=2, size=12)[0]
    for split in ("dev", "test"):
        for call_class in CALL_CLASSES:
            sites = [
                (row["repo"], row["file"], row["line"], row["call_name"])
                for row in sampled[split]
                if row["call_class"] == call_class
            ]
            assert len({site[:3] for site in sites}) == 1
            assert {site[3] for site in sites} == {"call1", "call2"}

    identical = [dict(row, call_name="call") for row in pool]
    deduplicated, coverage = sample_by_role(identical, roles, seed=2, size=12)

    assert Counter(row["call_class"] for row in deduplicated["dev"]) == dict.fromkeys(
        CALL_CLASSES, 1
    )
    assert coverage["dev"]["dynamic"]["available"] == 1


def test_sampling_excludes_vendored_paths() -> None:
    records, roles = _records()
    vendored = [dict(record, file="third_party/lib/calls.cs") for record in records]

    assert (
        sample_by_role(records + vendored, roles, seed=2, size=12)[0]
        == sample_by_role(records, roles, seed=2, size=12)[0]
    )


def test_sampling_excludes_generated_paths() -> None:
    records, roles = _records()
    generated = [
        dict(record, file="src/Generated/Thing.Generated.cs") for record in records
    ]
    generated += [dict(record, file="src/obj/Debug/Thing.g.cs") for record in records]

    sampled, coverage = sample_by_role(records + generated, roles, seed=2, size=12)

    assert sampled == sample_by_role(records, roles, seed=2, size=12)[0]
    assert coverage["dev"]["same_file"]["available"] == 6


def test_sampling_rejects_impossible_repository_and_path_caps() -> None:
    _, roles = _records()
    single_repo = [
        record
        for record in _records()[0]
        if record["repo"] == "dev-a" or record["repo"] == "test-a"
    ]
    blocked, coverage = sample_by_role(single_repo, roles, seed=2, size=12)

    assert len(blocked["dev"]) == 4
    assert all(entry["selected"] <= 4 for entry in coverage["dev"].values())
    # One class is filled to its quota before the next one starts, so the four
    # available slots go to two whole classes instead of one site each.
    assert sorted(
        entry["selected"] for entry in coverage["dev"].values() if entry["selected"]
    ) == [2, 2]

    test_paths = [dict(record, file="src/tests/calls.cs") for record in _records()[0]]
    limited, coverage = sample_by_role(test_paths, roles, seed=2, size=12)

    for split in ("dev", "test"):
        assert len(limited[split]) == 3
        # Classes are filled scarcest-first, so the path cap is spent on the
        # first classes and the later ones get nothing.
        assert coverage[split]["same_file"]["selected"] == 2
        assert coverage[split]["imported"]["selected"] == 1
        assert coverage[split]["constructor"]["selected"] == 0


def test_sampling_obeys_roles_and_is_deterministic() -> None:
    records, roles = _records()
    sampled, _ = sample_by_role(records, roles, seed=19, size=12)

    assert sampled == sample_by_role(records, roles, seed=19, size=12)[0]
    assert Counter(row["call_class"] for row in sampled["dev"]) == dict.fromkeys(
        CALL_CLASSES, 2
    )
    dev_repos = {row["repo"] for row in sampled["dev"]}
    test_repos = {row["repo"] for row in sampled["test"]}
    assert dev_repos.isdisjoint(test_repos)
    assert test_repos <= {repo for repo, role in roles.items() if role == "test-only"}
    assert len(test_repos) == 3


def test_sampling_keeps_a_short_class_honest_and_fills_the_slots_from_supply() -> None:
    records, roles = _records()
    one_dynamic = [
        row
        for row in records
        if row["call_class"] != "dynamic"
        or (
            row["repo"] in {"dev-a", "test-a"}
            and row["line"] == CALL_CLASSES.index("dynamic") * 2 + 1
        )
    ]

    sampled, coverage = sample_by_role(one_dynamic, roles, seed=2, size=12)

    counts = Counter(row["call_class"] for row in sampled["dev"])
    assert len(sampled["dev"]) == 12
    assert len(sampled["test"]) == 12
    # The exhausted class keeps its honest count and the spare slot goes to a
    # class that still has supply.
    assert counts["dynamic"] == 1
    assert sorted(counts.values()) == [1, 2, 2, 2, 2, 3]
    assert coverage["dev"]["dynamic"] == {
        "available": 1,
        "selected": 1,
        "in_repo": 0,
        "quota": 2,
    }


def test_sampling_balances_member_targets_in_repo_and_external() -> None:
    records, roles = _records()
    members = [row for row in records if row["call_class"] == "member"]
    pool = [
        dict(row, line=100 + index, ground_truth="src/Base.cs::Base.Run()")
        for index, row in enumerate(members)
    ] + [
        dict(row, line=200 + index, ground_truth="external")
        for index, row in enumerate(members)
    ]

    sampled, coverage = sample_by_role(pool, roles, seed=2, size=12)

    for split in ("dev", "test"):
        selected = [row for row in sampled[split] if row["call_class"] == "member"]
        assert coverage[split]["member"]["in_repo"] == 6
        assert len(selected) == 12
        assert sum(row["ground_truth"] == "external" for row in selected) == 6


def test_unresolved_sites_get_two_review_slots() -> None:
    unresolved = next(row for row in _records()[0] if row["ground_truth"] == "unknown")

    stub = verification_stub(unresolved)

    assert [reviewer["id"] for reviewer in stub["reviewers"]] == [
        "reviewer_a",
        "reviewer_b",
    ]
    assert stub["site"]["call_class"] == "higher_order"
    assert stub["site"]["call_name"] == unresolved["call_name"]
    assert stub["site"]["function_id"] == unresolved["function_id"]
    assert stub["agreement"] is None


def test_jsonl_digest_matches_written_bytes(tmp_path) -> None:
    records, _ = _records()
    path = tmp_path / "calls.jsonl"
    digest = write_jsonl(path, records[:2])
    manifest = tmp_path / "manifest.json"
    write_manifest(manifest, {"calls.jsonl": digest}, {"java": {"dev": {}}}, 50)

    assert len(digest) == 64
    assert manifest.exists()
    assert path.read_text().count("\n") == 2
    assert verify_manifest(manifest, tmp_path)


def test_manifest_records_a_short_class_as_actual_versus_target(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    coverage = {
        "java": {
            "test": {
                "dynamic": {"available": 19, "selected": 19, "in_repo": 0, "quota": 50},
                "member": {
                    "available": 900,
                    "selected": 50,
                    "in_repo": 25,
                    "quota": 50,
                },
            }
        }
    }

    write_manifest(manifest, {}, coverage, 50)

    payload = json.loads(manifest.read_text())
    shortfall = payload["class_shortfalls"]["java"]["test"]["dynamic"]

    source = payload["coverage"]["java"]["test"]["dynamic"]
    assert shortfall["actual"] == source["selected"]
    assert shortfall["target"] == source["quota"]


def test_hash_verification_detects_changed_bytes(tmp_path) -> None:
    restricted = tmp_path / "restricted"
    restricted.mkdir()
    sample = restricted / "java.jsonl"
    sample.write_bytes(b'{"site":1}\n')
    manifest = tmp_path / "manifest.json"
    write_manifest(manifest, {sample.name: "0" * 64}, {}, 50)

    assert not verify_manifest(manifest, restricted)


def test_java_runner_uses_isolated_paths_and_maps_output(tmp_path) -> None:
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        stdout = (
            ""
            if command[0] == "javac"
            else "\n".join(
                [
                    json.dumps(
                        {
                            "repo": "repo",
                            "file": "src/Main.java",
                            "line": 4,
                            "call_name": "run",
                            "call_class": "member",
                            "target": "src/Worker.java::Worker.run()",
                            "target_kind": "project",
                            "truth_source": "javac:test-double",
                        }
                    ),
                    json.dumps(
                        {
                            "repo": "repo",
                            "file": "src/Main.java",
                            "line": 5,
                            "call_name": "invoke",
                            "call_class": "dynamic",
                            "target": None,
                            "target_kind": "dynamic",
                            "truth_source": "javac:test-double",
                        }
                    ),
                ]
            )
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    output = tmp_path / "output" / "java.jsonl"
    env_root = tmp_path / "env"
    rows = run_java(
        "repo", tmp_path, tmp_path / "src", output, env_root, runner=fake_runner
    )

    assert len(calls) == 2
    assert calls[0][0][0] == "javac"
    assert calls[1][0][:3] == ["java", "-cp", str(env_root / "javac-classes")]
    assert calls[1][0][-3:] == ["repo", str(tmp_path), str(tmp_path / "src")]
    env = calls[0][1]["env"]
    assert Path(env["HOME"]).is_relative_to(env_root)
    assert Path(env["TMPDIR"]).is_relative_to(env_root)
    assert Path(env["XDG_CONFIG_HOME"]).is_relative_to(env_root)
    assert Path(env["MAVEN_OPTS"].split("=", 1)[1]).is_relative_to(env_root)
    assert rows[0]["ground_truth"] == "src/Worker.java::Worker.run()"
    assert rows[0]["call_name"] == "run"
    assert rows[1]["ground_truth"] == "unknown"
    assert output.is_file()
    assert _files_outside(tmp_path, env_root) == {
        "output/java.jsonl",
        "output/java-human-review.jsonl",
        "output/java.stamp",
    }
    review = json.loads(
        (tmp_path / "output" / "java-human-review.jsonl").read_text().splitlines()[0]
    )
    assert review["site"]["call_class"] == "dynamic"
    assert review["status"] == "pending_human_verification"


def test_csharp_runner_uses_isolated_paths_and_maps_output(tmp_path) -> None:
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        stdout = (
            ""
            if command[1] == "build"
            else json.dumps(
                {
                    "repo": "repo",
                    "file": "src/Main.cs",
                    "line": 8,
                    "call_name": "handler",
                    "call_class": "higher_order",
                    "target": None,
                    "target_kind": "dynamic",
                    "truth_source": "roslyn:test-double",
                }
            )
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    references = tmp_path / "references"
    references.mkdir()
    (references / "Xunit.Assert-abc123.dll").symlink_to(references / "missing.dll")
    output = tmp_path / "output" / "csharp.jsonl"
    env_root = tmp_path / "env"
    rows = run_csharp(
        "repo",
        tmp_path,
        tmp_path / "src",
        output,
        env_root,
        references=references,
        runner=fake_runner,
    )

    assert len(calls) == 2
    assert calls[0][0][:2] == ["dotnet", "build"]
    assert calls[1][0][:2] == ["dotnet", "exec"]
    assert calls[1][0][-2].endswith("references.txt")
    assert calls[1][0][-1].endswith("extra-sources.txt")
    env = calls[0][1]["env"]
    assert Path(env["HOME"]).is_relative_to(env_root)
    assert Path(env["DOTNET_CLI_HOME"]).is_relative_to(env_root)
    assert Path(env["NUGET_PACKAGES"]).is_relative_to(env_root)
    assert Path(env["DOTNET_ROOT"]).is_absolute()
    assert rows[0]["ground_truth"] == "unknown"
    assert rows[0]["call_name"] == "handler"
    assert rows[0]["call_class"] == "higher_order"
    assert output.is_file()
    assert _files_outside(tmp_path, env_root) == {
        "output/csharp.jsonl",
        "output/csharp-human-review.jsonl",
        "output/csharp.stamp",
    }
    reference_list = env_root / "roslyn-runner" / "references.txt"
    assert reference_list.read_text().strip() == str(
        (references / "missing.dll").resolve()
    )


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_java_exporter_labels_declaration_targets_and_function_values(tmp_path) -> None:
    source = tmp_path / "repo" / "src" / "fixture"
    source.mkdir(parents=True)
    (source / "Sized.java").write_text(
        "package fixture;\n"
        "public interface Sized {\n"
        "  int size();\n"
        "  int capacity();\n"
        "}\n"
    )
    (source / "Box.java").write_text(
        "package fixture;\n"
        "public class Box implements Sized {\n"
        "  public int size() { return 0; }\n"
        "  public int capacity() { return 0; }\n"
        "}\n"
    )
    (source / "Main.java").write_text(
        "package fixture;\n"
        "public class Main {\n"
        "  private final int value;\n"
        "  Main() {\n"
        "    this(1);\n"
        "  }\n"
        "  Main(int x) {\n"
        "    super();\n"
        "    this.value = x;\n"
        "  }\n"
        "  void start(Sized sized, Runnable task, Box box) throws Exception {\n"
        "    sized.size();\n"
        "    task.run();\n"
        "    box.size();\n"
        "    this.helper();\n"
        "    helper();\n"
        '    java.lang.reflect.Method method = Main.class.getMethod("helper");\n'
        "    method.invoke(this);\n"
        "    Main other = new Main(2);\n"
        "    System.out.println(other.value);\n"
        "  }\n"
        "  void helper() {}\n"
        "}\n"
    )

    rows = run_java(
        "fixture",
        tmp_path / "repo",
        source,
        tmp_path / "out" / "java.jsonl",
        tmp_path / "env",
    )
    sites = {(row["file"], row["line"], row["call_name"]): row for row in rows}
    main = "src/fixture/Main.java"

    interface_call = sites[(main, 12, "size")]
    assert interface_call["call_class"] == "imported"
    assert (
        interface_call["ground_truth"] == "src/fixture/Sized.java::fixture.Sized.size()"
    )

    function_value = sites[(main, 13, "run")]
    assert function_value["call_class"] == "higher_order"
    assert function_value["ground_truth"] == "unknown"

    concrete_call = sites[(main, 14, "size")]
    assert concrete_call["call_class"] == "imported"
    assert concrete_call["ground_truth"] == "src/fixture/Box.java::fixture.Box.size()"

    receiver_call = sites[(main, 15, "helper")]
    assert receiver_call["call_class"] == "member"
    assert receiver_call["ground_truth"] == f"{main}::fixture.Main.helper()"

    local_call = sites[(main, 16, "helper")]
    assert local_call["call_class"] == "same_file"
    assert local_call["ground_truth"] == f"{main}::fixture.Main.helper()"

    reflection = sites[(main, 18, "invoke")]
    assert reflection["call_class"] == "dynamic"
    assert reflection["ground_truth"] == "unknown"

    assert sites[(main, 17, "getMethod")]["ground_truth"] == "external"

    this_call = sites[(main, 5, "this")]
    assert this_call["call_class"] == "constructor"
    assert this_call["ground_truth"] == f"{main}::fixture.Main.<init>(int)"

    super_call = sites[(main, 8, "super")]
    assert super_call["call_class"] == "constructor"
    assert super_call["ground_truth"] == "external"

    new_call = sites[(main, 19, "Main")]
    assert new_call["call_class"] == "constructor"
    assert new_call["ground_truth"] == f"{main}::fixture.Main.<init>(int)"


def test_pipeline_maps_a_resolved_target_typed_new_to_a_constructor() -> None:
    """Map the one record a file with non-call expressions still produces.

    That `nameof`, `typeof`, `sizeof` and `default` produce no record at all is
    checked by the opt-in live Roslyn test; the pipeline side of a target-typed
    `new` whose constructor resolves is checked here, without dotnet.
    """
    rows = export_tool_output(
        [
            {
                "file": "src/Derived.cs",
                "line": 17,
                "call_name": "Derived",
                "call_class": "constructor",
                "target": "src/Derived.cs::Fx.Derived.Derived()",
                "target_kind": "project",
                "caller": "src/Derived.cs::Fx.Derived.Go",
                "module": "src",
                "target_module": "src",
                "truth_source": "roslyn:test-double",
            }
        ],
        repo="dev-a",
        language="csharp",
    )

    assert rows[0]["call_class"] == "constructor"
    assert rows[0]["call_name"] == "Derived"
    assert rows[0]["ground_truth"] == "src/Derived.cs::Fx.Derived.Derived()"


@pytest.mark.skipif(
    os.environ.get("VARDE_BENCH_LIVE_DOTNET") != "1",
    reason="set VARDE_BENCH_LIVE_DOTNET=1 to run the real Roslyn runner "
    "(it restores packages and builds the runner)",
)
def test_csharp_exporter_skips_non_call_expressions(tmp_path) -> None:
    source = tmp_path / "repo" / "src" / "fixture"
    source.mkdir(parents=True)
    (source / "Derived.cs").write_text(
        "namespace Fx;\n"
        "public class Base\n"
        "{\n"
        "    public Base(int x) { }\n"
        "    public virtual void Run() { }\n"
        "}\n"
        "public class Derived : Base\n"
        "{\n"
        "    public Derived() : base(1) { }\n"
        "    public Derived(int y) : this() { }\n"
        "    public void Go()\n"
        "    {\n"
        "        var name = nameof(Go);\n"
        "        var type = typeof(Derived);\n"
        "        var size = sizeof(int);\n"
        "        var d = default(int);\n"
        "        Derived other = new();\n"
        "        Run();\n"
        "        other.Run();\n"
        "        System.Reflection.MethodInfo info = null!;\n"
        "        info.Invoke(null, null);\n"
        "        System.Console.WriteLine(name + type.Name + size + d);\n"
        "    }\n"
        "}\n"
    )

    rows = run_csharp(
        "fixture",
        tmp_path / "repo",
        source,
        tmp_path / "out" / "csharp.jsonl",
        tmp_path / "env",
    )
    by_line = {row["line"]: row for row in rows}

    assert "nameof" not in {row["call_name"] for row in rows}
    assert by_line[17]["call_name"] == "Derived"
    assert by_line[17]["call_class"] == "constructor"
    assert by_line[18]["call_class"] == "same_file"
    assert by_line[19]["call_class"] == "member"
    assert by_line[19]["ground_truth"] == "src/fixture/Derived.cs::Fx.Base.Run()"
    assert by_line[21]["call_class"] == "dynamic"
    assert by_line[21]["ground_truth"] == "unknown"


def test_record_cache_is_invalidated_by_exporter_changes(tmp_path) -> None:
    output = tmp_path / "records" / "java-repo.jsonl"
    output.parent.mkdir()
    output.write_text("{}\n")

    assert not _records_current(output, "java")

    output.with_suffix(".stamp").write_text("stale\n")
    assert not _records_current(output, "java")

    output.with_suffix(".stamp").write_text(exporter_digest("java") + "\n")
    assert _records_current(output, "java")
    assert exporter_digest("java") != exporter_digest("csharp")


def test_dotnet_root_uses_the_environment_and_rejects_a_missing_host(tmp_path) -> None:
    root = tmp_path / "libexec"
    (root / "packs").mkdir(parents=True)

    assert _dotnet_root({"DOTNET_ROOT": str(root)}) == str(root.resolve())

    with pytest.raises(RuntimeError, match="not available"):
        _dotnet_root({"PATH": ""})


def test_framework_references_link_only_non_core_sdk_packs(
    tmp_path, monkeypatch
) -> None:
    packs = tmp_path / "dotnet" / "packs"
    aspnet = packs / "Microsoft.AspNetCore.App.Ref" / "10.0.12" / "ref" / "net10.0"
    core = packs / "Microsoft.NETCore.App.Ref" / "10.0.12" / "ref" / "net10.0"
    aspnet.mkdir(parents=True)
    core.mkdir(parents=True)
    (aspnet / "Microsoft.AspNetCore.Http.dll").write_bytes(b"")
    (core / "System.Runtime.dll").write_bytes(b"")
    output = tmp_path / "references"
    output.mkdir()
    monkeypatch.setenv("DOTNET_ROOT", str(tmp_path / "dotnet"))

    _link_framework_references(tmp_path / "env", output, set())
    assert sorted(path.name for path in output.iterdir()) == [
        "Microsoft.AspNetCore.Http.dll"
    ]

    skipped = tmp_path / "skipped"
    skipped.mkdir()
    _link_framework_references(tmp_path / "env", skipped, {"Microsoft.AspNetCore.Http"})
    assert list(skipped.iterdir()) == []


def test_props_files_follow_imports_into_out_of_cone_files(tmp_path) -> None:
    repo = tmp_path / "repo"
    project = repo / "src" / "App"
    (repo / "build").mkdir(parents=True)
    project.mkdir(parents=True)
    (repo / "Directory.Build.props").write_text(
        "<Project>"
        '<Import Project="build/Common.props" />'
        '<Import Project="$(MSBuildToolsPath)/Other.props" />'
        "</Project>"
    )
    (repo / "build" / "Common.props").write_text(
        "<Project><PropertyGroup>"
        "<ImplicitUsings>enable</ImplicitUsings>"
        "</PropertyGroup></Project>"
    )

    properties = _msbuild_properties(repo, project, tmp_path / "env")

    assert properties["implicitusings"] == "enable"


def test_props_files_read_targets_files_and_engineering_listing(tmp_path) -> None:
    repo = tmp_path / "repo"
    project = repo / "src" / "App"
    (repo / "build").mkdir(parents=True)
    project.mkdir(parents=True)
    (repo / "Directory.Build.props").write_text(
        '<Project><Import Project="build/Common.targets" /></Project>'
    )
    (repo / "Directory.Build.targets").write_text(
        "<Project><PropertyGroup><Nullable>enable</Nullable></PropertyGroup></Project>"
    )
    (repo / "build" / "Common.targets").write_text(
        "<Project><PropertyGroup><LangVersion>latest</LangVersion></PropertyGroup></Project>"
    )
    _commit_out_of_cone_file(
        repo,
        "eng/targets/CSharp.Common.targets",
        "<Project><PropertyGroup><ImplicitUsings>enable</ImplicitUsings>"
        "</PropertyGroup></Project>",
    )

    properties = _msbuild_properties(repo, project, tmp_path / "env")

    assert properties["implicitusings"] == "enable"
    assert properties["nullable"] == "enable"
    assert properties["langversion"] == "latest"


def _commit_out_of_cone_file(repo: Path, name: str, text: str) -> None:
    """Commit a file the checkout does not materialize, as a pin would hold it."""
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    path.unlink()


def test_global_usings_file_writes_implicit_and_declared_usings(
    tmp_path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    project = repo / "src" / "App"
    project.mkdir(parents=True)
    (repo / "Directory.Build.props").write_text(
        "<Project><PropertyGroup>"
        "<ImplicitUsings>enable</ImplicitUsings>"
        "</PropertyGroup><ItemGroup>"
        '<Using Include="OrchardCore.Modules" />'
        '<Using Include="System.Console" Static="true" />'
        "</ItemGroup></Project>"
    )
    (project / "App.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"></Project>')
    sdk = tmp_path / "dotnet"
    (sdk / "packs").mkdir(parents=True)
    (sdk / "sdk" / "10.0.401" / "Sdks" / "Microsoft.NET.Sdk").mkdir(parents=True)
    (
        sdk / "sdk" / "10.0.401" / "Sdks" / "Microsoft.NET.Sdk" / "Implicit.props"
    ).write_text('<Project><ItemGroup><Using Include="System" /></ItemGroup></Project>')
    monkeypatch.setenv("DOTNET_ROOT", str(sdk))

    path = _global_usings_file(repo, project, tmp_path / "env")

    assert path is not None
    assert sorted(path.read_text().splitlines()) == [
        "global using OrchardCore.Modules;",
        "global using System;",
        "global using static System.Console;",
    ]

    (repo / "Directory.Build.props").write_text("<Project></Project>")
    assert _global_usings_file(repo, project, tmp_path / "env") is None


def test_package_versions_resolve_central_and_property_versions(tmp_path) -> None:
    repo = tmp_path / "repo"
    project = repo / "src" / "App"
    project.mkdir(parents=True)
    (repo / "Directory.Build.props").write_text(
        "<Project><PropertyGroup><XunitVersion>2.9.2</XunitVersion>"
        "</PropertyGroup></Project>"
    )
    (repo / "Directory.Packages.props").write_text(
        "<Project><ItemGroup>"
        '<PackageVersion Include="Xunit.Assert" Version="$(xunitassertversion)" />'
        '<PackageVersion Include="Moq" Version="4.20.72" />'
        "</ItemGroup></Project>"
    )
    (repo / "src" / "Directory.Build.props").write_text(
        "<Project><PropertyGroup>"
        "<XunitAssertVersion>$(XunitVersion)</XunitAssertVersion>"
        "</PropertyGroup></Project>"
    )
    (project / "App.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup>'
        '<PackageReference Include="Xunit.Assert" />'
        '<PackageReference Include="Serilog" Version="3.1.1" />'
        '<PackageReference Include="Broken" Version="$(MissingProperty)" />'
        "</ItemGroup></Project>"
    )

    versions = _package_versions(repo, project, tmp_path / "env")

    assert versions == {"Xunit.Assert": "2.9.2", "Serilog": "3.1.1"}


def test_unusable_packages_reads_nuget_error_ids() -> None:
    message = (
        "error NU1101: Unable to find package Xunit.Assert. No packages exist "
        "with this id in source(s): nuget.org\n"
        "error NU1202: Package Moq 4.20.72 is not compatible with net10.0.\n"
        "error MSB1009: Project file does not exist.\n"
    )

    assert _unusable_packages(message) == {"Xunit.Assert", "Moq"}
