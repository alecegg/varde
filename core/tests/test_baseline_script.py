import os
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "test-baseline.sh"
loader = SourceFileLoader("test_baseline_script", str(SCRIPT))
spec = spec_from_loader(loader.name, loader)
assert spec is not None
baseline_script = module_from_spec(spec)
loader.exec_module(baseline_script)


def test_any_failure_or_failed_module_requires_nonzero_exit():
    assert not baseline_script.has_failures(set(), [])
    assert baseline_script.has_failures({"tests::failure"}, [])
    assert baseline_script.has_failures(set(), ["core"])


def test_test_jobs_defaults_to_quarter_the_cpus_capped_at_two():
    assert baseline_script.test_jobs({}, 1) == 1
    assert baseline_script.test_jobs({}, 2) == 1
    assert baseline_script.test_jobs({}, 8) == 2
    assert baseline_script.test_jobs({}, 32) == 2


def test_test_jobs_accepts_positive_override_and_rejects_bad_values():
    assert baseline_script.test_jobs({"VARDE_TEST_JOBS": "1"}, 32) == 1
    assert baseline_script.test_jobs({"VARDE_TEST_JOBS": "6"}, 2) == 6
    for value in ("invalid", "0", "-1"):
        try:
            baseline_script.test_jobs({"VARDE_TEST_JOBS": value})
        except ValueError as exc:
            assert "positive integer" in str(exc)
        else:
            raise AssertionError(f"accepted job count {value!r}")


def test_pytest_command_uses_two_workers_for_selected_modules():
    for module in ("core", "code", "workflow", "data"):
        assert baseline_script.pytest_command(module)[-2:] == ["-n", "2"]
    assert "-n" not in baseline_script.pytest_command("runner")


def test_normal_pytest_command_runs_module_tests_with_xdist():
    command = baseline_script.pytest_command("workflow")
    assert command[:7] == [
        "uv",
        "run",
        "--offline",
        "--no-sync",
        "pytest",
        "workflow/tests",
        "-q",
    ]
    assert command[-2:] == ["-n", "2"]
    assert "-m" not in command


def test_aggregate_results_preserves_accounting_and_module_order():
    results = [
        baseline_script.ModuleResult("core", 1, SUMMARY, False, 300),
        baseline_script.ModuleResult("toz", 1, "", False, 300),
        baseline_script.ModuleResult(
            "code",
            0,
            "=== short test summary info ===\nSKIPPED [2] x.py:1: reason\n",
            False,
            300,
        ),
        baseline_script.ModuleResult("doc", -9, "partial output", True, 300),
    ]

    summary = baseline_script.aggregate_results(results)

    assert summary.failures == {
        "tests/test_a.py::test_x[a - b]",
        "tests/test_b.py::test_y",
        "tests/test_c.py",
    }
    assert summary.failed_modules == ["toz", "doc"]
    assert summary.skips == 5
    assert summary.skip_details == [
        ("core", "SKIPPED [3] tests/test_a.py:12: no ui"),
        ("code", "SKIPPED [2] x.py:1: reason"),
    ]


SUMMARY = """=== FAILURES ===
ERROR    logger:file.py:12 captured log noise
=== short test summary info ===
SKIPPED [3] tests/test_a.py:12: no ui
FAILED tests/test_a.py::test_x[a - b] - AssertionError: no
ERROR tests/test_b.py::test_y
FAILED tests/test_c.py - collection
"""


def test_parse_failures_reads_only_the_summary_and_keeps_parameter_ids():
    assert baseline_script.parse_failures(SUMMARY) == {
        "tests/test_a.py::test_x[a - b]",
        "tests/test_b.py::test_y",
        "tests/test_c.py",
    }


def test_count_skips_uses_the_grouped_multiplier():
    assert baseline_script.count_skips(SUMMARY) == 3


def test_skip_reasons_reads_grouped_entries_from_the_summary():
    assert baseline_script.skip_reasons(SUMMARY) == [
        "SKIPPED [3] tests/test_a.py:12: no ui"
    ]


def test_crash_reason_flags_crashes_even_with_failure_lines():
    assert baseline_script.crash_reason(0, "") is None
    assert baseline_script.crash_reason(1, SUMMARY) is None
    assert baseline_script.crash_reason(3, SUMMARY) == "pytest exited 3"
    assert baseline_script.crash_reason(1, "") is not None


