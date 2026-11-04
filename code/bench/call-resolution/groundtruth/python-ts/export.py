"""Run the pinned static tools and emit normalized call-site records."""

from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from collections.abc import Mapping
from pathlib import Path

from gt_python_ts import export_repository

HERE = Path(__file__).resolve().parent


def export_all(
    manifest: Mapping[str, object],
    checkout_root: Path,
    python_tool: Path,
    typescript_module: Path,
    node: str = "node",
) -> list[dict[str, object]]:
    """Export all manifest repositories with the selected compiler adapters."""
    records = []
    repositories = manifest["repo"]
    if not isinstance(repositories, list):
        raise TypeError("manifest repo entries must be an array")
    for repo in repositories:
        if not isinstance(repo, dict):
            raise TypeError("manifest repo entry must be a table")
        language = _required_text(repo, "language")
        root = checkout_root / _required_text(repo, "checkout_alias")
        if language == "python":
            runner = _python_runner(root, repo, python_tool)
        elif language == "typescript":
            runner = _typescript_runner(root, repo, typescript_module, node)
        else:
            raise ValueError(f"unsupported language in repo manifest: {language}")
        records.extend(export_repository(repo, language, runner))
    return sorted(
        records,
        key=lambda record: (
            str(record["language"]),
            str(record["repo"]),
            str(record["file"]),
            int(record["line"]),
            str(record["call_class"]),
        ),
    )


def _python_runner(root: Path, repo: Mapping[str, object], python_tool: Path):
    roots = json.dumps(repo["source_roots"])

    def run(_repo: Mapping[str, object]):
        return _run_worker(
            [str(python_tool), str(HERE / "python_worker.py"), str(root), roots],
            str(repo["repo"]),
        )

    return run


def _typescript_runner(
    root: Path, repo: Mapping[str, object], module_path: Path, node: str
):
    roots = json.dumps(repo["source_roots"])
    suffixes = json.dumps(repo["source_suffixes"])

    def run(_repo: Mapping[str, object]):
        return _run_worker(
            [
                node,
                str(HERE / "typescript_worker.cjs"),
                str(root),
                str(module_path.resolve()),
                roots,
                suffixes,
            ],
            str(repo["repo"]),
        )

    return run


def _run_worker(command: list[str], repo: str):
    try:
        result = subprocess.run(  # noqa: S603 - Runs a pinned language worker to export benchmark ground truth.
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip()[-2000:]
        raise RuntimeError(
            f"ground-truth worker failed for {repo}: {detail}"
        ) from error
    return json.loads(result.stdout)


def _required_text(record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkout-root", type=Path, required=True)
    parser.add_argument("--python-tool", type=Path, required=True)
    parser.add_argument("--typescript-module", type=Path, required=True)
    parser.add_argument("--node", default="node")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    records = export_all(
        manifest,
        args.checkout_root,
        args.python_tool,
        args.typescript_module,
        args.node,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False))
            stream.write("\n")
    print(json.dumps({"records": len(records), "output": str(args.output)}))


if __name__ == "__main__":
    main()
