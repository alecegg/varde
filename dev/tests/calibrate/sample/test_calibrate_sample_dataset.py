import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest
from varde_dev.calibrate.cli import main as calibrate_main
from varde_dev.calibrate.reports.dataset import read_dataset_files
from varde_dev.calibrate.sample import dataset_dir

REPO_ROOT = Path(__file__).resolve().parents[4]
SAMPLE = dataset_dir()


def _pair_manifests():
    return [
        (directory, (directory / "manifest.toml").read_text(encoding="utf-8"))
        for directory in sorted(SAMPLE.iterdir())
        if directory.is_dir()
    ]


def _toml(directory):
    import tomllib

    with (directory / "manifest.toml").open("rb") as stream:
        return tomllib.load(stream)


def _node_supports_typescript():
    node = shutil.which("node")
    if node is None:
        return False
    result = subprocess.run(
        [node, "--help"], text=True, capture_output=True, check=False
    )
    return result.returncode == 0 and "--experimental-strip-types" in result.stdout


def test_sample_pairs_import_with_behavior_and_three_item_groups(tmp_path, monkeypatch):
    pairs = [directory for directory, _ in _pair_manifests()]
    assert len(pairs) == 9
    dataset = tmp_path / "dataset"
    assert calibrate_main(["init", str(dataset)]) == 0
    assert calibrate_main(["import", str(dataset), "--sample"]) == 0
    _assert_imported_group_contract(dataset, pairs)
    _run_python_behaviors(pairs)
    monkeypatch.setattr(
        "builtins.input", lambda _prompt: (_ for _ in ()).throw(EOFError)
    )
    assert (
        calibrate_main(
            [
                "duel",
                str(dataset),
                "--group",
                "sample-python-price-order",
                "--session",
                "distinct",
            ]
        )
        == 0
    )
    session = json.loads(
        (dataset / "sessions/duel-distinct.json").read_text(encoding="utf-8")
    )
    pending = session["pending"]
    item_text = {
        item["id"]: item["text"] for item in read_dataset_files(dataset)["items"]
    }
    assert pending["x"] != pending["y"]
    assert item_text[pending["x"]] != item_text[pending["y"]]


@pytest.mark.skipif(shutil.which("dotnet") is None, reason="dotnet SDK is unavailable")
def test_sample_csharp_behaviors(tmp_path):
    _run_csharp_behaviors(tmp_path, [directory for directory, _ in _pair_manifests()])


@pytest.mark.skipif(
    not _node_supports_typescript(), reason="Node lacks --experimental-strip-types"
)
def test_sample_typescript_behaviors(tmp_path):
    _run_typescript_behaviors(
        tmp_path, [directory for directory, _ in _pair_manifests()]
    )


def _assert_imported_group_contract(dataset, pairs):
    data = read_dataset_files(dataset)
    groups = {}
    for pair_dir in pairs:
        manifest = _toml(pair_dir)
        groups.setdefault(manifest["pair_group_id"], set()).update(
            (manifest["id"] + ":a", manifest["id"] + ":b")
        )
        assert manifest["license"] == "MIT"
        for role, name in (
            ("a", manifest["left"]),
            ("b", manifest["right"]),
            ("behaviour_test", manifest["behaviour_test"]),
        ):
            expected_hash = manifest["sha256"][role]
            assert (
                hashlib.sha256((pair_dir / name).read_bytes()).hexdigest()
                == expected_hash
            )
            assert (pair_dir / name).is_file()
    assert all(len(item_ids) == 6 for item_ids in groups.values())
    assert len(groups) == 3
    assert {item["pair_group_id"] for item in data["items"]} == set(groups)
    assert all(item["license"] == "MIT" for item in data["items"])
    assert all(unit["pair_group_id"] in groups for unit in data["units"])
    for group in groups:
        texts = [
            item["text"] for item in data["items"] if item["pair_group_id"] == group
        ]
        assert len(texts) == 6
        assert len(set(texts)) == 6
    assert all(
        len({item["text"] for item in data["items"] if item["pair_group_id"] == group})
        == 6
        for group in groups
    )


def _run_python_behaviors(pairs):
    python_pairs = [pair for pair in pairs if _toml(pair)["language"] == "python"]
    for pair in python_pairs:
        manifest = _toml(pair)
        for side in (manifest["left"], manifest["right"]):
            namespace = runpy.run_path(pair / side)
            runpy.run_path(
                pair / manifest["behaviour_test"],
                init_globals={"price_order": namespace["price_order"]},
            )


