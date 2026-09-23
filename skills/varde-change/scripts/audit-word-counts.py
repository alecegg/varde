#!/usr/bin/env python3
"""Count words in Varde skill entrypoints and references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit physical words in Varde skill prompt documents."
    )
    parser.add_argument("--skills-dir", required=True, type=Path)
    parser.add_argument("--baseline-skills-dir", type=Path)
    parser.add_argument("--path-catalog", type=Path)
    parser.add_argument("--required-path", action="append", default=[])
    parser.add_argument("--observed-path", action="append", default=[])
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def word_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").split())


def prompt_files(skills_dir: Path) -> list[Path]:
    entrypoints = skills_dir.glob("varde-*/SKILL.md")
    references = skills_dir.glob("varde-*/references/*.md")
    assets = skills_dir.glob("varde-*/assets/*.md")
    return sorted({*entrypoints, *references, *assets})


def inventory(skills_dir: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    packages: dict[str, dict[str, int]] = {}
    entrypoint_words = 0
    reference_words = 0
    entrypoint_files = 0
    reference_files = 0

    for path in prompt_files(skills_dir):
        relative = path.relative_to(skills_dir).as_posix()
        package = relative.split("/", 1)[0]
        kind = "entrypoint" if path.name == "SKILL.md" else "reference"
        words = word_count(path)
        files[relative] = {"kind": kind, "words": words}
        package_totals = packages.setdefault(package, {"files": 0, "words": 0})
        package_totals["files"] += 1
        package_totals["words"] += words
        if kind == "entrypoint":
            entrypoint_files += 1
            entrypoint_words += words
        else:
            reference_files += 1
            reference_words += words

    return {
        "corpus": {
            "files": entrypoint_files + reference_files,
            "words": entrypoint_words + reference_words,
        },
        "entrypoint": {"files": entrypoint_files, "words": entrypoint_words},
        "reference": {"files": reference_files, "words": reference_words},
        "packages": packages,
        "files": files,
    }


def routing_path(
    label: str, paths: list[str], current: dict[str, Any]
) -> dict[str, Any]:
    unique_paths = sorted(set(paths))
    missing = [path for path in unique_paths if path not in current["files"]]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"{label} contains unknown prompt documents: {joined}")
    return {
        "files": unique_paths,
        "words": sum(current["files"][path]["words"] for path in unique_paths),
    }


def comparison(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    matching = sorted(set(baseline["files"]) & set(current["files"]))
    files = {}
    for path in matching:
        baseline_words = baseline["files"][path]["words"]
        current_words = current["files"][path]["words"]
        files[path] = {
            "baseline": baseline_words,
            "current": current_words,
            "delta": current_words - baseline_words,
        }
    return {
        "corpus_word_delta": (
            current["corpus"]["words"] - baseline["corpus"]["words"]
        ),
        "files": files,
    }


def catalog_routes(
    catalog_path: Path, current: dict[str, Any]
) -> dict[str, Any]:
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot read path catalog: {error}") from error

    if catalog.get("schema_version") != 1:
        raise SystemExit("path catalog schema_version must equal 1")
    routes = catalog.get("routes")
    if not isinstance(routes, list):
        raise SystemExit("path catalog routes must be an array")

    result: dict[str, Any] = {}
    for route in routes:
        if not isinstance(route, dict):
            raise SystemExit("path catalog routes must be objects")
        route_id = route.get("id")
        eval_id = route.get("eval_id")
        required = route.get("required_documents")
        observed = route.get("observed_documents")
        if not isinstance(route_id, str) or not route_id:
            raise SystemExit("every catalog route needs a non-empty id")
        if route_id in result:
            raise SystemExit(f"duplicate catalog route id: {route_id}")
        if not isinstance(eval_id, int):
            raise SystemExit(f"catalog route {route_id} needs an integer eval_id")
        if not isinstance(required, list) or not all(
            isinstance(path, str) for path in required
        ):
            raise SystemExit(
                f"catalog route {route_id} required_documents must be strings"
            )
        if not isinstance(observed, list) or not all(
            isinstance(path, str) for path in observed
        ):
            raise SystemExit(
                f"catalog route {route_id} observed_documents must be strings"
            )
        result[route_id] = {
            "eval_id": eval_id,
            "required_path": routing_path(
                f"catalog route {route_id} required path", required, current
            ),
            "observed_path": routing_path(
                f"catalog route {route_id} observed path", observed, current
            ),
        }
    return result


def main() -> None:
    args = parse_args()
    if not args.skills_dir.is_dir():
        raise SystemExit(f"skills directory not found: {args.skills_dir}")

    current = inventory(args.skills_dir)
    result: dict[str, Any] = {
        "schema_version": 1,
        "current": current,
        "required_path": routing_path(
            "required path", args.required_path, current
        ),
        "observed_path": routing_path(
            "observed path", args.observed_path, current
        ),
    }
    if args.path_catalog is not None:
        result["routes"] = catalog_routes(args.path_catalog, current)

    if args.baseline_skills_dir is not None:
        if not args.baseline_skills_dir.is_dir():
            raise SystemExit(
                f"baseline skills directory not found: {args.baseline_skills_dir}"
            )
        baseline = inventory(args.baseline_skills_dir)
        result["baseline"] = baseline
        result["comparison"] = comparison(baseline, current)

    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(output, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
