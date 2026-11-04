"""Command handlers for the calibration dataset store."""

import argparse
import hashlib
import importlib
import shutil
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from varde_dev.calibrate.store import (
    export_split,
    import_dataset,
    init_dataset,
    verify_dataset,
)
from varde_dev.calibrate.store.logic import SPLITS


def _parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"python -m varde_dev.calibrate {command}")
    parser.add_argument("dataset", type=Path)
    if command == "import":
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument(
            "--pairs",
            type=Path,
            help="directory containing exported pair directories",
        )
        source.add_argument(
            "--sample", action="store_true", help="import the built-in sample dataset"
        )
        parser.add_argument(
            "--split",
            choices=SPLITS,
            default="dev",
        )
    if command == "export":
        parser.add_argument("--split", choices=SPLITS, required=True)
        parser.add_argument("--output", type=Path, required=True)
    return parser


def main(command: str, argv: Sequence[str] | None = None) -> int:
    handlers = {
        "init": _handle_init,
        "import": _handle_import,
        "verify": _handle_verify,
        "export": _handle_export,
    }
    handler = handlers.get(command)
    if handler is None:
        raise ValueError(f"unsupported store command: {command}")
    parser = _parser(command)
    args = parser.parse_args(argv)
    try:
        return handler(args)
    except (
        OSError,
        TypeError,
        ValueError,
        tomllib.TOMLDecodeError,
        UnicodeDecodeError,
    ) as error:
        print(f"calibrate {command}: {error}", file=sys.stderr)
        return 1


def _handle_init(args: argparse.Namespace) -> int:
    init_dataset(args.dataset)
    print(f"initialized dataset: {args.dataset}")
    return 0


def _handle_import(args: argparse.Namespace) -> int:
    if args.sample:
        _import_sample_command(args.dataset, args.split)
    else:
        _import_pairs_command(args.dataset, args.pairs, args.split)
    return 0


def _handle_verify(args: argparse.Namespace) -> int:
    return _verify_command(args.dataset)


def _handle_export(args: argparse.Namespace) -> int:
    export_split(args.dataset, args.split, args.output)
    print(f"exported {args.split} split: {args.output}")
    return 0


def _import_pairs_command(dataset: Path, pairs: Path, split: str) -> None:
    _import_directory(dataset, pairs, split)


def _import_sample_command(dataset: Path, split: str) -> None:
    _import_directory(dataset, _sample_directory(), split)


def _import_directory(dataset: Path, source: Path, split: str) -> None:
    items, units, tasks, behaviour_tests = _read_pair_directory(source, split)
    import_dataset(dataset, items=items, units=units, tasks=tasks)
    _copy_behaviour_tests(dataset, behaviour_tests)
    print(f"imported {len(units)} pair(s) from {source}")


def _sample_directory() -> Path:
    module_name = "varde_dev.calibrate.sample"
    try:
        sample_module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        if error.name != module_name:
            raise
        raise ValueError("built-in sample dataset is not installed") from error
    return Path(sample_module.dataset_dir())


