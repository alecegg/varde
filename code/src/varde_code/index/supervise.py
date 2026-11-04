"""Install and start a per-repository user service for the index watcher."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

from varde_core.paths import varde_config_dir

from varde_code.index.paths import fnv1a64

READY_TIMEOUT = 30.0
JOB_PREFIX = "varde-code-py-"


def service_name(repo: Path) -> str:
    """Return the Python-specific supervisor label for a repository."""
    digest = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:16]
    return f"{JOB_PREFIX}{digest}"


def service_path(
    repo: Path, *, home: Path | None = None, system: str | None = None
) -> Path:
    home = home or Path(os.environ["HOME"])
    system = system or platform.system()
    name = service_name(repo)
    if system == "Darwin":
        return home / "Library" / "LaunchAgents" / f"{name}.plist"
    if system == "Linux":
        return home / ".config" / "systemd" / "user" / f"{name}.service"
    raise RuntimeError(f"watcher supervision is unsupported on {system}")


def _registry_dir() -> Path:
    return varde_config_dir() / "code" / "watch-services-py"


def _watch_set_id(repos: list[Path]) -> str:
    paths = "\n".join(sorted(str(repo.resolve()) for repo in repos))
    return f"{fnv1a64(paths.encode()):016x}"


def list_instances() -> list[dict[str, object]]:
    instances: list[dict[str, object]] = []
    registry = _registry_dir()
    if not registry.is_dir():
        return instances
    for record in sorted(registry.glob("*.json")):
        try:
            repo = Path(json.loads(record.read_text(encoding="utf-8")))
        except OSError, ValueError, TypeError:
            continue
        registered = service_path(repo).is_file()
        active, ownership_error = _service_state(repo)
        index_ready = _python_index_exists(repo)
        instances.append(
            {
                "pid": 0,
                "registered": registered,
                "alive": active,
                "ready": active is True and index_ready,
                "index_ready": index_ready,
                "repos": [str(repo)],
                "lock_path": "",
                "changed_paths": [],
                **({"ownership_error": ownership_error} if ownership_error else {}),
            }
        )
    return instances


def _python_index_exists(repo: Path) -> bool:
    from .paths import repo_db_path

    return repo_db_path(repo).is_file()


def _service_state(repo: Path) -> tuple[bool | None, str | None]:
    system = platform.system()
    name = service_name(repo)
    try:
        if system == "Darwin":
            uid = _run(["id", "-u"])
            if uid.returncode:
                return None, f"id -u failed: {uid.stderr.strip()}"
            result = _run(["launchctl", "print", f"gui/{uid.stdout.strip()}/{name}"])
            absent = ("could not find service", "service not found", "no such process")
        elif system == "Linux":
            result = _run(["systemctl", "--user", "is-active", f"{name}.service"])
            absent = ("not loaded", "not found", "does not exist", "inactive", "failed")
        else:
            return None, f"host supervision is unsupported on {system}"
    except OSError as error:
        return None, f"inspecting watcher service: {error}"
    if result.returncode == 0:
        return True, None
    output = f"{result.stdout}{result.stderr}".lower()
    if any(message in output for message in absent):
        return False, None
    return None, f"service inspection failed: {output.strip()}"


def _stop_service(repo: Path) -> None:
    system = platform.system()
    if system == "Darwin":
        uid = _run(["id", "-u"])
        if uid.returncode:
            raise RuntimeError("id -u failed")
        result = _run(
            ["launchctl", "bootout", f"gui/{uid.stdout.strip()}/{service_name(repo)}"]
        )
        missing = ("could not find service", "service not found", "no such process")
        command = "launchctl bootout"
    elif system == "Linux":
        result = _run(
            ["systemctl", "--user", "disable", "--now", f"{service_name(repo)}.service"]
        )
        missing = ("not loaded", "not found", "does not exist")
        command = "systemctl --user disable"
    else:
        raise RuntimeError(f"watcher supervision is unsupported on {system}")
    output = f"{result.stdout}{result.stderr}"
    if result.returncode and not any(value in output.lower() for value in missing):
        raise RuntimeError(f"{command} failed: {output.strip()}")


def stop(repos: list[Path]) -> dict[str, object]:
    canonical = [repo.resolve() for repo in repos]
    if len(canonical) == 1 and service_path(canonical[0]).is_file():
        repo = canonical[0]
        _stop_service(repo)
        service_path(repo).unlink(missing_ok=True)
        (_registry_dir() / f"{service_name(repo)}.json").unlink(missing_ok=True)
        return {"pid": 0, "repos": [str(repo)], "stopped": False}
    # Keep the diagnostic path stable with the shared watch CLI contract. Python
    # actions never read or mutate this Rust-owned lock directory.
    lock_path = (
        _registry_dir().parent / "watch-locks" / f"{_watch_set_id(canonical)}.lock"
    )
    raise RuntimeError(f"no watcher lock found for this repo set ({lock_path})")


def stop_all() -> list[dict[str, object]]:
    outcomes = []
    for instance in list_instances():
        repo_values = instance["repos"]
        if not isinstance(repo_values, list):
            continue
        repos = [Path(str(repo)) for repo in repo_values]
        pid = instance["pid"]
        if not isinstance(pid, (int, str, float, bytes, bytearray)):
            continue
        try:
            outcomes.append(stop(repos))
        except (OSError, RuntimeError) as error:
            outcomes.append(
                {
                    "pid": int(pid),
                    "repos": instance["repos"],
                    "stopped": False,
                    "error": str(error),
                }
            )
    return outcomes


def stop_and_remove_index(repo: Path) -> tuple[dict[str, object], bool]:
    from .paths import repo_db_path

    try:
        watcher = stop([repo])
        stop_error = None
    except (OSError, RuntimeError) as error:
        watcher = None
        stop_error = error
    db = repo_db_path(repo)
    try:
        db.unlink()
        removed = True
    except FileNotFoundError:
        removed = False
    except OSError as error:
        if stop_error:
            raise RuntimeError(
                f"stopping watcher: {stop_error}; removing code index: {error}"
            ) from error
        raise RuntimeError(f"removing code index {db}: {error}") from error
    with contextlib.suppress(OSError):
        db.with_name("source-root").unlink(missing_ok=True)
    if stop_error:
        raise RuntimeError(f"stopping watcher: {stop_error}") from stop_error
    return watcher or {}, removed


def _definition(repo: Path, binary: Path, system: str) -> str:
    label = service_name(repo)
    if system == "Darwin":
        import plistlib

        payload = {
            "Label": label,
            "ProgramArguments": [str(binary), "setup", "watch", "--repo", str(repo)],
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},
        }
        return plistlib.dumps(payload, fmt=plistlib.FMT_XML).decode()
    if system == "Linux":
        return (
            "[Unit]\nDescription=Varde Python code watcher\n[Service]\n"
            "Type=simple\n"
            f"ExecStart={_systemd_quote(str(binary))} setup watch --repo {_systemd_quote(str(repo))}\n"
            "Restart=on-failure\nRestartSec=2\n[Install]\nWantedBy=default.target\n"
        )
    raise RuntimeError(f"watcher supervision is unsupported on {system}")


def _systemd_quote(value: str) -> str:
    return (
        '"'
        + value.replace("%", "%%")
        .replace("$", "$$")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        + '"'
    )


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _wait_ready(repo: Path, name: str, system: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        if system == "Darwin":
            uid = _run(["id", "-u"])
            if uid.returncode:
                raise RuntimeError(f"id -u failed: {uid.stderr.strip()}")
            result = _run(["launchctl", "print", f"gui/{uid.stdout.strip()}/{name}"])
        else:
            result = _run(["systemctl", "--user", "is-active", f"{name}.service"])
        if result.returncode == 0:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"watcher service did not become ready for {repo}")
        time.sleep(0.25)


def ensure(
    repo: str | Path,
    *,
    binary: str | Path | None = None,
    timeout: float = READY_TIMEOUT,
    system: str | None = None,
) -> Path:
    """Install, start, and wait for the per-repository watcher service."""
    root = Path(repo).resolve(strict=True)
    if any(char in str(root) for char in "\n\r\0"):
        raise ValueError(
            "repository path contains an unsupported service-definition character"
        )
    system = system or platform.system()
    binary_path = str(binary) if binary is not None else shutil.which("varde")
    if binary_path is None:
        raise RuntimeError("could not locate the varde executable")
    executable = Path(binary_path)
    executable = executable.resolve()
    path = service_path(root, system=system)
    definition = _definition(root, executable, system)
    name = service_name(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != definition:
        path.write_text(definition)

    if system == "Darwin":
        uid = _run(["id", "-u"])
        if uid.returncode:
            raise RuntimeError(f"id -u failed: {uid.stderr.strip()}")
        domain = f"gui/{uid.stdout.strip()}"
        result = _run(["launchctl", "bootstrap", domain, str(path)])
        if result.returncode:
            result = _run(["launchctl", "kickstart", "-k", f"{domain}/{name}"])
        if result.returncode:
            raise RuntimeError(
                f"launchctl could not start watcher: {result.stderr.strip()}"
            )
    elif system == "Linux":
        for args in (
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", f"{name}.service"],
        ):
            result = _run(args)
            if result.returncode:
                raise RuntimeError(f"systemctl --user failed: {result.stderr.strip()}")
    else:
        raise RuntimeError(f"watcher supervision is unsupported on {system}")
    registry = _registry_dir()
    registry.mkdir(parents=True, exist_ok=True)
    (registry / f"{name}.json").write_text(json.dumps(str(root)), encoding="utf-8")
    _wait_ready(root, name, system, timeout)
    return path