def test_module_timeout_defaults_to_hang_guard_and_rejects_bad_values():
    assert baseline_script.module_timeout_seconds("core", {}) == 300
    assert baseline_script.module_timeout_seconds("runner", {}) == 1200
    assert (
        baseline_script.module_timeout_seconds(
            "core", {"VARDE_TEST_MODULE_TIMEOUT_SECONDS": "12"}
        )
        == 12
    )
    for value in ("soon", "0", "-1"):
        try:
            baseline_script.module_timeout_seconds(
                "core", {"VARDE_TEST_CORE_TIMEOUT_SECONDS": value}
            )
        except ValueError as exc:
            assert "expected a positive integer" in str(exc)
        else:
            raise AssertionError(f"accepted invalid timeout {value!r}")


def test_ensure_npm_prerequisites_installs_missing_lockfiles_offline(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(baseline_script, "ROOT", tmp_path)
    for relative in baseline_script.NPM_PROJECTS:
        project = tmp_path / relative
        project.mkdir(parents=True)
        (project / "package-lock.json").write_text(relative)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "ci":
            project = Path(command[-1])
            (project / "node_modules").mkdir()
            assert not (project / "node_modules" / ".varde-lock-sha256").exists()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(baseline_script.subprocess, "run", run)

    assert baseline_script.ensure_npm_prerequisites() == 0
    assert baseline_script.ensure_npm_prerequisites() == 0
    installs = [call for call in calls if call[1] == "ci"]
    assert len(installs) == len(baseline_script.NPM_PROJECTS)
    assert all("--offline" in call for call in installs)
    assert all("--ignore-scripts" in call for call in installs)
    checks = [call for call in calls if call[1:3] == ["run", "check"]]
    assert len(checks) == 2
    ui_steps = [
        call[1:3] for call in calls if call[1:3] in (["run", "build"], ["run", "check"])
    ]
    assert ui_steps == [["run", "build"], ["run", "check"]] * 2


def test_ensure_npm_prerequisites_fails_when_ui_check_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline_script, "ROOT", tmp_path)
    monkeypatch.setattr(baseline_script, "npm_lock_is_current", lambda _project: True)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        status = 1 if command[1:3] == ["run", "check"] else 0
        return subprocess.CompletedProcess(command, status)

    monkeypatch.setattr(baseline_script.subprocess, "run", run)

    assert baseline_script.ensure_npm_prerequisites() == 1
    npm_commands = [call[1:3] for call in calls if call[0] == "npm"]
    assert npm_commands == [["run", "build"], ["run", "check"]]


def test_ensure_npm_prerequisites_does_not_write_marker_after_failed_install(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(baseline_script, "ROOT", tmp_path)
    project = tmp_path / baseline_script.NPM_PROJECTS[0]
    (project / "node_modules").mkdir(parents=True)
    (project / "package-lock.json").write_text("lock")
    marker = project / "node_modules" / ".varde-lock-sha256"
    marker.write_text("old marker")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(baseline_script.subprocess, "run", run)

    assert baseline_script.ensure_npm_prerequisites() == 1
    assert not marker.exists()
    assert calls[0][1:4] == ["ci", "--offline", "--ignore-scripts"]


def test_run_command_kills_process_group_on_timeout(tmp_path):
    child_pid_file = tmp_path / "grandchild.pid"
    grandchild = "import time; time.sleep(30)"
    parent = (
        "import subprocess, sys, time; "
        f"child = subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        f"open({str(child_pid_file)!r}, 'w').write(str(child.pid)); "
        "print('started', flush=True); time.sleep(30)"
    )
    returncode, output, timed_out = baseline_script.run_command(
        [
            sys.executable,
            "-c",
            parent,
        ],
        tmp_path,
        timeout=1,
    )

    assert timed_out
    assert returncode != 0
    assert output == "started\n"
    child_pid = int(child_pid_file.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"grandchild process {child_pid} is still alive")


def test_run_reports_a_timed_out_module_and_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(baseline_script, "MODULES", ("core",))
    monkeypatch.setattr(baseline_script, "ensure_npm_prerequisites", lambda: 0)
    monkeypatch.setattr(baseline_script, "load_test_environment", lambda: None)
    monkeypatch.setattr(
        baseline_script.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", None),
    )
    monkeypatch.setattr(
        baseline_script, "run_command", lambda *args: (None, "partial output\n", True)
    )
    monkeypatch.setattr(sys, "argv", ["test-baseline.sh"])

    assert baseline_script.run() == 1
    assert "core: failed (timed out after" in capsys.readouterr().err
