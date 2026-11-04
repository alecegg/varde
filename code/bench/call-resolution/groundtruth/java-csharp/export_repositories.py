"""Fetch declared pins, verify licenses, and run their language compiler tools."""

from __future__ import annotations

import argparse
import subprocess
import tomllib
from pathlib import Path

from build_samples import build_samples
from tools import exporter_digest, prepare_csharp_references, run_csharp, run_java


def main() -> None:
    args = _args()
    manifest_path = args.repo_manifest
    repos = tomllib.loads(manifest_path.read_text())["repo"]
    env_root = args.env_root
    pin_root = env_root / "pins"
    raw_root = env_root / "records"
    raw_root.mkdir(parents=True, exist_ok=True)
    raw_paths = []
    for repo in repos:
        checkout = pin_root / repo["name"].replace("/", "__")
        _checkout(repo, checkout, env_root)
        output = raw_root / f"{repo['language']}-{checkout.name}.jsonl"
        source = checkout / repo["source_root"]
        if _records_current(output, repo["language"]):
            raw_paths.append(output)
            continue
        if repo["language"] == "java":
            run_java(repo["name"], checkout, source, output, env_root)
        else:
            references = prepare_csharp_references(checkout, source, env_root)
            run_csharp(
                repo["name"], checkout, source, output, env_root, references=references
            )
        raw_paths.append(output)

    build_samples(
        manifest_path,
        raw_paths,
        args.dev_dir,
        args.restricted_dir,
        args.test_manifest,
        seed=args.seed,
    )


def _records_current(output: Path, language: str) -> bool:
    """Reuse records only when the exporter sources that produced them are unchanged."""
    stamp = output.with_suffix(".stamp")
    if not output.is_file() or not stamp.is_file():
        return False
    return stamp.read_text().strip() == exporter_digest(language)


def _checkout(repo: dict[str, str], path: Path, env_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    (env_root / "git-home").mkdir(parents=True, exist_ok=True)
    env = {"HOME": str(env_root / "git-home"), "GIT_TERMINAL_PROMPT": "0"}
    if not (path / ".git").exists():
        _run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                repo["url"],
                str(path),
            ],
            env,
        )
    _run(["git", "fetch", "--depth=1", "origin", repo["sha"]], env, cwd=path)
    license_text = _run(
        ["git", "show", f"{repo['sha']}:{repo['license_file']}"],
        env,
        cwd=path,
    )
    _verify_license(
        license_text,
        repo["license"],
        repo["license_first_nonblank_line"],
    )
    sparse_patterns = path / ".git" / "info" / "sparse-checkout"
    if not sparse_patterns.exists():
        _run(["git", "sparse-checkout", "init", "--cone"], env, cwd=path)
    _run(["git", "sparse-checkout", "set", repo["source_root"]], env, cwd=path)
    _run(["git", "checkout", "--force", "--detach", repo["sha"]], env, cwd=path)
    head = _run(["git", "rev-parse", "HEAD"], env, cwd=path)
    if head.strip() != repo["sha"]:
        raise ValueError(f"pin mismatch for {repo['name']}: {head.strip()}")


def _verify_license(text: str, spdx: str, first_nonblank_line: str) -> None:
    markers = {
        "Apache-2.0": "Apache License",
        "MIT": "The MIT License",
        "BSD-3-Clause": "BSD 3-Clause License",
    }
    marker = markers.get(spdx)
    verified = marker is not None and marker in text
    if spdx == "BSD-3-Clause":
        verified = marker in text or (
            "Redistribution and use in source and binary forms" in text
            and "Neither the name" in text
        )
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if spdx == "MIT":
        verified = verified or "Permission is hereby granted, free of charge" in text
    if not verified or first != first_nonblank_line:
        raise ValueError(f"LICENSE file does not verify {spdx}")


def _run(
    command: list[str],
    env: dict[str, str],
    *,
    cwd: Path | None = None,
) -> str:
    result = subprocess.run(  # noqa: S603 - Runs fixed Git operations while staging pinned benchmark repositories.
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stderr}"
        )
    return result.stdout


def _args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    plan_notes = Path(
        "/Users/alec/source/agent-memory/projects/varde-py/working/plans/"
        "2026-10-17-quality-score-build/qs-call-audit/notes"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-manifest", type=Path, default=root / "repos/java-csharp.toml"
    )
    parser.add_argument("--env-root", type=Path, default=root / "envs/java-csharp")
    parser.add_argument("--dev-dir", type=Path, default=root / "data/dev/java-csharp")
    parser.add_argument(
        "--restricted-dir",
        type=Path,
        default=plan_notes / "restricted/call-audit/java-csharp",
    )
    parser.add_argument(
        "--test-manifest",
        type=Path,
        default=root / "data/test-manifest-java-csharp.json",
    )
    parser.add_argument("--seed", type=int, default=1701)
    return parser.parse_args()


if __name__ == "__main__":
    main()
