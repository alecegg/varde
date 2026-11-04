"""Copy a seeded judge sample into the quality-score package format."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

AUTHORED_BY = "codex gpt-6-luna seeded run 2026-10-22"
LANGUAGES = {
    ".py": "python",
    ".ts": "typescript",
    ".go": "go",
    ".java": "java",
    ".cs": "csharp",
}
JUDGES = {
    "extract": "extract-everything",
    "inline": "inline-everything",
    "names": "name-obsessed",
    "defensive": "defensive-and-commented",
    "classes": "class/abstraction-heavy",
}
FORBIDDEN_DIRS = {"bin", "obj", "__pycache__"}


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _metadata(language: str, task: str, files: dict[str, bytes]) -> str:
    lines = [
        f"language = {_toml_string(language)}",
        f"task = {_toml_string(task)}",
        f"authored_by = {_toml_string(AUTHORED_BY)}",
        "biases = ["
        + ", ".join(_toml_string(value) for value in JUDGES.values())
        + "]",
        "",
        "[hashes]",
    ]
    for name, data in sorted(files.items()):
        lines.append(
            f"{_toml_string(name)} = {_toml_string(hashlib.sha256(data).hexdigest())}"
        )
    return "\n".join(lines) + "\n"


def land_sample(source: Path, samples_root: Path) -> str:
    source = source.resolve()
    samples_root = samples_root.resolve()
    if not source.is_dir():
        raise ValueError(f"sample source is not a directory: {source}")
    leftovers = sorted(
        str(path.relative_to(source))
        for path in source.rglob("*")
        if path.is_dir() and path.name in FORBIDDEN_DIRS
    )
    if leftovers:
        raise ValueError(
            f"remove generated directories before landing: {', '.join(leftovers)}"
        )

    source_files = {
        path.name: path
        for path in source.iterdir()
        if path.is_file() and not path.name.startswith("test.")
    }
    task_path = source_files.get("task.md")
    if task_path is None:
        raise ValueError("sample source requires task.md")
    code_files = [path for path in source_files.values() if path.stem == "smoothed"]
    if len(code_files) != 1 or code_files[0].suffix not in LANGUAGES:
        raise ValueError("sample source requires one supported smoothed.<ext> file")
    suffix = code_files[0].suffix
    required = {
        "behaviour_test" + suffix,
        "original" + suffix,
        "smoothed" + suffix,
        "smoothing.md",
    }
    required.update(f"judge-{judge}{suffix}" for judge in JUDGES)
    missing = sorted(required - source_files.keys())
    if missing:
        raise ValueError(
            f"sample source is missing required files: {', '.join(missing)}"
        )
    if any(
        path.suffix != suffix
        for name, path in source_files.items()
        if name.startswith("judge-")
    ):
        raise ValueError("all judge files must use the smoothed source extension")

    files = {name: path.read_bytes() for name, path in source_files.items()}
    task_lines = files["task.md"].decode("utf-8").splitlines()
    task = task_lines[0].strip() if task_lines else ""
    if not task:
        task = "Seeded judge quality sample"
    sample_id = "s" + hashlib.sha256(files["smoothed" + suffix]).hexdigest()[:8]
    destination = samples_root / sample_id
    if destination.exists():
        raise FileExistsError(f"sample destination already exists: {destination}")
    destination.mkdir(parents=True)
    try:
        for name, data in files.items():
            (destination / name).write_bytes(data)
        (destination / "sample.toml").write_text(
            _metadata(LANGUAGES[suffix], task, files), encoding="utf-8"
        )
    except Exception:
        shutil.rmtree(destination)
        raise
    return sample_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample_dir", type=Path)
    parser.add_argument("samples_package_root", type=Path)
    args = parser.parse_args()
    print(land_sample(args.sample_dir, args.samples_package_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
