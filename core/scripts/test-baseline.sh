#!/usr/bin/env python3
"""Run module pytest suites and fail when any test or module fails."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    "core",
    "toz",
    "code",
    "visualize",
    "design",
    "learn",
    "workflow",
    "app",
    "runner",
    "data",
    "serve",
)
SUMMARY_HEADER = "short test summary info"
FAILURE_LINE = re.compile(
    r"^(?:FAILED|ERROR)\s+(\S+?::[^\[\s]+(?:\[.*?\])?|\S+\.py)(?:\s+-\s+.*)?$"
)
SKIP_LINE = re.compile(r"^SKIPPED \[(\d+)\]")
PYTEST_FAILED_EXIT_CODE = 1
DEFAULT_MODULE_TIMEOUT_SECONDS = 300
MODULE_TIMEOUT_SECONDS = {"runner": 1200, "learn": 2400}
NPM_PROJECTS = (
    "runner/ui",
    "runner/sidecar",
    "runner/node-host/engines/durable",
)
XDIST_MODULES = {"core", "code", "workflow", "data"}


class ModuleResult(NamedTuple):
    module: str
    returncode: int
    output: str
    timed_out: bool
    timeout: int


class RunSummary(NamedTuple):
    failures: set[str]
    failed_modules: list[str]
    skips: int
    skip_details: list[tuple[str, str]]


def aggregate_results(results: list[ModuleResult]) -> RunSummary:
    failures: set[str] = set()
    failed_modules: list[str] = []
    skips = 0
    skip_details: list[tuple[str, str]] = []
    for result in results:
        if result.timed_out or crash_reason(result.returncode, result.output):
            failed_modules.append(result.module)
            continue
        module_failures = parse_failures(result.output)
        failures.update(module_failures)
        skips += count_skips(result.output)
        skip_details.extend(
            (result.module, line) for line in skip_reasons(result.output)
        )
    return RunSummary(failures, failed_modules, skips, skip_details)


def test_jobs(environment: Mapping[str, str], cpu_count: int | None = None) -> int:
    value = environment.get("VARDE_TEST_JOBS")
    if value is not None:
        try:
            jobs = int(value)
        except ValueError as exc:
            raise ValueError("VARDE_TEST_JOBS must be a positive integer") from exc
        if jobs <= 0:
            raise ValueError("VARDE_TEST_JOBS must be a positive integer")
        return jobs
    cpus = cpu_count if cpu_count is not None else (os.cpu_count() or 1)
    # Selected modules each start two xdist workers; keep host load bounded.
    return min(2, max(1, cpus // 4))


def pytest_command(module: str) -> list[str]:
    command = [
        "uv",
        "run",
        "--offline",
        "--no-sync",
        "pytest",
        f"{module}/tests",
        "-q",
        "-rfEs",
    ]
    if module in XDIST_MODULES:
        command.extend(["-n", "2"])
    return command


def summary_lines(output: str) -> list[str]:
    lines = output.splitlines()
    starts = [index for index, line in enumerate(lines) if SUMMARY_HEADER in line]
    return lines[starts[-1] + 1 :] if starts else []


def parse_failures(output: str) -> set[str]:
    matches = (FAILURE_LINE.match(line) for line in summary_lines(output))
    return {match.group(1) for match in matches if match}


def count_skips(output: str) -> int:
    matches = (SKIP_LINE.match(line) for line in summary_lines(output))
    return sum(int(match.group(1)) for match in matches if match)


def skip_reasons(output: str) -> list[str]:
    return [line for line in summary_lines(output) if SKIP_LINE.match(line)]


def has_failures(failures: set[str], failed_modules: list[str]) -> bool:
    return bool(failures or failed_modules)


def crash_reason(returncode: int, output: str) -> str | None:
    if returncode == 0:
        return None
    if returncode != PYTEST_FAILED_EXIT_CODE:
        return f"pytest exited {returncode}"
    if not parse_failures(output):
        return "pytest reported failures but no failure id"
    return None


def module_timeout_seconds(module: str, environment: Mapping[str, str]) -> int:
    value = environment.get(
        f"VARDE_TEST_{module.upper()}_TIMEOUT_SECONDS",
        environment.get(
            "VARDE_TEST_MODULE_TIMEOUT_SECONDS",
            str(MODULE_TIMEOUT_SECONDS.get(module, DEFAULT_MODULE_TIMEOUT_SECONDS)),
        ),
    )
    try:
        timeout = int(value)
    except ValueError as exc:
        raise ValueError(
            f"invalid test timeout {value!r} for {module}; "
            "expected a positive integer number of seconds"
        ) from exc
    if timeout <= 0:
        raise ValueError(
            f"invalid test timeout {value!r} for {module}; "
            "expected a positive integer number of seconds"
        )
    return timeout


def npm_lock_is_current(project: Path) -> bool:
    lockfile = project / "package-lock.json"
    marker = project / "node_modules" / ".varde-lock-sha256"
    if not lockfile.is_file() or not marker.is_file():
        return False
    digest = hashlib.sha256(lockfile.read_bytes()).hexdigest()
    return marker.read_text().strip() == digest


def ensure_npm_prerequisites() -> int:
    for relative in NPM_PROJECTS:
        project = ROOT / relative
        if not npm_lock_is_current(project):
            marker = project / "node_modules" / ".varde-lock-sha256"
            marker.unlink(missing_ok=True)
            command = ["npm", "ci", "--offline", "--ignore-scripts"]
            command.extend(["--prefix", str(project)])
            result = subprocess.run(command, cwd=ROOT, check=False)  # noqa: S603
            if result.returncode:
                print(
                    f"Could not install {relative} dependencies offline. "
                    "Check the npm cache or restore network access.",
                    file=sys.stderr,
                )
                return result.returncode
            digest = hashlib.sha256(
                (project / "package-lock.json").read_bytes()
            ).hexdigest()
            (project / "node_modules" / ".varde-lock-sha256").write_text(digest + "\n")
    result = subprocess.run(  # noqa: S603
        ["npm", "run", "build", "--prefix", str(ROOT / "runner/ui")],  # noqa: S607
        cwd=ROOT,
        check=False,
    )
    if result.returncode:
        return result.returncode
    for command in (
        ["bash", str(ROOT / "runner/scripts/install-webkit-browsers.sh")],
        ["npm", "run", "check", "--prefix", str(ROOT / "runner/ui")],
    ):
        result = subprocess.run(command, cwd=ROOT, check=False)  # noqa: S603
        if result.returncode:
            return result.returncode
    return result.returncode


def load_test_environment() -> None:
    command = 'source "$1/core/scripts/test-env.sh" && export UV_OFFLINE=1 && env -0'
    result = subprocess.run(  # noqa: S603
        ["bash", "-c", command, "test-baseline", str(ROOT)],  # noqa: S607
        check=True,
        stdout=subprocess.PIPE,
    )
    for item in result.stdout.split(b"\0"):
        if item:
            key, value = item.split(b"=", 1)
            os.environ[os.fsdecode(key)] = os.fsdecode(value)


def run_command(command: list[str], cwd: Path, timeout: int) -> tuple[int, str, bool]:
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=cwd,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # macOS answers EPERM when the group holds only exited processes.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
            if process.poll() is None:
                process.wait()
        output.seek(0)
        return process.returncode, output.read().decode(errors="replace"), timed_out


def run() -> int:
    if "--install-prerequisites" in sys.argv[1:]:
        return ensure_npm_prerequisites()
    npm_status = ensure_npm_prerequisites()
    if npm_status:
        return npm_status
    load_test_environment()
    try:
        jobs = test_jobs(os.environ)
    except ValueError as exc:
        print(f"{exc}.", file=sys.stderr)
        return 2
    sync = subprocess.run(
        ["uv", "sync", "--locked", "--offline", "--all-packages", "--all-groups"],  # noqa: S607
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if sync.returncode:
        print(sync.stdout, end="", file=sys.stderr)
        return sync.returncode

    timeouts: dict[str, int] = {}
    for module in MODULES:
        try:
            timeouts[module] = module_timeout_seconds(module, os.environ)
        except ValueError as exc:
            print(f"{exc}.", file=sys.stderr)
            return 2

    def run_module(module: str) -> ModuleResult:
        returncode, output, timed_out = run_command(
            pytest_command(module), ROOT, timeouts[module]
        )
        return ModuleResult(module, returncode, output, timed_out, timeouts[module])

    with ThreadPoolExecutor(max_workers=jobs) as executor:
        results = list(executor.map(run_module, MODULES))
    summary = aggregate_results(results)
    for result in results:
        module = result.module
        output = result.output
        timed_out = result.timed_out
        timeout = result.timeout
        if timed_out:
            print(output, end="")
            print(
                f"{module}: failed (timed out after {timeout}s)",
                file=sys.stderr,
            )
            continue
        reason = crash_reason(result.returncode, output)
        if reason:
            print(output, end="")
            print(f"{module}: {reason}:", file=sys.stderr)
            continue
        module_failures = parse_failures(output)
        if module_failures:
            print(output, end="")

    for failure in sorted(summary.failures):
        print(f"FAILED {failure}")
    print(f"SKIPPED {summary.skips} tests")
    for module, detail in summary.skip_details:
        print(f"{module}: {detail}")
    for module in summary.failed_modules:
        print(f"FAILED MODULE {module}")
    return 1 if has_failures(summary.failures, summary.failed_modules) else 0


if __name__ == "__main__":
    raise SystemExit(run())
