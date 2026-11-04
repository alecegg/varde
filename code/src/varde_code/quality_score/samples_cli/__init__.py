"""Commands for viewing and recalibrating quality-score samples."""

from __future__ import annotations

import argparse
import difflib
import importlib.resources
import json
import sys
import tomllib
from pathlib import Path
from typing import Any, TextIO

from varde_core.paths import varde_config_dir

from ..calibration import Calibration, load_calibration, shipped_calibration_path
from ..samples import component_diff, component_vector, load_sample
from ..tuner import SampleVectors, recalibrate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="varde code samples")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--json", action="store_true", dest="json_output")
    show = commands.add_parser("show")
    show.add_argument("id")
    show.add_argument("--version", default="smoothed")
    show.add_argument("--diff", nargs=2, metavar=("A", "B"))
    save = commands.add_parser("save")
    save.add_argument("id")
    save.add_argument("--from", required=True, dest="source")
    reset = commands.add_parser("reset")
    reset.add_argument("id")
    recal = commands.add_parser("recalibrate")
    recal.add_argument("--dry-run", action="store_true")
    recal.add_argument("--json", action="store_true", dest="json_output")
    return parser


def run(argv: list[str], io: Any = None) -> int:
    stdout: TextIO = getattr(io, "stdout", sys.stdout)
    stderr: TextIO = getattr(io, "stderr", sys.stderr)
    try:
        args = _parser().parse_args(argv[1:])
        if args.command == "list":
            return _list(args.json_output, stdout)
        if args.command == "show":
            return _show(args.id, args.version, args.diff, stdout)
        if args.command == "save":
            return _save(args.id, args.source, stdout)
        if args.command == "reset":
            return _reset(args.id, stdout)
        return _recalibrate(args.dry_run, args.json_output, stdout)
    except (OSError, ValueError, TypeError, KeyError, tomllib.TOMLDecodeError) as exc:
        print(f"code samples: {exc}", file=stderr)
        return 2


def _sample_ids() -> list[str]:
    root = Path(str(importlib.resources.files("varde_code.quality_score.samples")))
    if not root.is_dir():
        return []
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir()
        and not path.name.startswith(("_", "."))
        and (path / "sample.toml").is_file()
    )


def _list(as_json: bool, stdout: TextIO) -> int:
    samples = [load_sample(sample_id) for sample_id in _sample_ids()]
    records = [
        {
            "id": item.id,
            "language": item.language,
            "task": item.task,
            "user_target": item.user_target,
        }
        for item in samples
    ]
    if as_json:
        print(json.dumps(records, sort_keys=True), file=stdout)
    elif not records:
        print("No quality samples are currently shipped.", file=stdout)
    else:
        for item in records:
            marker = " (user target)" if item["user_target"] else ""
            print(
                f"{item['id']}\t{item['language']}\t{item['task']}{marker}", file=stdout
            )
    return 0


def _version_path(sample, name: str) -> Path:
    if name == "mine":
        return sample.target
    try:
        return sample.versions[name]
    except KeyError as exc:
        raise ValueError(f"sample {sample.id!r} has no version {name!r}") from exc


def _show(sample_id: str, version: str, diff: list[str] | None, stdout: TextIO) -> int:
    sample = load_sample(sample_id)
    if diff:
        first, second = (_version_path(sample, name) for name in diff)
        print(
            "".join(
                difflib.unified_diff(
                    first.read_text(encoding="utf-8").splitlines(keepends=True),
                    second.read_text(encoding="utf-8").splitlines(keepends=True),
                    fromfile=diff[0],
                    tofile=diff[1],
                )
            ),
            end="",
            file=stdout,
        )
    else:
        print(
            _version_path(sample, version).read_text(encoding="utf-8"),
            end="",
            file=stdout,
        )
    return 0


