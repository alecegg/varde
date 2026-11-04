"""Run every declared item version against its shared behaviour test."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path


def available_commands(suffix: str) -> list[str] | None:
    candidates = {
        ".py": ["python3"],
        ".go": ["go"],
        ".rs": ["cargo"],
        ".java": ["javac", "java"],
        ".cs": ["dotnet"],
        ".cpp": ["g++", "clang++"],
        ".cc": ["g++", "clang++"],
    }
    if suffix == ".java":
        return (
            ["javac", "java"]
            if all(shutil.which(name) for name in ("javac", "java"))
            else None
        )
    if suffix == ".rs":
        if not shutil.which("cargo"):
            return None
        probe = subprocess.run(
            ["cargo", "--version"], check=False, capture_output=True, text=True
        )
        return ["cargo"] if probe.returncode == 0 else None
    if suffix == ".ts":
        if (
            shutil.which("node")
            and "--experimental-strip-types"
            in subprocess.run(
                ["node", "--help"], check=False, capture_output=True, text=True
            ).stdout
        ):
            return ["node"]
        return ["tsc"] if shutil.which("tsc") and shutil.which("node") else None
    for command in candidates.get(suffix, []):
        if shutil.which(command):
            return [command]
    return None


def unavailable_reason(suffix: str) -> str:
    if suffix == ".rs" and shutil.which("cargo"):
        return (
            "Rust toolchain unavailable: cargo is present but rustup has no "
            "installed default toolchain"
        )
    names = {
        ".py": "python3",
        ".ts": "Node type stripping or tsc",
        ".go": "go",
        ".rs": "cargo",
        ".java": "javac and java",
        ".cs": "dotnet",
        ".cpp": "g++ or clang++",
        ".cc": "g++ or clang++",
    }
    return f"{names.get(suffix, suffix)} toolchain unavailable on PATH"


def workspace_commands(
    root: Path, solution: Path, test: Path, tools: list[str]
) -> tuple[list[list[str]], list[str]]:
    """Lay out a solution and its behaviour test under root.

    Returns the compile or build commands and then the command that runs the
    built test against the solution. A failing build command means the version
    does not compile; a failing run command means the behaviour test fails.
    Languages without a separate build step return an empty build list.
    """
    suffix = solution.suffix
    if suffix == ".py":
        return [["python3", "-m", "py_compile", str(solution)]], ["python3", str(test)]
    if suffix == ".ts":
        if tools[0] == "node":
            return [], ["node", "--experimental-strip-types", str(test)]
        return (
            [["tsc", str(test), "--target", "es2022", "--module", "commonjs"]],
            ["node", str(test.with_suffix(".js"))],
        )
    if suffix == ".go":
        (root / "go.mod").write_text("module corpus\n\ngo 1.20\n")
        (root / test.name).write_bytes(test.read_bytes())
        return [["go", "build", "./..."]], ["go", "test", "./..."]
    if suffix == ".rs":
        (root / "Cargo.toml").write_text(
            '[package]\nname="corpus"\nversion="0.1.0"\nedition="2021"\n'
        )
        (root / "src").mkdir()
        shutil.move(solution, root / "src/lib.rs")
        (root / "tests").mkdir()
        shutil.move(test, root / "tests/behaviour_test.rs")
        return [["cargo", "build", "--offline"]], ["cargo", "test", "--offline"]
    if suffix == ".java":
        return (
            [["javac", solution.name, test.name]],
            ["java", "-cp", str(root), test.stem],
        )
    if suffix == ".cs":
        sdks = subprocess.run(
            ["dotnet", "--list-sdks"], check=False, capture_output=True, text=True
        ).stdout
        versions = re.findall(r"^(\d+)\.[\d.]+\s", sdks, re.MULTILINE)
        target = max(map(int, versions)) if versions else 8
        project = root / "corpus.csproj"
        project.write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            "<OutputType>Exe</OutputType>"
            f"<TargetFramework>net{target}.0</TargetFramework></PropertyGroup></Project>"
        )
        return [["dotnet", "build", str(project)]], [
            "dotnet",
            "run",
            "--no-build",
            "--project",
            str(project),
        ]
    return [[tools[0], str(test), "-o", str(root / "test")]], [str(root / "test")]


def run_version(source: Path, test: Path) -> tuple[str, str]:
    tools = available_commands(source.suffix)
    if tools is None:
        return "blocked", f"missing toolchain for {source.suffix}"
    with tempfile.TemporaryDirectory(prefix="varde-behaviour-") as temp:
        root = Path(temp)
        solution = root / f"solution{source.suffix}"
        test_copy = root / test.name
        shutil.copy2(source, solution)
        shutil.copy2(test, test_copy)
        build, command = workspace_commands(root, solution, test_copy, tools)
        steps = [*build, command]
        for index, step in enumerate(steps):
            result = subprocess.run(
                step, cwd=root, capture_output=True, text=True, check=False
            )
            if result.returncode:
                kind = "failed" if index == len(build) else "broken"
                return kind, result.stderr or result.stdout
        return "passed", ""


def pair_versions(pair: object) -> list[str] | None:
    if not isinstance(pair, dict):
        return None
    if "pairs" not in pair:
        versions = [pair.get("left"), pair.get("right")]
    else:
        pair_entries = pair["pairs"]
        if not isinstance(pair_entries, list):
            return None
        versions = []
        for entry in pair_entries:
            if not isinstance(entry, dict):
                return None
            versions.extend((entry.get("left"), entry.get("right")))
    if any(not isinstance(name, str) for name in versions):
        return None
    unique = list(dict.fromkeys(versions))
    return [name for name in unique if Path(name).stem == "sensible"] + [
        name for name in unique if Path(name).stem != "sensible"
    ]


def run_item(item_dir: Path) -> list[dict[str, str]]:
    tests = list(item_dir.glob("behaviour_test.*"))
    sources = [
        p
        for p in item_dir.iterdir()
        if p.is_file()
        and p.suffix not in {".txt", ".json", ".toml", ".md"}
        and not p.name.startswith("behaviour_test.")
    ]
    declared = None
    pair_path = item_dir / "pair.json"
    manifest_path = item_dir / "manifest.toml"
    try:
        if pair_path.exists():
            pair = json.loads(pair_path.read_text())
            declared = pair_versions(pair) or []
        elif manifest_path.exists():
            manifest = tomllib.loads(manifest_path.read_text())
            declared = manifest.get("versions")
    except json.JSONDecodeError, KeyError, TypeError, tomllib.TOMLDecodeError:
        declared = []
    if declared is None:
        sides = sources
    elif not isinstance(declared, list) or any(
        not isinstance(name, str) or Path(name).name != name for name in declared
    ):
        sides = []
    else:
        sides = [item_dir / name for name in declared]
    if (
        len(tests) != 1
        or len(sides) < 2
        or len(set(sides)) != len(sides)
        or any(not side.is_file() for side in sides)
    ):
        return [
            {
                "kind": "invalid_item",
                "item": str(item_dir),
                "message": (
                    "expected at least two declared versions and one behaviour test"
                ),
            }
        ]
    findings = []
    for side in sides:
        status, message = run_version(side, tests[0])
        if status != "passed":
            findings.append(
                {
                    "kind": status,
                    "item": item_dir.name,
                    "version": side.name,
                    "message": message,
                }
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--items", type=Path)
    group.add_argument("--all", action="store_true")
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--allow-missing-toolchain", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "items" if args.all else args.items
    if not root.exists():
        parser.error(f"items directory does not exist: {root}")
    items = (
        [root]
        if any(root.glob("behaviour_test.*"))
        else [
            p for p in root.rglob("*") if p.is_dir() and any(p.glob("behaviour_test.*"))
        ]
    )
    findings = [f for item in items for f in run_item(item)]
    for finding in findings:
        finding["status"] = (
            finding["kind"] if finding["kind"] in {"blocked", "broken"} else "failed"
        )
        print(json.dumps(finding, sort_keys=True))
    failed = any(f["kind"] != "blocked" for f in findings)
    blocked = any(f["kind"] == "blocked" for f in findings)
    if blocked and args.allow_missing_toolchain:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "versions": sum(f["kind"] == "blocked" for f in findings),
                }
            )
        )
    if not findings:
        print(json.dumps({"status": "passed", "items": len(items)}))
    return 1 if failed or (blocked and not args.allow_missing_toolchain) else 0


if __name__ == "__main__":
    raise SystemExit(main())