def _read_pair_directory(
    source: Path, split: str
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Path],
]:
    if not source.is_dir():
        raise FileNotFoundError(f"pair directory does not exist: {source}")
    pair_dirs = sorted(path for path in source.iterdir() if path.is_dir())
    if not pair_dirs and (source / "manifest.toml").is_file():
        pair_dirs = [source]
    if not pair_dirs:
        raise ValueError(f"no pair directories found in {source}")

    items: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []
    tasks_by_id: dict[str, dict[str, Any]] = {}
    behaviour_tests: dict[str, Path] = {}
    for pair_dir in pair_dirs:
        manifest = _read_pair_manifest(pair_dir)
        pair_id = _pair_id(pair_dir, manifest)
        group_id = _required_manifest_text(manifest, "pair_group_id", pair_id)
        language = _required_manifest_text(manifest, "language", pair_id)
        task_text = _required_manifest_text(manifest, "task", pair_id)
        license_id = _required_manifest_text(manifest, "license", pair_id)
        files = _pair_files(pair_dir, manifest, pair_id)
        _verify_source_hashes(files, manifest, pair_id)
        task = tasks_by_id.setdefault(
            group_id, {"id": group_id, "description": task_text, "behaviour_tests": []}
        )
        if task["description"] != task_text:
            raise ValueError(
                f"inconsistent task descriptions for pair_group_id {group_id}"
            )
        test_path = files["behaviour_test"]
        relative_test_path = _stored_behaviour_test_path(pair_id, test_path.suffix)
        test_hash = hashlib.sha256(test_path.read_bytes()).hexdigest()
        reference = {"path": relative_test_path, "sha256": test_hash}
        if reference not in task["behaviour_tests"]:
            task["behaviour_tests"].append(reference)
        behaviour_tests[relative_test_path] = test_path

        item_ids = [f"{pair_id}:a", f"{pair_id}:b"]
        for item_id, side in zip(item_ids, ("a", "b"), strict=True):
            content = files[side].read_bytes().decode("utf-8")
            items.append(
                {
                    "id": item_id,
                    "language": language,
                    "task_id": group_id,
                    "pair_group_id": group_id,
                    "text": content,
                    "license": license_id,
                    "split": split,
                    "metadata": {"pair_id": pair_id, "side": side},
                }
            )
        units.append(
            {
                "id": pair_id,
                "kind": "pair",
                "item_ids": item_ids,
                "pair_group_id": group_id,
                "task_id": group_id,
                "split": split,
            }
        )
    return items, units, list(tasks_by_id.values()), behaviour_tests


def _stored_behaviour_test_path(pair_id: str, suffix: str) -> str:
    opaque_name = hashlib.sha256(pair_id.encode("utf-8")).hexdigest()
    return f"tasks/behaviour-tests/{opaque_name}{suffix}"


def _copy_behaviour_tests(dataset: Path, behaviour_tests: dict[str, Path]) -> None:
    for relative_path, source in behaviour_tests.items():
        destination = dataset / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _read_pair_manifest(pair_dir: Path) -> dict[str, Any]:
    manifest_path = pair_dir / "manifest.toml"
    if not manifest_path.is_file():
        raise ValueError(f"pair is missing manifest.toml: {pair_dir.name}")
    with manifest_path.open("rb") as stream:
        return tomllib.load(stream)


def _pair_id(pair_dir: Path, manifest: dict[str, Any]) -> str:
    pair_id = _required_manifest_text(manifest, "id", pair_dir.name)
    if pair_id != pair_dir.name:
        raise ValueError(
            f"manifest id does not match opaque pair directory: {pair_dir.name}"
        )
    return pair_id


def _pair_files(
    pair_dir: Path, manifest: dict[str, Any], pair_id: str
) -> dict[str, Path]:
    names = {
        "a": manifest.get("left"),
        "b": manifest.get("right"),
        "behaviour_test": manifest.get("behaviour_test"),
    }
    files: dict[str, Path] = {}
    for key, name in names.items():
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError(f"invalid {key} file path in pair {pair_id}")
        path = pair_dir / name
        if not path.is_file():
            raise ValueError(f"pair {pair_id} is missing {key} file: {name}")
        files[key] = path
    return files


def _verify_source_hashes(
    files: dict[str, Path], manifest: dict[str, Any], pair_id: str
) -> None:
    declared = manifest.get("sha256")
    if declared is None:
        raise ValueError(f"pair {pair_id} manifest requires [sha256]")
    if not isinstance(declared, dict):
        raise TypeError(f"pair {pair_id} [sha256] must be a table")
    for key, path in files.items():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if declared.get(key) != actual:
            raise ValueError(f"content sha256 mismatch for pair {pair_id} file {key}")


def _required_manifest_text(manifest: dict[str, Any], key: str, pair_id: str) -> str:
    value = manifest.get(key)
    if not isinstance(value, str) or not value.strip():
        if key == "license":
            raise ValueError(
                f'pair {pair_id} manifest requires license; add license = "MIT"'
            )
        raise ValueError(f"pair {pair_id} manifest requires {key}")
    return value


def _verify_command(dataset: Path) -> int:
    errors = verify_dataset(dataset)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"verified dataset: {dataset}")
    return 0