def _save(sample_id: str, source: str, stdout: TextIO) -> int:
    sample = load_sample(sample_id)
    path = Path(source)
    if path.suffix != sample.versions["smoothed"].suffix:
        raise ValueError(f"expected a {sample.versions['smoothed'].suffix} source file")
    from varde_code.quality_pass.facts import extract_facts

    raw = path.read_bytes()
    try:
        facts = extract_facts(raw, sample.language, path.as_posix())
    except (ValueError, TypeError) as exc:
        raise ValueError(f"source could not be parsed into facts: {exc}") from exc
    if not isinstance(facts, dict) or facts.get("contract") not in {
        "facts-1",
        "facts-2",
    }:
        raise ValueError("source could not be parsed into facts")
    if "parse contains errors" in facts.get("diagnostics", []):
        raise ValueError("source could not be parsed into facts: parse contains errors")
    destination = (
        varde_config_dir() / "quality/samples" / sample_id / f"target{path.suffix}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    print("Saved user target. The sample behaviour test was not run.", file=stdout)
    return 0


def _reset(sample_id: str, stdout: TextIO) -> int:
    sample = load_sample(sample_id)
    if sample.user_target:
        sample.target.unlink()
        print(f"Reset {sample_id} to its shipped target.", file=stdout)
    else:
        print(f"{sample_id} already uses its shipped target.", file=stdout)
    return 0


def _sample_vectors(
    calibration: Calibration,
) -> tuple[list[SampleVectors], dict[str, dict[str, int]]]:
    vectors = []
    edited = {}
    for sample_id in _sample_ids():
        sample = load_sample(sample_id)
        versions = {
            name: component_vector(path, calibration)
            for name, path in sample.versions.items()
        }
        target = component_vector(sample.target, calibration)
        if sample.user_target:
            edited[sample.id] = target
        versions["smoothed"] = target
        vectors.append(SampleVectors(sample.id, versions))
    return vectors, edited


def _recalibrate(dry_run: bool, as_json: bool, stdout: TextIO) -> int:
    calibration = load_calibration(shipped_calibration_path())
    samples, edited = _sample_vectors(calibration)
    if not samples:
        raise ValueError("no shipped samples are available for recalibration")
    if not edited:
        raise ValueError("save a user target before recalibrating")
    result = recalibrate(edited, calibration, samples=samples)
    diffs = {
        sample_id: component_diff(
            component_vector(load_sample(sample_id).versions["smoothed"], calibration),
            target,
        )
        for sample_id, target in edited.items()
    }
    label = result.label
    validation = "not validated" if label == "user-edited, gaming-unchecked" else label
    profile_path = varde_config_dir() / "quality/profile.toml"
    written = False
    if result.profile is not None and not dry_run:
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(
            _profile_toml(result.profile, calibration), encoding="utf-8"
        )
        written = True
    payload = {
        "label": label,
        "validation": validation,
        "component_diff": diffs,
        "reasons": list(result.reasons),
        "profile": str(profile_path) if written else None,
        "dry_run": dry_run,
    }
    if as_json:
        print(json.dumps(payload, sort_keys=True), file=stdout)
    else:
        print(f"Calibration: {validation}; {label}.", file=stdout)
        for sample_id, diff in sorted(diffs.items()):
            print(
                f"Component diff for {sample_id} (target minus shipped):", file=stdout
            )
            for name, value in diff.items():
                print(f"  {name}: {value}", file=stdout)
        for reason in result.reasons:
            print(f"Reason: {reason}", file=stdout)
        profile_status = f"written to {profile_path}" if written else "not written"
        print(f"Profile {profile_status}.", file=stdout)
    return 0 if result.profile is not None else 2


def _profile_toml(profile: dict[str, object], calibration: Calibration) -> str:
    meta = profile["profile"]
    if not isinstance(meta, dict):
        raise TypeError("profile metadata must be a mapping")
    lines = ["[profile]"]
    lines.extend(f"{key} = {json.dumps(value)}" for key, value in meta.items())
    languages = profile["languages"]
    if not isinstance(languages, dict):
        raise TypeError("profile languages must be a mapping")
    for language, settings in languages.items():
        if not isinstance(settings, dict):
            raise TypeError("language settings must be a mapping")
        lines.extend(["", f"[languages.{language}.strength]"])
        strength = settings["strength"]
        if not isinstance(strength, dict):
            raise TypeError("language strength must be a mapping")
        profile_targets = {
            "small_side": "A",
            "long_side": "wL",
            "cognitive": "w",
            "structure": "structure",
            "names": "names",
        }
        lines.extend(
            f"{key} = {json.dumps(value)}"
            for key, value in strength.items()
            if profile_targets.get(key, key) in calibration.global_strengths
        )
        lines.extend(["", f"[languages.{language}.validation]"])
        validation = settings["validation"]
        if not isinstance(validation, dict):
            raise TypeError("language validation must be a mapping")
        lines.extend(
            f"{key} = {json.dumps(value)}" for key, value in validation.items()
        )
    return "\n".join(lines) + "\n"