def _run_csharp_behaviors(tmp_path, pairs):
    csharp_pairs = [pair for pair in pairs if _toml(pair)["language"] == "csharp"]
    harness = tmp_path / "csharp-behavior"
    harness.mkdir()
    (harness / "Harness.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        "<OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework>"
        "<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>"
        "</PropertyGroup></Project>\n",
        encoding="utf-8",
    )
    test_source = (csharp_pairs[0] / "behaviour_test.cs").read_text()
    for source in _unique_sources(csharp_pairs):
        (harness / "Pricing.cs").write_bytes(source)
        (harness / "Program.cs").write_text(test_source, encoding="utf-8")
        _run(
            ["dotnet", "run", "--project", str(harness / "Harness.csproj")],
            harness,
        )


def _run_typescript_behaviors(tmp_path, pairs):
    typescript_pairs = [
        pair for pair in pairs if _toml(pair)["language"] == "typescript"
    ]
    harness = tmp_path / "typescript-behavior"
    harness.mkdir()
    (harness / "package.json").write_text('{"type":"module"}\n')
    test_source = (typescript_pairs[0] / "behaviour_test.ts").read_text()
    for source in _unique_sources(typescript_pairs):
        (harness / "candidate.ts").write_bytes(source)
        (harness / "behaviour_test.ts").write_text(test_source, encoding="utf-8")
        _run(["node", "--experimental-strip-types", "behaviour_test.ts"], harness)


def _unique_sources(pair_dirs):
    seen = set()
    for pair in pair_dirs:
        manifest = _toml(pair)
        for side in (manifest["left"], manifest["right"]):
            source = (pair / side).read_bytes()
            digest = hashlib.sha256(source).digest()
            if digest not in seen:
                seen.add(digest)
                yield source


def _run(command, cwd):
    completed = subprocess.run(
        command, cwd=cwd, text=True, capture_output=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_guide_walkthrough_runs_verbatim_in_isolated_home(tmp_path):
    guide = (REPO_ROOT / "dev/src/varde_dev/calibrate/GUIDE.md").read_text()
    command_block = re.search(r"```sh\n(.*?)\n```", guide, re.DOTALL)
    assert command_block is not None
    environment = os.environ.copy()
    for key in ("VARDE_CALIBRATE_ALLOW_LIVE",):
        environment.pop(key, None)
    for key, folder in (
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "xdg-config"),
        ("VARDE_CONFIG_DIR", "varde-config"),
        ("XDG_DATA_HOME", "xdg-data"),
    ):
        path = tmp_path / folder
        path.mkdir()
        environment[key] = str(path)
    environment["CAL_DATA"] = str(tmp_path / "walkthrough-dataset")

    completed = subprocess.run(
        ["bash", "-euc", command_block.group(1)],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Resuming session walkthrough" in completed.stdout
    assert "Paused." in completed.stdout
    dataset = tmp_path / "walkthrough-dataset"
    assert (dataset / "manifest.toml").is_file()

    data = read_dataset_files(dataset)
    (dataset / "components.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "item_id": item["id"],
                    "components": {
                        "size": len(item["text"]),
                        "cognitive": item["text"].count("if"),
                    },
                }
            )
            + "\n"
            for item in data["items"]
        ),
        encoding="utf-8",
    )
    (dataset / "scores.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "unit_id": unit["id"],
                    "scores": {unit["item_ids"][0]: 1, unit["item_ids"][1]: 0},
                    "calibration_id": "walkthrough-calibration",
                    "formula": "smoke-test",
                    "split": "test",
                }
            )
            + "\n"
            for unit in data["units"]
            if unit["kind"] == "pair"
        ),
        encoding="utf-8",
    )
    (dataset / "lens.md").write_text("Prefer behavior-preserving clarity.\n")
    (dataset / "idiom-notes.md").write_text("Use ordinary language idioms.\n")

    def run_documented(command):
        result = subprocess.run(
            ["bash", "-euc", command],
            cwd=REPO_ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    rank_block = re.search(
        r"```sh\n((?:uv run python -m varde_dev\.calibrate rank.*\n?)+)```",
        guide,
    )
    assert rank_block is not None
    run_documented(rank_block.group(1))

    profile_block = re.search(
        r"```sh\n(uv run python -m varde_dev\.calibrate profile.*?)\n```",
        guide,
        re.DOTALL,
    )
    assert profile_block is not None
    run_documented(profile_block.group(1))
    assert (dataset / "profile.json").is_file()

    validate_block = re.search(
        r"```sh\n(uv run python -m varde_dev\.calibrate validate.*?)\n```",
        guide,
        re.DOTALL,
    )
    assert validate_block is not None
    run_documented(validate_block.group(1))
    assert (dataset / "validation/python.toml").is_file()

    rate_block = re.search(
        r"```sh\n(uv run python -m varde_dev\.calibrate rate.*?)\n```", guide, re.DOTALL
    )
    assert rate_block is not None
    run_documented(rate_block.group(1))
