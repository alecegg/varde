"""Enforce test and script file dependencies; core gate files are exempt.

Module ``src/`` files and root-level Python files are outside this scan.
"""

from __future__ import annotations

import ast
import fnmatch
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = re.compile(r"(?<![\w.-])([a-z][a-z0-9_-]*)/(?:src|tests|scripts|pex)/")
PATH_TOKEN = re.compile(r"([a-z][a-z0-9_-]*/(?:src|tests|scripts|pex)/[\w./-]*)")


def _module_sources(root: Path, module: str) -> list[Path]:
    paths = [root / module / "tests", root / module / "scripts"]
    sources = [
        path
        for directory in paths
        if directory.exists()
        for path in directory.rglob("*")
    ]
    sources.extend((root / module).glob("*.sh"))
    return [
        path
        for path in sources
        if path.is_file()
        and path.suffix in {".sh", ".py"}
        and (
            path.suffix == ".sh"
            or path.parent.name == "scripts"
            or "tests" in path.parts
        )
    ]


def _python_references(
    path: Path, modules: set[str], root: Path
) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    references: set[tuple[str, str]] = set()
    sys_path_constants = {
        id(item)
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and ast.unparse(call.func) in {"sys.path.insert", "sys.path.append"}
        for item in ast.walk(call)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }

    def add(text: str, kind: str) -> None:
        for token in text.split():
            for match in PATH_TOKEN.finditer(token):
                target = MODULE_PATH.match(match.group(0))
                exists = (root / match.group(0).rstrip("/")).exists()
                if target and target.group(1) in modules and exists:
                    references.add((target.group(1), kind))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            kind = "sys-path" if id(node) in sys_path_constants else "file-read"
            add(node.value, kind)
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            parts = [
                str(item.value)
                for item in sorted(
                    (
                        item
                        for item in ast.walk(node)
                        if isinstance(item, ast.Constant)
                        and isinstance(item.value, str)
                    ),
                    key=lambda item: (item.lineno, item.col_offset),
                )
            ]
            kind = (
                "sys-path"
                if any(
                    isinstance(item, ast.Constant) and id(item) in sys_path_constants
                    for item in ast.walk(node)
                )
                else "file-read"
            )
            add("/".join(parts) + "/", kind)
    return references


def _shell_references(
    path: Path, modules: set[str], root: Path
) -> set[tuple[str, str]]:
    references = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0]
        for match in PATH_TOKEN.finditer(line):
            target = MODULE_PATH.match(match.group(0))
            exists = (root / match.group(0).rstrip("/")).exists()
            if target and target.group(1) in modules and exists:
                references.add((target.group(1), "shell"))
    return references


def coupling_violations(root: Path) -> list[str]:
    config = tomllib.loads((root / "layers.toml").read_text(encoding="utf-8"))
    layers = config["module"]
    modules = set(layers)
    entries = config.get("coupling", [])
    exempt_paths = config.get("exempt", {}).get("paths", [])
    errors = []
    matched: set[int] = set()
    for source_module in sorted(modules):
        for source in _module_sources(root, source_module):
            relative = source.relative_to(root).as_posix()
            if any(fnmatch.fnmatchcase(relative, pattern) for pattern in exempt_paths):
                continue
            references = (
                _shell_references(source, modules, root)
                if source.suffix == ".sh"
                else _python_references(source, modules, root)
            )
            for target_module, kind in sorted(references):
                if target_module == source_module:
                    continue
                if layers[target_module]["level"] >= layers[source_module]["level"]:
                    errors.append(
                        f"{relative} references non-lower module {target_module}"
                    )
                    continue
                matches = [
                    index
                    for index, entry in enumerate(entries)
                    if entry["from"] == source_module
                    and entry["to"] == target_module
                    and entry["kind"] == kind
                    and fnmatch.fnmatchcase(relative, entry["path"])
                ]
                if not matches:
                    errors.append(
                        f"{relative} references {target_module} without "
                        "a coupling entry"
                    )
                matched.update(matches)
    for index, entry in enumerate(entries):
        if layers[entry["to"]]["level"] >= layers[entry["from"]]["level"]:
            errors.append(
                f"coupling {entry['from']} -> {entry['to']} must point downward"
            )
        if index not in matched:
            errors.append(
                f"stale coupling entry {entry['from']} -> {entry['to']}: "
                f"{entry['path']}"
            )
    return errors


