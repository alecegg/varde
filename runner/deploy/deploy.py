#!/usr/bin/env python3
"""Deploy this checkout: atomic CLI swap, UI build, runner restart, endpoint checks.

Each step reports ok, warn, or fail on its own. The runner restart always runs,
even when the CLI step warns or fails, because the previous CLI stays in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER_COMMAND = ["uv", "run", "--project", str(ROOT / "runner"), "varde-runner"]
UI_STATIC = (
    ROOT / "runner" / "src" / "varde_runner" / "web" / "static" / "ui" / "index.html"
)
UI_SOURCES = (
    ROOT / "runner" / "ui" / "src",
    ROOT / "runner" / "ui" / "package-lock.json",
)
ENDPOINTS = ("/", "/api/orchestrators", "/api/needs-you-count", "/api/relay")
SMOKE_COMMANDS = (["--version"], ["plan", "--help"])
SERVE_PACKAGE = "varde-serve"
SERVE_SMOKE_COMMANDS = (["--version"],)


class StepWarning(Exception):
    """Raised by a step that finished but needs attention."""


@dataclass
class StepResult:
    name: str
    status: str
    detail: str
    seconds: float


def run_step(name: str, action: Callable[[], str]) -> StepResult:
    started = time.monotonic()
    try:
        status, detail = "ok", action()
    except StepWarning as warning:
        status, detail = "warn", str(warning)
    except Exception as error:  # noqa: BLE001 - A step must never skip the restart.
        status, detail = "fail", str(error)
    return StepResult(name, status, detail, time.monotonic() - started)


def release_name(commit: str, stamp: str) -> str:
    return f"{stamp}-{commit}"


def run_checked(command: list[str], env: dict[str, str] | None = None) -> str:
    done = subprocess.run(  # noqa: S603 - Runs locally assembled deploy commands.
        command, env=env, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-5:]
        raise RuntimeError(
            f"{' '.join(command[:3])} exited {done.returncode}: {' | '.join(tail)}"
        )
    return done.stdout.strip()


def install_release(release: Path, source: Path, package: str = "varde") -> Path:
    """Install `package` into a fresh private tool dir; return its executable."""
    env = {
        **os.environ,
        "UV_TOOL_DIR": str(release / "tools"),
        "UV_TOOL_BIN_DIR": str(release / "bin"),
    }
    run_checked(
        [
            "uv",
            "tool",
            "install",
            "--force",
            "--reinstall",
            "--from",
            str(source),
            package,
        ],
        env,
    )
    executable = release / "bin" / package
    if not executable.exists():
        raise RuntimeError(f"install produced no executable at {executable}")
    return executable


def _site_packages(release: Path, package: str = "varde") -> Path:
    library = release / "tools" / package / "lib"
    candidates = sorted(library.glob("python*/site-packages"))
    if len(candidates) != 1:
        raise RuntimeError(f"could not locate installed varde packages in {release}")
    return candidates[0]


def _workspace_packages(source: Path) -> list[Path]:
    workspace_root = next(
        (
            parent
            for parent in (source, *source.parents)
            if (parent / "pyproject.toml").is_file()
            and "workspace"
            in tomllib.loads((parent / "pyproject.toml").read_text(encoding="utf-8"))
            .get("tool", {})
            .get("uv", {})
        ),
        None,
    )
    if workspace_root is None:
        raise RuntimeError(f"could not locate uv workspace above {source}")
    workspace = tomllib.loads(
        (workspace_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    members = workspace["tool"]["uv"]["workspace"].get("members", [])
    packages = [
        package
        for member in members
        for package in sorted((workspace_root / member / "src").iterdir())
        if package.is_dir()
    ]
    if not packages:
        raise RuntimeError(f"no workspace packages found under {source}")
    return packages


def _source_files(package: Path) -> list[Path]:
    return sorted(
        file
        for file in package.rglob("*")
        if file.is_file()
        and "__pycache__" not in file.parts
        and "evals" not in file.relative_to(package).parts
        and file.suffix in {".py", ".pyi"}
    )


def verify_installed_sources(
    release: Path, source: Path = ROOT, tool: str = "varde"
) -> str:
    """Fail when built workspace Python sources differ from this checkout."""
    site_packages = _site_packages(release, tool)
    checked_files = 0
    stale: list[str] = []
    for package in _workspace_packages(source):
        installed = site_packages / package.name
        if not installed.is_dir():
            # Some workspace projects, such as the optional runner extra, are
            # not dependencies of the installed CLI tool.
            continue
        for source_file in _source_files(package):
            target = installed / source_file.relative_to(package)
            if not target.is_file():
                relative = source_file.relative_to(package)
                stale.append(f"{package.name}/{relative} (missing)")
                continue
            source_hash = hashlib.sha256(source_file.read_bytes()).digest()
            installed_hash = hashlib.sha256(target.read_bytes()).digest()
            checked_files += 1
            if source_hash != installed_hash:
                stale.append(f"{package.name}/{source_file.relative_to(package)}")
    if stale:
        summary = ", ".join(stale[:5])
        more = f" (+{len(stale) - 5} more)" if len(stale) > 5 else ""
        raise RuntimeError(f"installed workspace sources are stale: {summary}{more}")
    return f"verified {checked_files} workspace Python source files"


def smoke_test(
    executable: Path, commands: tuple[list[str], ...] = SMOKE_COMMANDS
) -> str:
    outputs = [run_checked([str(executable), *a]) for a in commands]
    return outputs[0].splitlines()[0] if outputs[0] else ""


def repoint(link: Path, target: Path) -> Path | None:
    """Atomically make `link` a symlink to `target`; return the previous target."""
    if link.exists() and not link.is_symlink():
        raise RuntimeError(f"{link} is not a symlink; refusing to replace it")
    previous = Path(os.readlink(link)) if link.is_symlink() else None
    link.parent.mkdir(parents=True, exist_ok=True)
    staged = link.with_name(f".{link.name}.new.{os.getpid()}")
    staged.unlink(missing_ok=True)
    staged.symlink_to(target)
    os.replace(staged, link)
    return previous


def swap_cli(  # noqa: PLR0913, PLR0917 - one flat deploy step per installed tool
    source: Path,
    releases: Path,
    link: Path,
    commit: str,
    stamp: str,
    package: str = "varde",
    smoke: tuple[list[str], ...] = SMOKE_COMMANDS,
) -> str:
    release = releases / release_name(commit, stamp)
    if release.exists():
        raise RuntimeError(f"release {release} already exists")
    try:
        executable = install_release(release, source, package)
        source_status = verify_installed_sources(release, source, package)
        version = smoke_test(executable, smoke)
    except OSError, RuntimeError:
        shutil.rmtree(release, ignore_errors=True)
        raise
    previous = repoint(link, executable)
    return f"{version}; {source_status}; previous target {previous}"


def prune_releases(releases: Path, keep: int, protected: set[Path]) -> list[Path]:
    """Remove all but the newest `keep` (at least 2) releases, never a protected one."""
    keep = max(keep, 2)
    if not releases.is_dir():
        return []
    ordered = sorted(
        (p for p in releases.iterdir() if p.is_dir()), key=lambda p: p.name
    )
    removable = ordered[: max(len(ordered) - keep, 0)]
    kept = {q.resolve() for q in protected}
    removed = [
        p for p in removable if not any(p.resolve() in (q, *q.parents) for q in kept)
    ]
    for path in removed:
        shutil.rmtree(path, ignore_errors=True)
    return removed


def ui_is_stale(
    static_index: Path = UI_STATIC, sources: tuple[Path, ...] = UI_SOURCES
) -> bool:
    if not static_index.exists():
        return True
    built = static_index.stat().st_mtime
    files = [
        f
        for s in sources
        for f in ([s] if s.is_file() else s.rglob("*"))
        if f.is_file()
    ]
    return any(f.stat().st_mtime > built for f in files)


def build_ui() -> str:
    if not ui_is_stale():
        return "up to date, skipped"
    run_checked(["npm", "ci", "--prefix", str(ROOT / "runner" / "ui")])
    run_checked(["npm", "run", "build", "--prefix", str(ROOT / "runner" / "ui")])
    return "built"


def fetch(url: str, timeout: float = 5.0) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - Loopback URL.
        return response.status, response.read()


def relay_state(port: int) -> str | None:
    """Return the relay state, or None when the relay is off or unreachable."""
    try:
        status, body = fetch(f"http://127.0.0.1:{port}/api/relay", timeout=2)
        data = json.loads(body)
    except OSError, ValueError:
        return None
    return data.get("state") if status == 200 and data.get("enabled") else None


def wait_until(
    check: Callable[[], bool], seconds: float, interval: float = 0.5
) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if check():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def wait_relay_idle(port: int, seconds: float) -> str:
    if relay_state(port) is None:
        return "relay off or runner down, nothing to wait for"
    if wait_until(lambda: relay_state(port) != "delivering", seconds):
        return "relay idle"
    raise StepWarning(f"relay still delivering after {seconds:g}s; restarting anyway")


def service(action: str) -> str:
    return run_checked([*RUNNER_COMMAND, "service", action]) or f"{action} sent"


def wait_runner_ready(port: int, seconds: float) -> str:
    url = f"http://127.0.0.1:{port}/api/orchestrators"

    def ready() -> bool:
        try:
            return fetch(url, timeout=1)[0] == 200
        except OSError:
            return False

    if wait_until(ready, seconds):
        return "ready"
    raise RuntimeError(f"runner not ready within {seconds:g}s")


def check_endpoints(port: int) -> str:
    timings, failures = [], []
    for path in ENDPOINTS:
        started = time.monotonic()
        try:
            status = fetch(f"http://127.0.0.1:{port}{path}")[0]
        except OSError as error:
            status = getattr(error, "code", 0)
        elapsed = time.monotonic() - started
        timings.append(f"{path} {status} {elapsed:.2f}s")
        if status != 200:
            failures.append(path)
    if failures:
        raise RuntimeError("; ".join(timings))
    return "; ".join(timings)


def git_commit() -> str:
    return run_checked(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"])


def format_results(results: list[StepResult]) -> str:
    lines = [
        f"{r.status.upper():5} {r.name:<16} {r.seconds:6.1f}s  {r.detail}"
        for r in results
    ]
    return "\n".join(lines)


def deploy(args: argparse.Namespace) -> int:
    results: list[StepResult] = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    protected: set[Path] = set()

    def record(name: str, action: Callable[[], str]) -> None:
        result = run_step(name, action)
        results.append(result)
        print(f"{result.status.upper():5} {name}: {result.detail}", flush=True)

    if not args.skip_cli:
        record(
            "cli-swap",
            lambda: swap_cli(
                ROOT / "app", args.releases, args.link, git_commit(), stamp
            ),
        )
        record("cli-prune", lambda: prune_step(args, protected))
    if not args.skip_serve:
        # varde-serve is a separate tool: the app cannot depend on it (same
        # level) and the PEX excludes it, so `varde serve` finds this link.
        record(
            "serve-swap",
            lambda: swap_cli(
                ROOT / "serve",
                args.serve_releases,
                args.serve_link,
                git_commit(),
                stamp,
                SERVE_PACKAGE,
                SERVE_SMOKE_COMMANDS,
            ),
        )
        record("serve-prune", lambda: prune_serve_step(args))
    if not args.skip_ui:
        record("ui-build", build_ui)
    if not args.skip_runner:
        record("relay-wait", lambda: wait_relay_idle(args.port, args.relay_wait))
        record("runner-stop", lambda: service("stop"))
        record("runner-start", lambda: service("start"))
        record("runner-ready", lambda: wait_runner_ready(args.port, args.ready_wait))
        record("endpoints", lambda: check_endpoints(args.port))
    print("\n" + format_results(results))
    return 1 if any(r.status == "fail" for r in results) else 0


def prune_step(args: argparse.Namespace, protected: set[Path]) -> str:
    if args.link.is_symlink():
        protected.add(Path(os.readlink(args.link)).resolve())
    removed = prune_releases(args.releases, args.keep, protected)
    return f"kept newest {args.keep}, removed {len(removed)}"


def prune_serve_step(args: argparse.Namespace) -> str:
    protected = set()
    if args.serve_link.is_symlink():
        protected.add(Path(os.readlink(args.serve_link)).resolve())
    removed = prune_releases(args.serve_releases, args.keep, protected)
    return f"kept newest {args.keep}, removed {len(removed)}"


def parser() -> argparse.ArgumentParser:
    home = Path.home()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--releases", type=Path, default=home / ".local/share/varde/cli-releases"
    )
    p.add_argument("--link", type=Path, default=home / ".local/bin/varde")
    p.add_argument(
        "--serve-releases",
        type=Path,
        default=home / ".local/share/varde/serve-releases",
    )
    p.add_argument("--serve-link", type=Path, default=home / ".local/bin/varde-serve")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--keep", type=int, default=3, help="releases to keep when pruning")
    p.add_argument(
        "--relay-wait", type=float, default=30.0, help="seconds to wait for the relay"
    )
    p.add_argument(
        "--ready-wait", type=float, default=60.0, help="seconds to wait for the runner"
    )
    p.add_argument("--skip-cli", action="store_true")
    p.add_argument("--skip-serve", action="store_true")
    p.add_argument("--skip-ui", action="store_true")
    p.add_argument("--skip-runner", action="store_true")
    return p


if __name__ == "__main__":
    sys.exit(deploy(parser().parse_args()))
