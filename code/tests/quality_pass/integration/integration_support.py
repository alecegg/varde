"""Shared helpers and the fixture repository for the quality pass integration tests.

The integration suite drives the pass only through its public entry points:
``run_quality_pass``, ``read_facts`` and ``read_measures``. Index build and
refresh come from the fast-index public API because the pass refuses a stale
index.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.index.incremental import refresh
from varde_code.quality_pass.pass_ import read_facts, read_measures
from varde_code.query import modes

INTEGRATION_DIR = Path(__file__).parent
PASS_CHILD = INTEGRATION_DIR / "integration_pass_child.py"

# One module per release language: Python, TypeScript/TSX, Java, Go, Rust, C#,
# C++. Rust's module declaration is not represented as a resolver import fact,
# so `helper::compute` cannot be identified. Architecture 3.4 classifies
# unresolved calls as opaque.
SEVEN_LANGUAGE_REPO = {
    "pylib/__init__.py": "",
    "pylib/helper.py": "def compute(value):\n    return value + 1\n",
    "pylib/app.py": (
        "from pylib.helper import compute\n\n\ndef run():\n    return compute(2)\n"
    ),
    "tslib/helper.ts": (
        "export function compute(value: number): number {\n  return value + 1;\n}\n"
    ),
    "tslib/app.ts": (
        "import { compute } from './helper';\n\n"
        "export function run(): number {\n  return compute(2);\n}\n"
    ),
    "tslib/view.tsx": (
        "export function label(value: number): string {\n  return String(value);\n}\n"
    ),
    "jvlib/Helper.java": (
        "package jvlib;\n\npublic final class Helper {\n"
        "    public static int compute(int value) {\n        return value + 1;\n"
        "    }\n}\n"
    ),
    "jvlib/App.java": (
        "package jvlib;\n\nimport jvlib.Helper;\n\npublic final class App {\n"
        "    public static int run() {\n        return Helper.compute(2);\n"
        "    }\n}\n"
    ),
    "golib/helper.go": (
        "package golib\n\nfunc Compute(value int) int {\n\treturn value + 1\n}\n"
    ),
    "golib/app.go": "package golib\n\nfunc Run() int {\n\treturn Compute(2)\n}\n",
    "rslib/helper.rs": "pub fn compute(value: i32) -> i32 {\n    value + 1\n}\n",
    "rslib/app.rs": (
        "mod helper;\n\npub fn run() -> i32 {\n    helper::compute(2)\n}\n"
    ),
    "cslib/Helper.cs": (
        "namespace Cslib;\n\npublic static class Helper\n{\n"
        "    public static int Compute(int value)\n    {\n        return value + 1;\n"
        "    }\n}\n"
    ),
    "cslib/App.cs": (
        "namespace Cslib;\n\npublic static class App\n{\n"
        "    public static int Run()\n    {\n        return Helper.Compute(2);\n"
        "    }\n}\n"
    ),
    "cpplib/helper.cpp": "int compute(int value) {\n    return value + 1;\n}\n",
    "cpplib/app.cpp": (
        "int compute(int value);\n\nint run() {\n    return compute(2);\n}\n"
    ),
}

SEVEN_LANGUAGE_FILES = tuple(sorted(SEVEN_LANGUAGE_REPO))

# ``(language, helper, caller, edited helper source)`` for the reverse-closure
# edit tests: the edit changes the helper body but not its function ids, so only
# the helper's own edges recompute and the caller's measures follow via its
# callee's Merkle fingerprint.
REVERSE_CLOSURE_CASES = (
    (
        "python",
        "pylib/helper.py",
        "pylib/app.py",
        "def compute(value):\n    return value + 2\n",
    ),
    (
        "typescript",
        "tslib/helper.ts",
        "tslib/app.ts",
        "export function compute(value: number): number {\n  return value + 2;\n}\n",
    ),
    (
        "java",
        "jvlib/Helper.java",
        "jvlib/App.java",
        (
            "package jvlib;\n\npublic final class Helper {\n"
            "    public static int compute(int value) {\n        return value + 2;\n"
            "    }\n}\n"
        ),
    ),
)
REVERSE_CLOSURE_IDS = [case[0] for case in REVERSE_CLOSURE_CASES]

# A leaf edit (the Python caller has no dependents) and an id-changing edit
# (a same-named sibling moves the helper's function id set, so the importer's
# resolution digest changes and its edges recompute as well).
LEAF_EDIT = (
    "pylib/app.py",
    "from pylib.helper import compute\n\n\ndef run():\n    return compute(3)\n",
)
ID_CHANGE_EDIT = (
    "pylib/helper.py",
    (
        "def compute(value):\n    return value + 1\n"
        "\n\nclass Wrapper:\n    def compute(self):\n        return 0\n"
    ),
)

# Hand-derived from the resolver's scope rules: Python, TypeScript, Java and C#
# (a file's directory stands in for its namespace) resolve their cross-file
# calls; Go and C++ project names without import targets are opaque; Rust's
# helper::compute target is unavailable because its module declaration is not
# an import fact; the TSX String call is external because its name has no
# project definition.
EXPECTED_CALL_COVERAGE = {
    "pylib/app.py": {"resolved": 1, "ambiguous": 0, "opaque": 0, "external": 0},
    "tslib/app.ts": {"resolved": 1, "ambiguous": 0, "opaque": 0, "external": 0},
    "jvlib/App.java": {"resolved": 1, "ambiguous": 0, "opaque": 0, "external": 0},
    "golib/app.go": {"resolved": 0, "ambiguous": 0, "opaque": 1, "external": 0},
    "cslib/App.cs": {"resolved": 1, "ambiguous": 0, "opaque": 0, "external": 0},
    "cpplib/app.cpp": {"resolved": 0, "ambiguous": 0, "opaque": 1, "external": 0},
    "rslib/app.rs": {"resolved": 0, "ambiguous": 0, "opaque": 1, "external": 0},
    "tslib/view.tsx": {"resolved": 0, "ambiguous": 0, "opaque": 0, "external": 1},
}
# Above the 30% unresolved share the structure components are low confidence.
# Only the opaque-only callers cross it; external calls are not unresolved.
EXPECTED_LOW_CONFIDENCE = (
    "cpplib/app.cpp",
    "golib/app.go",
    "rslib/app.rs",
)


def prepare_env(monkeypatch, tmp_path: Path) -> Path:
    """Isolate the config dir and detach any registered index service."""
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)
    return tmp_path / "repo"


def write_repo(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def build_index(root: Path):
    return build(root, CodeExtractionProvider())


def refresh_index(root: Path) -> None:
    refresh(root, CodeExtractionProvider())


def facts_by_path(root: Path) -> dict[str, dict]:
    return {record["path"]: record for record in read_facts(root)}


def measures_by_path(root: Path) -> dict[str, dict]:
    return {record["path"]: record for record in read_measures(root)}


def snapshot(root: Path) -> str:
    """Serialize the stored facts and measures without reordering record keys."""
    return json.dumps(
        {"facts": list(read_facts(root)), "measures": list(read_measures(root))},
        sort_keys=False,
    )


def records_snapshot(payload: dict) -> str:
    """Serialize a child payload's facts and measures without reordering keys.

    ``sort_keys=False`` keeps the key order returned by ``read_facts`` and
    ``read_measures``, so a nondeterministic stored key order shows up as a
    difference instead of being normalized away.
    """
    return json.dumps(
        {"facts": payload["facts"], "measures": payload["measures"]}, sort_keys=False
    )


def run_pass_child(
    root: Path,
    mode: str,
    *,
    workers: int,
    seed: str,
    config_dir: Path | None = None,
    timeout: float = 300,
) -> dict:
    """Run one pass in a fresh interpreter and return its JSON payload."""
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = seed
    if config_dir is not None:
        env["VARDE_CONFIG_DIR"] = str(config_dir)
    result = subprocess.run(  # noqa: S603 - Runs the integration fixture command with constructed arguments.
        [sys.executable, str(PASS_CHILD), str(root), mode, str(workers)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return json.loads(result.stdout)


def crash_repo_files(count: int = 200) -> dict[str, str]:
    """A repository of independent callers large enough to interrupt mid-pass."""
    files = {}
    for index in range(count):
        files[f"crash/mod_{index:03d}.py"] = (
            f"def helper_{index}(value):\n    return value + {index}\n"
            f"\n\ndef entry_{index}():\n    return helper_{index}(1)\n"
        )
    return files
