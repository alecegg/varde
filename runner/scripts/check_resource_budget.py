"""Check isolated runner resource budgets.

Run from the repository root with:
    uv run python runner/scripts/check_resource_budget.py

The check uses a temporary working tree, isolated runner configuration/state,
and no agent processes. It opens a dashboard page and /events stream by default;
pass --no-dashboard-client for a runner-only idle measurement. Pass
--fixture-dir with a working tree, --git-repo with its source repo, and
--config-file with a credential-free runner TOML to measure a real-shape
fixture. SQLite databases are snapshotted with SQLite backup; file-backed
mailbox data is copied while token file contents are omitted. The plan index is
rebased to copied paths and file metadata. CPU includes the process group; Git
status subprocesses are counted during the measurement window.
"""

from __future__ import annotations

import argparse
import http.client
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from varde_runner.config import default_toml

STARTUP_LIMIT_SECONDS = 5.0
IDLE_CPU_LIMIT_PERCENT = 10.0  # interim gate
IDLE_CPU_TARGET_PERCENT = 2.0  # reported, non-gating
IDLE_WARMUP_SECONDS = 30
IDLE_MEASURE_SECONDS = 60
RSS_LIMIT_MB = 256.0
PS_COMMAND = shutil.which("ps") or "/bin/ps"
_PROCESS_CPU_MAX: dict[int, float] = {}
PLAN_COUNT = 100
FILES_PER_PLAN = 77
PLAN_READS_REFRESH_SECONDS = 60
MONITOR_CYCLE_SECONDS = 30
MONITOR_CYCLE_CPU_LIMIT_PERCENT = 0.3


def _populate_plan_fixture(working: Path) -> None:
    for plan_number in range(PLAN_COUNT):
        plan_dir = working / "plans" / f"budget-{plan_number:03d}"
        notes = plan_dir / "notes"
        notes.mkdir(parents=True)
        (plan_dir / "plan.md").write_text(
            f"---\nid: budget-{plan_number:03d}\nstatus: active\n"
            "assigned_to: budget-check\n---\n",
            encoding="utf-8",
        )
        for file_number in range(FILES_PER_PLAN):
            (notes / f"note-{file_number:03d}.md").write_text(
                "Synthetic plan note for the resource budget check.\n",
                encoding="utf-8",
            )