def test_module_couplings_are_declared_and_downward() -> None:
    assert coupling_violations(ROOT) == []


def test_coupling_scan_rejects_sideways_paths_and_stale_entries(tmp_path: Path) -> None:
    (tmp_path / "lower/tests").mkdir(parents=True)
    (tmp_path / "upper/tests").mkdir(parents=True)
    (tmp_path / "lower/src/pkg").mkdir(parents=True)
    (tmp_path / "lower/src/pkg/file.py").touch()
    (tmp_path / "layers.toml").write_text(
        '[module.lower]\ndist="lower"\nlevel=1\n'
        '[module.upper]\ndist="upper"\nlevel=1\n',
        encoding="utf-8",
    )
    (tmp_path / "upper/tests/test_paths.py").write_text(
        'from pathlib import Path\nPath("lower/src/pkg/file.py")\n',
        encoding="utf-8",
    )
    errors = coupling_violations(tmp_path)
    assert "upper/tests/test_paths.py references non-lower module lower" in errors


def test_coupling_scan_requires_entries_for_downward_paths(tmp_path: Path) -> None:
    (tmp_path / "lower/tests").mkdir(parents=True)
    (tmp_path / "upper/tests").mkdir(parents=True)
    (tmp_path / "lower/src/pkg").mkdir(parents=True)
    (tmp_path / "lower/src/pkg/file.py").touch()
    (tmp_path / "layers.toml").write_text(
        '[module.lower]\ndist="lower"\nlevel=0\n'
        '[module.upper]\ndist="upper"\nlevel=1\n',
        encoding="utf-8",
    )
    (tmp_path / "upper/tests/test_paths.py").write_text(
        'from pathlib import Path\nPath("lower/src/pkg/file.py")\n',
        encoding="utf-8",
    )
    assert coupling_violations(tmp_path) == [
        "upper/tests/test_paths.py references lower without a coupling entry"
    ]


def test_coupling_scan_finds_process_and_shell_path_strings(tmp_path: Path) -> None:
    (tmp_path / "app/tests").mkdir(parents=True)
    (tmp_path / "workflow/tests").mkdir(parents=True)
    (tmp_path / "app/scripts").mkdir(parents=True)
    (tmp_path / "app/scripts/generate.py").touch()
    (tmp_path / "workflow/tests/x.sh").touch()
    (tmp_path / "app/tests/y.sh").touch()
    (tmp_path / "layers.toml").write_text(
        '[module.workflow]\ndist="workflow"\nlevel=2\n'
        '[module.app]\ndist="app"\nlevel=1\n',
        encoding="utf-8",
    )
    (tmp_path / "workflow/tests/test_process.py").write_text(
        'import subprocess\nsubprocess.run(["uv", "run", "python", '
        '"app/scripts/generate.py"])\n'
        'subprocess.run("bash app/tests/y.sh", shell=True)\n'
        'subprocess.run("uv run python app/scripts/generate.py", shell=True)\n',
        encoding="utf-8",
    )
    (tmp_path / "app/tests/test_paths.sh").write_text(
        '"$REPO_ROOT/workflow/tests/x.sh" "$REPO_ROOT"\nbash app/tests/y.sh\n',
        encoding="utf-8",
    )
    errors = coupling_violations(tmp_path)
    assert (
        "workflow/tests/test_process.py references app without a coupling entry"
        in errors
    )
    assert "app/tests/test_paths.sh references non-lower module workflow" in errors
