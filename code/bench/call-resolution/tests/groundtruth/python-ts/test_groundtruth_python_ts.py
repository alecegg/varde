from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
from audit.records import CALL_CLASSES, validate_record

_MODULE_PATH = (
    Path(__file__).parents[3] / "groundtruth" / "python-ts" / "gt_python_ts.py"
)
_SPEC = importlib.util.spec_from_file_location("gt_python_ts", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
export_repository = _MODULE.export_repository
review_stub = _MODULE.review_stub
sample_records = _MODULE.sample_records
stratified_samples = _MODULE.stratified_samples
verify_test_manifest = _MODULE.verify_test_manifest
write_test_manifest = _MODULE.write_test_manifest


def test_fake_runner_preserves_concrete_implementation_and_dynamic_unknown():
    repo = {"repo": "example/project"}

    def fake_runner(_repo: dict[str, str]) -> list[dict[str, object]]:
        return [
            {
                "file": "src/child.py",
                "line": 12,
                "call_name": "run",
                "call_class": "member",
                "target_id": "src/child.py::Child.run@30",
                "target_module": "src.child",
                "truth_source": "jedi",
                "function_id": "src/child.py::caller@10",
                "module": "src.child",
            },
            {
                "file": "src/child.py",
                "line": 13,
                "call_name": "resolve",
                "call_class": "dynamic",
                "target_id": None,
                "target_module": None,
                "truth_source": "jedi:unresolved-dynamic",
                "function_id": "src/child.py::caller@10",
                "module": "src.child",
            },
        ]

    records = export_repository(repo, "python", fake_runner)

    assert records[0]["ground_truth"] == "src/child.py::Child.run@30"
    assert records[0]["call_name"] == "run"
    assert records[0]["ground_truth_module"] == "src.child"
    assert records[1]["ground_truth"] == "unknown"
    assert records[1]["call_class"] == "dynamic"
    assert records[1]["truth_source"] == "jedi:unresolved-dynamic"
    for record in records:
        validate_record(record)


def test_review_stub_keeps_two_independent_unfilled_reviews():
    stub = review_stub(
        {
            "repo": "example/project",
            "language": "typescript",
            "file": "src/app.ts",
            "line": 5,
            "call_name": "resolve",
            "call_class": "higher_order",
            "ground_truth": "unknown",
        }
    )

    assert stub["reviewer_1"]["target"] is None
    assert stub["reviewer_2"]["target"] is None
    assert stub["reviewer_1"] != stub["reviewer_2"]
    assert stub["call_class"] == "higher_order"


def test_sample_records_stratifies_and_keeps_repository_sets_disjoint():
    sites = []
    for repo_index in range(5):
        for call_class in sorted(CALL_CLASSES):
            sites.extend(
                {
                    "repo": f"example/repo-{repo_index}",
                    "language": "python",
                    "file": f"src/{repo_index}.py",
                    "line": ordinal + 1,
                    "call_class": call_class,
                    "ground_truth": "unknown",
                    "measured_edge": None,
                    "measured_status": "unresolved",
                    "truth_source": "fixture",
                    "function_id": None,
                    "module": None,
                }
                for ordinal in range(2)
            )

    sample = sample_records(sites, seed=166, n_per_language=12)["python"]

    dev_repos = {record["repo"] for record in sample["dev"]}
    test_repos = {record["repo"] for record in sample["test"]}
    assert dev_repos.isdisjoint(test_repos)
    assert len(sample["dev"]) == len(sample["test"]) == 12
    assert {record["call_class"] for record in sample["dev"]} == CALL_CLASSES
    assert {record["call_class"] for record in sample["test"]} == CALL_CLASSES


def _fixture_sites(per_class: int, counts: dict[str, int] | None = None):
    counts = counts or {}
    sites = []
    for repo_index in range(6):
        for call_class in sorted(CALL_CLASSES):
            sites.extend(
                {
                    "repo": f"example/repo-{repo_index}",
                    "language": "python",
                    "file": f"src/{repo_index}.py",
                    "line": ordinal + 1,
                    "call_name": f"{call_class}_{ordinal}",
                    "call_class": call_class,
                    "ground_truth": "unknown",
                    "measured_edge": None,
                    "measured_status": "unresolved",
                    "truth_source": "fixture",
                    "function_id": None,
                    "module": None,
                }
                for ordinal in range(counts.get(call_class, per_class))
            )
    return sites


def test_stratified_samples_balance_repositories_and_deduplicate_sites():
    sites = _fixture_sites(per_class=10)
    sites.append(dict(sites[0]))

    samples, notes = stratified_samples(sites, seed=7, n_per_language=60)

    for split in ("dev", "test"):
        records = samples["python"][split]
        identities = {
            (r["repo"], r["file"], r["line"], r["call_name"]) for r in records
        }
        assert len(records) == 60
        assert len(identities) == 60
        assert {r["call_class"] for r in records} == CALL_CLASSES
        composition = notes["python"][split]
        assert composition["shortfalls"] == {}
        assert composition["test_path_sites"] == 0
        assert max(composition["repo_counts"].values()) <= 24


def test_stratified_samples_report_shortfall_without_padding():
    sites = _fixture_sites(per_class=10, counts={"member": 1})

    samples, notes = stratified_samples(sites, seed=7, n_per_language=60)

    records = samples["python"]["test"]
    assert len(records) == 60
    assert notes["python"]["test"]["shortfalls"] == {"member": 3}


def test_test_manifest_verifies_external_files_by_hash_only(tmp_path: Path):
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    python_file = frozen / "python.jsonl"
    typescript_file = frozen / "typescript.jsonl"
    python_file.write_bytes(b'{"language":"python"}\n')
    typescript_file.write_bytes(b'{"language":"typescript"}\n')
    manifest_path = tmp_path / "manifest.json"

    write_test_manifest(
        manifest_path,
        frozen,
        {"python": python_file, "typescript": typescript_file},
    )

    manifest = json.loads(manifest_path.read_text())
    assert (
        manifest["files"]["python"]["file"]
        == "notes/restricted/call-audit/python-ts/python.jsonl"
    )
    assert (
        manifest["files"]["python"]["sha256"]
        == hashlib.sha256(python_file.read_bytes()).hexdigest()
    )
    assert verify_test_manifest(manifest_path, frozen)
    typescript_file.write_bytes(b"changed\n")
    assert not verify_test_manifest(manifest_path, frozen)


def test_python_worker_resolves_scoped_and_higher_order_calls(tmp_path: Path):
    import subprocess

    harness = Path(__file__).parents[3]
    python = harness / "envs/python-ts/.py/bin/python"
    if not python.is_file():
        pytest.skip(f"isolated Jedi environment is missing: {python}")
    root = tmp_path / "python"
    source = root / "src"
    source.mkdir(parents=True)
    (source / "helper.py").write_text("def imported_target(): pass\n")
    main = source / "main.py"
    main.write_text(
        "from helper import imported_target\n"
        "class Box:\n    def __init__(self): pass\n    def method(self): pass\n"
        "def shadow_target(): pass\n"
        "def local_target(): pass\n"
        "def make(): return nested_target\n"
        "def caller():\n"
        "    shadow_target = local_target\n"
        "    shadow_target()\n"
        "    imported_target()\n"
        "    def outer():\n"
        "        def nested_target(): pass\n"
        "        def nested_caller(): nested_target()\n"
        "        nested_caller()\n"
        "    outer()\n"
        "    Box()\n"
        "    make()()\n"
        "    box = Box()\n"
        "    box.method()\n"
    )
    result = subprocess.run(  # noqa: S603 - Runs the Python ground-truth worker to test its command-line contract.
        [
            str(python),
            str(harness / "groundtruth/python-ts/python_worker.py"),
            str(root),
            '["src"]',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    sites = json.loads(result.stdout)
    by_line = {site["line"]: site for site in sites if site["file"] == "src/main.py"}
    expected = {
        10: "src/main.py::local_target@6",
        11: "src/helper.py::imported_target@1",
        14: "src/main.py::nested_target@13",
        17: "src/main.py::Box.__init__@3",
        18: "src/main.py::make@7",
        20: "src/main.py::method@4",
    }
    for line, target in expected.items():
        assert by_line[line]["target_id"] == target
        assert by_line[line]["call_name"]
    assert by_line[10]["call_class"] == "higher_order"
    assert any(
        site["line"] == 18
        and site["call_class"] == "higher_order"
        and site["target_id"] == "src/main.py::make@7"
        for site in sites
    )
    assert by_line[20]["call_name"] == "method"


def test_typescript_worker_resolves_scoped_and_higher_order_calls(tmp_path: Path):
    import subprocess

    harness = Path(__file__).parents[3]
    root = tmp_path / "typescript"
    source = root / "src"
    source.mkdir(parents=True)
    (source / "helper.ts").write_text("export function importedTarget() {}\n")
    main = source / "main.ts"
    main.write_text(
        "import { importedTarget } from './helper';\n"
        "class Box { constructor() {} method() {} }\n"
        "function shadowTarget() {}\n"
        "function localTarget() {}\n"
        "function nestedTarget() {}\n"
        "function make() { return nestedTarget; }\n"
        "function caller() {\n"
        "  const shadowTarget = localTarget;\n"
        "  shadowTarget();\n"
        "  importedTarget();\n"
        "  function outer() {\n"
        "    function nestedTarget() {}\n"
        "    function nestedCaller() { nestedTarget(); }\n"
        "    nestedCaller();\n"
        "  }\n"
        "  outer();\n"
        "  new Box();\n"
        "  make()();\n"
        "  const box = new Box();\n"
        "  box.method();\n"
        "}\n"
    )
    node = shutil.which("node")
    module = harness / "envs/python-ts/.npm/node_modules/typescript/lib/typescript.js"
    if node is None or not module.is_file():
        pytest.skip("node or the pinned TypeScript compiler module is missing")
    result = subprocess.run(  # noqa: S603 - Runs the TypeScript ground-truth worker to test its output.
        [
            node,
            str(harness / "groundtruth/python-ts/typescript_worker.cjs"),
            str(root),
            str(module),
            '["src"]',
            '[".ts"]',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    sites = json.loads(result.stdout)
    by_line = {site["line"]: site for site in sites if site["file"] == "src/main.ts"}
    expected = {
        9: "src/main.ts::localTarget@4",
        10: "src/helper.ts::importedTarget@1",
        13: "src/main.ts::nestedTarget@12",
        14: "src/main.ts::nestedCaller@13",
        17: "src/main.ts::Box.constructor@2",
        18: "src/main.ts::nestedTarget@5",
        20: "src/main.ts::method@2",
    }
    for line, target in expected.items():
        assert by_line[line]["target_id"] == target
        assert by_line[line]["call_name"]
    assert any(
        site["line"] == 18
        and site["call_class"] == "higher_order"
        and site["target_id"] == "src/main.ts::nestedTarget@5"
        for site in sites
    )
    assert by_line[20]["call_name"] == "method"