def _rss_mb(pid: int) -> float:
    value = subprocess.check_output(  # noqa: S603 - fixed system ps command
        [PS_COMMAND, "-p", str(pid), "-o", "rss="], text=True
    ).strip()
    return int(value) / 1024


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _cpu_time_seconds(value: str) -> float:
    match = re.fullmatch(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", value)
    if match is None:
        raise RuntimeError(f"could not parse process CPU time: {value!r}")
    days, hours, minutes, seconds = match.groups()
    return (
        int(days or 0) * 86_400
        + int(hours or 0) * 3_600
        + int(minutes or 0) * 60
        + float(seconds)
    )


def _process_cpu_seconds(pid: int) -> float:
    output = subprocess.check_output(  # noqa: S603 - fixed system ps command
        [PS_COMMAND, "-p", str(pid), "-o", "time="], text=True
    ).strip()
    return _cpu_time_seconds(output)


def _process_group_cpu_seconds(process_group: int) -> float:
    output = subprocess.check_output(  # noqa: S603 - fixed system ps command
        [PS_COMMAND, "-axo", "pgid=,pid=,time="], text=True
    )
    current: dict[int, float] = {}
    for line in output.splitlines():
        fields = line.split(None, 2)
        if len(fields) != 3 or fields[0] != str(process_group):
            continue
        current[int(fields[1])] = _cpu_time_seconds(fields[2])
    for pid, cpu_seconds in current.items():
        _PROCESS_CPU_MAX[pid] = max(_PROCESS_CPU_MAX.get(pid, 0.0), cpu_seconds)
    return sum(_PROCESS_CPU_MAX.values())


def _copy_fixture(fixture: Path, working: Path) -> None:
    plans = fixture / "plans"
    if not plans.is_dir():
        raise ValueError(f"fixture has no plans directory: {fixture}")
    shutil.copytree(plans, working / "plans")
    _copy_sqlite_tree(
        fixture / ".cache" / "dashboard", working / ".cache" / "dashboard"
    )
    _copy_sqlite_tree(fixture / ".cache", working / ".cache", exclude={"dashboard"})
    _copy_file_mailbox(fixture / ".cache" / "inbox", working / ".cache" / "inbox")
    registry = fixture / ".cache" / "dashboard" / "sessions" / "registry.json"
    if registry.is_file():
        target = working / ".cache" / "dashboard" / "sessions" / "registry.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(registry, target)
    _rebase_plan_index(fixture, working)


def _copy_file_mailbox(source: Path, target: Path) -> None:
    if not source.is_dir():
        return
    for directory, child_dirs, files in os.walk(source):
        source_dir = Path(directory)
        relative_dir = source_dir.relative_to(source)
        target_dir = target / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            source_file = source_dir / name
            target_file = target_dir / name
            if "tokens" in relative_dir.parts:
                target_file.touch()
            else:
                shutil.copy2(source_file, target_file)
        for name in child_dirs:
            (target_dir / name).mkdir(exist_ok=True)


def _copy_sqlite_tree(
    source: Path, target: Path, *, exclude: set[str] | None = None
) -> None:
    if not source.is_dir():
        return
    excluded = exclude or set()
    for database in source.rglob("*.sqlite3"):
        relative = database.relative_to(source)
        if relative.parts[0] in excluded:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_uri = database.resolve().as_uri() + "?mode=ro"
        with (
            sqlite3.connect(source_uri, uri=True) as source_db,
            sqlite3.connect(destination) as target_db,
        ):
            source_db.backup(target_db)


def _rebase_plan_index(fixture: Path, working: Path) -> None:
    index = working / ".cache" / "plans-read-index.sqlite3"
    if not index.is_file():
        return
    old_root = str((fixture / "plans").resolve())
    new_root = str((working / "plans").resolve())
    with sqlite3.connect(index) as db:
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        path_columns = {
            "directories": ("path",),
            "plans": ("path",),
            "tasks": ("path", "plan_path"),
            "invalid_artifacts": ("path", "plan_path"),
            "reviews": ("plan_path",),
            "task_notes": ("task_path",),
            "plan_activity": ("plan_path", "latest_path"),
        }
        for table, columns in path_columns.items():
            if table not in tables:
                continue
            available = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for column in columns:
                if column in available:
                    db.execute(
                        f"UPDATE {table} SET {column}=replace({column}, ?, ?) "  # noqa: S608
                        f"WHERE substr({column}, 1, length(?))=?",
                        (old_root, new_root, old_root, old_root),
                    )
        for table, path_column in (
            ("directories", "path"),
            ("plans", "path"),
            ("tasks", "path"),
            ("invalid_artifacts", "path"),
            ("reviews", "plan_path"),
            ("task_notes", "task_path"),
        ):
            if table not in tables:
                continue
            available = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            stat_columns = sorted(
                key
                for key in ("dev", "ino", "mtime_ns", "ctime_ns", "size", "inode")
                if key in available
            )
            for (path,) in db.execute(f"SELECT {path_column} FROM {table}"):  # noqa: S608 - table and column are fixed above
                if not stat_columns:
                    continue
                try:
                    status = Path(path).stat()
                except OSError:
                    continue
                values = {
                    "dev": status.st_dev,
                    "ino": status.st_ino,
                    "mtime_ns": status.st_mtime_ns,
                    "ctime_ns": status.st_ctime_ns,
                    "size": status.st_size,
                    "inode": status.st_ino,
                }
                assignments = ", ".join(f"{column}=?" for column in stat_columns)
                db.execute(
                    f"UPDATE {table} SET {assignments} WHERE {path_column}=?",  # noqa: S608
                    (*[values[column] for column in stat_columns], path),
                )


def _attach_worktree_registry(working: Path, git_repo: Path | None) -> None:
    if git_repo is None:
        return
    git_metadata = git_repo.resolve() / ".git"
    if not git_metadata.exists():
        raise ValueError(f"repository has no .git metadata: {git_repo}")
    (working / ".git").symlink_to(
        git_metadata, target_is_directory=git_metadata.is_dir()
    )


def _registered_worktrees(git_repo: Path | None) -> int:
    if git_repo is None:
        return 0
    output = subprocess.check_output(  # noqa: S603 - fixed Git read-only query
        [
            shutil.which("git") or "git",
            "-C",
            str(git_repo),
            "worktree",
            "list",
            "--porcelain",
        ],
        text=True,
    )
    return sum(line.startswith("worktree ") for line in output.splitlines())


def _install_git_counter(base: Path, git_status_log: Path) -> Path:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required for the resource budget check")
    directory = base / "bin"
    directory.mkdir()
    wrapper = directory / "git"
    real_git = str(Path(git).resolve())
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "if sys.argv[-2:] == ['status', '--porcelain']:\n"
        f"    open({str(git_status_log)!r}, 'a').write('status\\n')\n"
        f"os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return directory


def _open_dashboard(port: int) -> http.client.HTTPConnection:
    page = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    page.request("GET", "/")
    response = page.getresponse()
    location = response.getheader("location")
    response.read()
    page.close()
    if location:
        path = location.partition("?")[0]
        page = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        page.request("GET", path)
        response = page.getresponse()
        response.read()
        page.close()

    events = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    events.request("GET", "/events", headers={"Accept": "text/event-stream"})
    response = events.getresponse()
    if response.status != 200:
        events.close()
        raise RuntimeError(f"dashboard event stream returned HTTP {response.status}")
    return events


def _get(port: int, path: str) -> tuple[int, float]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    started = time.monotonic()
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
        return response.status, time.monotonic() - started
    finally:
        connection.close()


def _run(  # noqa: C901, PLR0912, PLR0915 - process cleanup stays local
    fixture: Path | None = None,
    git_repo: Path | None = None,
    config_file: Path | None = None,
    dashboard_client: bool = True,
) -> int:
    with tempfile.TemporaryDirectory(prefix="varde-runner-budget-") as temporary:
        base = Path(temporary)
        working = (base / "working").resolve()
        config = base / "config"
        state = base / "state"
        home = base / "home"
        for path in (config, state, home):
            path.mkdir(parents=True, exist_ok=True)
        if fixture is None:
            (working / "plans").mkdir(parents=True)
            _populate_plan_fixture(working)
        else:
            _copy_fixture(fixture, working)
        _attach_worktree_registry(working, git_repo)
        config_contents = (
            config_file.read_text(encoding="utf-8")
            if config_file is not None
            else default_toml()
        )
        (config / "runner.toml").write_text(config_contents, encoding="utf-8")
        port = _free_port()
        status_log = base / "git-status.log"
        wrapper_dir = _install_git_counter(base, status_log)
        registered_worktrees = _registered_worktrees(git_repo)
        env = {
            "PATH": os.pathsep.join(
                (str(wrapper_dir), os.environ.get("PATH", "/usr/bin:/bin"))
            ),
            "HOME": str(home),
            "TMPDIR": str(base),
            "VARDE_WORKING_DIR": str(working),
            "VARDE_RUNNER_CONFIG_DIR": str(config),
            "VARDE_RUNNER_STATE_DIR": str(state),
            "VARDE_RUNNER_RELAY": "data",
            "VARDE_PLANS_BACKEND": "sqlite",
            "VARDE_BUDGET_STATUS_LOG": str(status_log),
        }
        command = [
            sys.executable,
            "-X",
            "faulthandler",
            "-c",
            "from varde_runner import main; main()",
            "serve",
            "--port",
            str(port),
        ]
        started = time.monotonic()
        process = subprocess.Popen(  # noqa: S603 - executable and arguments are fixed
            command,
            cwd=Path.cwd(),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        events = None
        try:
            deadline = started + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"runner exited during startup: {process.returncode}"
                    )
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise TimeoutError("runner did not listen within 30 seconds")
            time_to_bind = time.monotonic() - started
            http_status, http_elapsed = _get(port, "/api/relay")
            time_to_ready = time.monotonic() - started
            if http_status >= 500:
                raise RuntimeError(f"runner readiness returned HTTP {http_status}")
            agents_status, agents_elapsed = _get(port, "/api/agents")
            if agents_status >= 500:
                raise RuntimeError(f"agents route returned HTTP {agents_status}")
            relay_status, relay_elapsed = _get(port, "/api/relay")
            if dashboard_client:
                events = _open_dashboard(port)
            time.sleep(IDLE_WARMUP_SECONDS)
            monitor_cpu_start = _process_cpu_seconds(process.pid)
            monitor_tree_cpu_start = _process_group_cpu_seconds(process.pid)
            monitor_started = time.monotonic()
            monitor_requests = []
            for path in ("/api/agents", "/api/agents", "/api/agents", "/api/relay"):
                status, elapsed = _get(port, path)
                if status >= 500:
                    raise RuntimeError(f"monitor route {path} returned HTTP {status}")
                monitor_requests.append((path, elapsed))
            monitor_cpu_seconds = _process_cpu_seconds(process.pid) - monitor_cpu_start
            monitor_tree_cpu_seconds = (
                _process_group_cpu_seconds(process.pid) - monitor_tree_cpu_start
            )
            monitor_elapsed = time.monotonic() - monitor_started
            monitor_cpu_percent = 100 * monitor_cpu_seconds / MONITOR_CYCLE_SECONDS
            cpu_start = _process_cpu_seconds(process.pid)
            tree_cpu_start = _process_group_cpu_seconds(process.pid)
            status_start = (
                len(status_log.read_text().splitlines()) if status_log.exists() else 0
            )
            measure_start = time.monotonic()
            rss_values = []
            for _ in range(IDLE_MEASURE_SECONDS):
                time.sleep(1)
                if process.poll() is not None:
                    raise RuntimeError("runner exited during idle measurement")
                rss_values.append(_rss_mb(process.pid))
            elapsed = time.monotonic() - measure_start
            cpu_percent = (
                100 * (_process_cpu_seconds(process.pid) - cpu_start) / elapsed
            )
            tree_cpu_percent = (
                100
                * (_process_group_cpu_seconds(process.pid) - tree_cpu_start)
                / elapsed
            )
            status_count = (
                len(status_log.read_text().splitlines()) - status_start
                if status_log.exists()
                else 0
            )
            max_status_count = int(elapsed / PLAN_READS_REFRESH_SECONDS) + 1
            rss_max = max(rss_values)
            print(
                f"tcp_bind_s={time_to_bind:.3f} "
                f"http_ready_s={time_to_ready:.3f} "
                f"(limit < {STARTUP_LIMIT_SECONDS:.1f})"
            )
            print(
                f"api_agents_first_ms={agents_elapsed * 1000:.1f} "
                f"status={agents_status} api_relay_ms={relay_elapsed * 1000:.1f} "
                f"status={relay_status} readiness_relay_ms={http_elapsed * 1000:.1f}"
            )
            print(
                "monitor_cycle="
                + ",".join(
                    f"{path}:{elapsed * 1000:.2f}ms"
                    for path, elapsed in monitor_requests
                )
                + f" wall_s={monitor_elapsed:.3f} "
                + f"runner_cpu_ms={monitor_cpu_seconds * 1000:.2f} "
                + f"process_tree_cpu_ms={monitor_tree_cpu_seconds * 1000:.2f} "
                + f"cpu_percent_at_{MONITOR_CYCLE_SECONDS}s="
                + f"{monitor_cpu_percent:.3f} "
                + f"(limit < {MONITOR_CYCLE_CPU_LIMIT_PERCENT:.1f})"
            )
            print(
                f"runner_idle_cpu_percent={cpu_percent:.3f} over {elapsed:.1f}s "
                f"(interim limit < {IDLE_CPU_LIMIT_PERCENT:.1f}); "
                f"process_tree_cpu_percent={tree_cpu_percent:.3f}"
            )
            print(
                f"git_status_spawns={status_count} "
                f"(limit <= {max_status_count} per {elapsed:.1f}s)"
            )
            if git_repo is not None:
                print(f"registered_worktrees={registered_worktrees}")
            print(f"rss_max_mb={rss_max:.1f} (limit < {RSS_LIMIT_MB:.0f})")
            if cpu_percent >= IDLE_CPU_TARGET_PERCENT:
                print(
                    f"WARNING: idle CPU {cpu_percent:.3f}% misses the "
                    f"{IDLE_CPU_TARGET_PERCENT:.1f}% budget target (non-gating)"
                )
            failures = []
            if time_to_ready >= STARTUP_LIMIT_SECONDS:
                failures.append("startup time")
            if cpu_percent >= IDLE_CPU_LIMIT_PERCENT:
                failures.append("idle CPU")
            if monitor_cpu_percent >= MONITOR_CYCLE_CPU_LIMIT_PERCENT:
                failures.append("monitor-cycle CPU")
            if rss_max >= RSS_LIMIT_MB:
                failures.append("RSS")
            if status_count > max_status_count:
                failures.append("Git status spawn count")
            if registered_worktrees and status_count == 0:
                failures.append("Git status was not exercised")
            if failures:
                print("FAILED: " + ", ".join(failures))
                return 1
            print("PASS: runner stays within resource budgets")
            return 0
        finally:
            if events is not None:
                events.close()
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help="copy plans and dashboard SQLite data from a working tree",
    )
    parser.add_argument(
        "--git-repo",
        type=Path,
        help="repository whose registered worktrees the runner should inspect",
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        help="credential-free runner TOML to use instead of the default config",
    )
    parser.add_argument(
        "--no-dashboard-client",
        action="store_true",
        help="measure idle runner without opening a dashboard page or /events stream",
    )
    args = parser.parse_args()
    raise SystemExit(
        _run(
            args.fixture_dir,
            args.git_repo,
            args.config_file,
            dashboard_client=not args.no_dashboard_client,
        )
    )
