import os
import shutil
import time
from pathlib import Path

import pytest
from varde_code.quality_score import baseline_tests as bt

NEEDS_PYTHON = pytest.mark.skipif(not shutil.which("python3"), reason="python3 missing")


def make(tmp_path: Path, solution: str, test: str) -> tuple[Path, Path]:
    code = tmp_path / "code"
    code.mkdir()
    (code / "solution.py").write_text(solution)
    test_file = tmp_path / "test_solution.py"
    test_file.write_text(test)
    return code, test_file


TEST = (
    "import unittest\nfrom solution import add\n\n"
    "class T(unittest.TestCase):\n"
    "    def test_a(self): self.assertEqual(add(1, 2), 3)\n"
    "    def test_b(self): self.assertEqual(add(2, 2), 4)\n"
)


def test_plan_is_pure() -> None:
    plan = bt.plan_test("python", Path("/c"), Path("/t/test_solution.py"))
    assert plan.command == ("python3", "-m", "unittest", "test_solution")
    assert plan.copies == (
        (Path("/c/solution.py"), "solution.py"),
        (Path("/t/test_solution.py"), "test_solution.py"),
    )
    assert bt.plan_test("csharp", Path("/c"), Path("/t")).copies[0][1] == "Solution.cs"


def test_scrubbed_env_keeps_only_toolchain_vars() -> None:
    env = bt.scrubbed_env(
        {"PATH": "/bin", "FAKE_SECRET": "x", "HOME": "/real"}, Path("/h")
    )
    assert "FAKE_SECRET" not in env
    assert env["PATH"] == "/bin"
    assert env["HOME"] == "/h"


@NEEDS_PYTHON
def test_passing_sample(tmp_path: Path) -> None:
    code, test = make(tmp_path, "def add(a, b):\n    return a + b\n", TEST)
    result = bt.run_tests("python", code, test)
    assert result is not None and result.ok
    assert (result.passed, result.failed) == (2, 0)


@NEEDS_PYTHON
def test_failing_sample(tmp_path: Path) -> None:
    code, test = make(tmp_path, "def add(a, b):\n    return a * b\n", TEST)
    result = bt.run_tests("python", code, test)
    assert result is not None and not result.ok
    assert (result.passed, result.failed) == (1, 1)
    assert "AssertionError" in result.output_tail


@NEEDS_PYTHON
def test_env_is_scrubbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_SECRET", "hunter2")
    out = tmp_path / "seen.txt"
    test = (
        "import os, unittest\n"
        "class T(unittest.TestCase):\n"
        "    def test_a(self):\n"
        f"        open({str(out)!r}, 'w').write(repr(sorted(os.environ)))\n"
    )
    code, test_file = make(tmp_path, "", test)
    result = bt.run_tests("python", code, test_file)
    assert result is not None and result.ok
    seen = out.read_text()
    assert "FAKE_SECRET" not in seen
    assert "HOME" in seen


@NEEDS_PYTHON
def test_timeout_kills_child_and_its_subprocess(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    test = (
        "import subprocess, unittest\n"
        "class T(unittest.TestCase):\n"
        "    def test_a(self):\n"
        "        p = subprocess.Popen(['sleep', '300'])\n"
        f"        open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
        "        p.wait()\n"
    )
    code, test_file = make(tmp_path, "", test)
    started = time.monotonic()
    result = bt.run_tests("python", code, test_file, timeout=2)
    assert time.monotonic() - started < 30
    assert result is not None and not result.ok
    assert "timed out" in result.output_tail
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    pytest.fail("grandchild still alive")


@NEEDS_PYTHON
def test_output_is_capped(tmp_path: Path) -> None:
    test = (
        "import sys, unittest\n"
        "class T(unittest.TestCase):\n"
        "    def test_a(self):\n"
        "        sys.stdout.write('x' * (bt_n))\n"
        "        sys.stdout.flush()\n"
    ).replace("bt_n", str(1_000_000))
    code, test_file = make(tmp_path, "", test)
    result = bt.run_tests("python", code, test_file)
    assert result is not None
    assert len(result.output_tail.encode()) <= bt.OUTPUT_CAP_BYTES
    assert "Ran 1 test" in result.output_tail


def test_missing_toolchain_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bt.shutil, "which", lambda _name: None)
    assert not bt.toolchain_available("python")
    code, test = make(tmp_path, "", "")
    assert bt.run_tests("python", code, test) is None


def test_unknown_language_unavailable() -> None:
    assert not bt.toolchain_available("cobol")


def test_parse_counts() -> None:
    assert bt.parse_counts("typescript", "\u2139 pass 3\n\u2139 fail 1\n") == (3, 1)
    assert bt.parse_counts("csharp", "ok a\n2/3 passed\n") == (2, 1)
    assert bt.parse_counts(
        "python", "Ran 4 tests\n\nFAILED (failures=1, errors=1)"
    ) == (2, 2)
    assert bt.parse_counts("python", "nothing") is None
