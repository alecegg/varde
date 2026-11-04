"""Run a baseline problem's behaviour tests against one solution, sandboxed.

``plan_test`` is pure (language, code dir, test file -> command and staged
files). ``run_tests`` stages them in a temp directory and runs the command
with a scrubbed environment, a timeout and a capped output. Network is not
blocked (see ``docs/sandbox-permissions.md``).
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TIMEOUT_SECONDS = 60.0
OUTPUT_CAP_BYTES = 64 * 1024
KEPT_ENV = ("PATH", "DOTNET_ROOT", "LANG")


@dataclass(frozen=True)
class LanguageSpec:
    tools: tuple[str, ...]
    solution: str
    test: str
    command: tuple[str, ...]


LANGUAGES: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        ("python3",),
        "solution.py",
        "test_solution.py",
        ("python3", "-m", "unittest", "test_solution"),
    ),
    "typescript": LanguageSpec(
        ("node",),
        "solution.ts",
        "solution.test.ts",
        ("node", "--test", "solution.test.ts"),
    ),
    "csharp": LanguageSpec(
        ("dotnet",),
        "Solution.cs",
        "Tests.cs",
        ("dotnet", "run", "--project", "Baseline.csproj"),
    ),
}


@dataclass(frozen=True)
class TestPlan:
    __test__ = False  # not a pytest class

    command: tuple[str, ...]
    tools: tuple[str, ...]
    copies: tuple[tuple[Path, str], ...]  # (source, name in the work directory)


@dataclass(frozen=True)
class TestResult:
    __test__ = False  # not a pytest class

    ok: bool
    passed: int
    failed: int
    output_tail: str


def plan_test(language: str, code_dir: Path, test_file: Path) -> TestPlan:
    """Return the command and files to stage; raise KeyError for an unknown language."""
    spec = LANGUAGES[language]
    return TestPlan(
        spec.command,
        spec.tools,
        ((code_dir / spec.solution, spec.solution), (test_file, spec.test)),
    )


def toolchain_available(language: str) -> bool:
    spec = LANGUAGES.get(language)
    return spec is not None and all(shutil.which(tool) for tool in spec.tools)


def scrubbed_env(source: Mapping[str, str], home: Path) -> dict[str, str]:
    """Only PATH and toolchain variables from ``source``, with a temp HOME."""
    kept = {key: source[key] for key in KEPT_ENV if key in source}
    return kept | {
        "HOME": str(home),
        "DOTNET_CLI_HOME": str(home),
        "DOTNET_NOLOGO": "1",
        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    }


def _count(pattern: str, text: str) -> int | None:
    found = re.findall(pattern, text)
    return int(found[-1]) if found else None


def parse_counts(language: str, output: str) -> tuple[int, int] | None:
    """Return (passed, failed) from the runner's summary, or None if absent."""
    if language == "typescript":
        passed, failed = (
            _count(r"(?m)^\D*pass (\d+)", output),
            _count(r"(?m)^\D*fail (\d+)", output),
        )
        return None if passed is None or failed is None else (passed, failed)
    if language == "csharp":
        found = re.findall(r"(\d+)/(\d+) passed", output)
        return (
            None
            if not found
            else (int(found[-1][0]), int(found[-1][1]) - int(found[-1][0]))
        )
    ran = _count(r"Ran (\d+) tests?", output)
    if ran is None:
        return None
    failed = sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)", output))
    return ran - failed, failed


def _framework_major(env: dict[str, str]) -> str:
    done = subprocess.run(
        ["dotnet", "--version"],  # noqa: S607
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return done.stdout.strip().split(".")[0] or "8"


def _stage(root: Path, plan: TestPlan, support: Mapping[str, str], tfm: str) -> None:
    for source, name in plan.copies:
        shutil.copy(source, root / name)
    for name, text in support.items():
        (root / name).write_text(text.replace("{tfm}", tfm))


def _drain(stream, keep: list[bytes]) -> None:
    """Read to EOF, keeping only the last OUTPUT_CAP_BYTES."""
    tail = b""
    while chunk := stream.read(8192):
        tail = (tail + chunk)[-OUTPUT_CAP_BYTES:]
    keep.append(tail)


def _run_capped(
    command: tuple[str, ...], cwd: Path, env: dict[str, str], timeout: float
) -> tuple[int | None, str]:
    """Run in a new process group and kill it afterwards; code is None on timeout."""
    proc = subprocess.Popen(  # noqa: S603 - command comes from LANGUAGES.
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    keep: list[bytes] = []
    reader = threading.Thread(target=_drain, args=(proc.stdout, keep), daemon=True)
    reader.start()
    try:
        code: int | None = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        code = None
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)  # also kills stray grandchildren
    proc.wait()
    reader.join(timeout=5)
    return code, (keep[0] if keep else b"").decode("utf-8", errors="replace")


def run_tests(
    language: str,
    code_dir: Path,
    test_file: Path,
    support: Mapping[str, str] | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> TestResult | None:
    """Run the tests; None when the toolchain is missing (not a failure)."""
    if not toolchain_available(language):
        return None
    plan = plan_test(language, code_dir, test_file)
    with tempfile.TemporaryDirectory(prefix="baseline-tests-") as temp:
        root = Path(temp)
        home = root / "home"
        home.mkdir()
        work = root / "work"
        work.mkdir()
        env = scrubbed_env(os.environ, home)
        tfm = _framework_major(env) if language == "csharp" else "8"
        _stage(work, plan, support or {}, tfm)
        code, tail = _run_capped(plan.command, work, env, timeout)
    if code is None:
        return TestResult(False, 0, 0, tail + "\ntimed out")
    counts = parse_counts(language, tail)
    passed, failed = counts or (0, 0 if code == 0 else 1)
    return TestResult(code == 0, passed, failed, tail)
