import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from varde_dev.calibrate.cli import main
from varde_dev.calibrate.profile.commands import main as profile_main


def _write_jsonl(path: Path, record_type: str, records: list[dict]) -> None:
    path.write_text(
        json.dumps({"record_type": record_type, "schema_version": 1})
        + "\n"
        + "".join(
            json.dumps({"schema_version": 1, **record}) + "\n" for record in records
        ),
        encoding="utf-8",
    )


def test_profile_command_writes_versioned_profile_with_input_hashes(tmp_path):
    dataset = tmp_path / "dataset"
    (dataset / "labels").mkdir(parents=True)
    (dataset / "manifest.toml").write_text(
        'label_batches = [{ id = "batch-1" }]\n', encoding="utf-8"
    )
    items = [
        {"id": "a", "pair_group_id": "g"},
        {"id": "b", "pair_group_id": "g"},
    ]
    _write_jsonl(dataset / "items.jsonl", "items", items)
    _write_jsonl(
        dataset / "units.jsonl",
        "units",
        [{"id": "u", "kind": "pair", "item_ids": ["a", "b"], "pair_group_id": "g"}],
    )
    _write_jsonl(
        dataset / "labels" / "batch-1.jsonl",
        "labels",
        [
            {
                "rater_id": "person",
                "unit_id": "u",
                "choice": "B",
                "order_shown": ["b", "a"],
            }
        ],
    )
    components = tmp_path / "components.jsonl"
    components.write_text(
        '{"item_id":"a","components":{"size":0}}\n'
        '{"item_id":"b","components":{"size":1}}\n',
        encoding="utf-8",
    )

    assert (
        main(
            [
                "profile",
                str(dataset),
                "--rater",
                "person",
                "--components",
                str(components),
            ]
        )
        == 0
    )
    profile = json.loads((dataset / "profile.json").read_text(encoding="utf-8"))
    assert profile["schema_version"] == 1
    assert profile["rater_id"] == "person"
    assert set(profile) == {
        "schema_version",
        "rater_id",
        "components",
        "weights",
        "constant_components",
        "under_determined",
        "under_determined_components",
        "held_out_pair_accuracy",
        "dislikes_most",
        "input_hashes",
        "fit_settings",
    }
    assert set(profile["weights"]["size"]) == {
        "weight",
        "standard_error",
        "interval_95",
        "mean",
        "scale",
    }
    assert profile["weights"]["size"]["weight"] < 0
    assert len(profile["input_hashes"]["labels_sha256"]) == 64
    label_records = [
        json.loads(line)
        for line in (dataset / "labels" / "batch-1.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[1:]
    ]
    label_payload = "\n".join(
        json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        for record in sorted(
            label_records,
            key=lambda record: json.dumps(
                record, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ),
        )
    ).encode("utf-8")
    assert (
        profile["input_hashes"]["labels_sha256"]
        == hashlib.sha256(label_payload).hexdigest()
    )
    assert (
        profile["input_hashes"]["components_sha256"]
        == hashlib.sha256(components.read_bytes()).hexdigest()
    )
    assert profile["fit_settings"]["l2_strength"] == 1.0
    assert set(profile["dislikes_most"]) == {"by_group", "predicted_worst_pairs"}


def test_scorer_builds_same_profile_components_as_override(tmp_path):
    dataset, components = _dataset_and_components(tmp_path)
    scorer = _fake_scorer(tmp_path)
    result = main(
        [
            "profile",
            str(dataset),
            "--rater",
            "person",
            "--scorer",
            f"{scorer} --facts {{facts}} --calibration {{calibration}} --json",
            "--calibration",
            str(_placeholder_calibration()),
        ]
    )
    assert result == 0
    scored_profile = json.loads((dataset / "profile.json").read_text(encoding="utf-8"))

    assert (
        main(
            [
                "profile",
                str(dataset),
                "--rater",
                "person",
                "--components",
                str(components),
            ]
        )
        == 0
    )
    override_profile = json.loads(
        (dataset / "profile.json").read_text(encoding="utf-8")
    )
    assert scored_profile["weights"] == override_profile["weights"]
    assert scored_profile["components"] == override_profile["components"]


def test_scorer_failure_names_item_and_exits_nonzero(tmp_path, capsys):
    dataset, _ = _dataset_and_components(tmp_path)
    scorer = tmp_path / "bad-scorer"
    scorer.write_text(
        (
            "#!/usr/bin/env python3\nimport sys\n"
            "print('item broke', file=sys.stderr)\nsys.exit(3)\n"
        ),
        encoding="utf-8",
    )
    scorer.chmod(0o755)
    assert (
        main(
            [
                "profile",
                str(dataset),
                "--rater",
                "person",
                "--scorer",
                f"{scorer} --facts {{facts}} --calibration {{calibration}} --json",
                "--calibration",
                str(_placeholder_calibration()),
            ]
        )
        == 1
    )
    assert "item a" in capsys.readouterr().err


def test_components_override_takes_precedence_over_scorer(tmp_path):
    dataset, components = _dataset_and_components(tmp_path)
    scorer = tmp_path / "bad-scorer"
    scorer.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    scorer.chmod(0o755)
    assert (
        main(
            [
                "profile",
                str(dataset),
                "--rater",
                "person",
                "--components",
                str(components),
                "--scorer",
                f"{scorer} --facts {{facts}} --calibration {{calibration}} --json",
                "--calibration",
                str(_placeholder_calibration()),
            ]
        )
        == 0
    )


def _dataset_and_components(tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "dataset"
    (dataset / "labels").mkdir(parents=True)
    (dataset / "manifest.toml").write_text(
        'label_batches = [{ id = "batch-1" }]\n', encoding="utf-8"
    )
    _write_jsonl(
        dataset / "items.jsonl",
        "items",
        [
            {"id": "a", "pair_group_id": "g", "facts_path": "a.jsonl"},
            {"id": "b", "pair_group_id": "g", "facts_path": "b.jsonl"},
        ],
    )
    _write_jsonl(
        dataset / "units.jsonl",
        "units",
        [{"id": "u", "kind": "pair", "item_ids": ["a", "b"], "pair_group_id": "g"}],
    )
    _write_jsonl(
        dataset / "labels" / "batch-1.jsonl",
        "labels",
        [
            {
                "rater_id": "person",
                "unit_id": "u",
                "choice": "A",
                "order_shown": ["a", "b"],
            }
        ],
    )
    components = tmp_path / "components.jsonl"
    components.write_text(
        '{"item_id":"a","components":{"cognitive":1,"size":0}}\n'
        '{"item_id":"b","components":{"cognitive":3,"size":1}}\n',
        encoding="utf-8",
    )
    for item_id in ("a", "b"):
        (dataset / f"{item_id}.jsonl").write_text(
            json.dumps(_facts_record(f"src/{item_id}.py")) + "\n", encoding="utf-8"
        )
    return dataset, components


def _fake_scorer(tmp_path: Path) -> Path:
    scorer = tmp_path / "fake-scorer"
    scorer.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\n"
        "item='a' if '/a.' in sys.argv[sys.argv.index('--facts')+1] else 'b'\n"
        "debt={'a':1,'b':3}[item]\n"
        "print(json.dumps({'breakdown':[{'name':'cognitive','debt':debt},{'name':'size','debt':{'a':0,'b':1}[item]}]}))\n",
        encoding="utf-8",
    )
    scorer.chmod(0o755)
    return scorer


def _placeholder_calibration() -> Path:
    return (
        Path(__file__).parents[4]
        / "dev/tests/calibrate/profile/fixtures/placeholder.toml"
    )


def _facts_record(path: str) -> dict[str, object]:
    return {
        "contract": "facts-2",
        "path": path,
        "language": "python",
        "module": "src",
        "tokens": 1000,
        "structure_confidence": "normal",
        "functions": [
            {
                "id": f"{path}::f",
                "line": 1,
                "tokens": 50,
                "cognitive": 80,
                "params": 1,
                "depth": 1,
                "fan_out": 1,
                "tree_size": 1,
                "name_issues": ["vague"],
                "fragment_scope": None,
            }
        ],
    }


def test_real_varde_score_cli_components_feed_profile(tmp_path):
    dataset, _ = _dataset_and_components(tmp_path)
    calibration = _placeholder_calibration()
    scorer = _real_score_launcher(tmp_path)
    scored = subprocess.run(  # noqa: S603 - Test executes the calibration CLI with controlled fixture arguments.
        [
            sys.executable,
            str(scorer),
            "--facts",
            str(dataset / "a.jsonl"),
            "--calibration",
            str(calibration),
            "--debug",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert scored.returncode == 0, scored.stderr
    expected = {
        part["name"]: part["debt"] for part in json.loads(scored.stdout)["breakdown"]
    }

    assert (
        main(
            [
                "profile",
                str(dataset),
                "--rater",
                "person",
                "--calibration",
                str(calibration),
                "--scorer",
                (
                    f"{sys.executable} {scorer} --facts {{facts}} "
                    "--calibration {calibration} --debug"
                ),
            ]
        )
        == 0
    )
    profile = json.loads((dataset / "profile.json").read_text(encoding="utf-8"))
    assert profile["components"] == sorted(expected)
    assert all(
        abs(profile["weights"][name]["mean"] - value) < 1e-9
        for name, value in expected.items()
    )


def _real_score_launcher(tmp_path: Path) -> Path:
    launcher = tmp_path / "real-varde-code-score"
    launcher.write_text(
        "from varde_code.module import register\n"
        "import sys\n"
        "sys.exit(register().run(['score', *sys.argv[1:]]))\n",
        encoding="utf-8",
    )
    return launcher


def test_scorer_help_mentions_debug(capsys):
    with pytest.raises(SystemExit):
        profile_main(["--help"])
    assert "--debug" in capsys.readouterr().out
