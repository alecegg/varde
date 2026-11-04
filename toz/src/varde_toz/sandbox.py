"""Generate OS sandbox policy text for the Toz worker.

This module does not launch or enforce a sandbox. It mirrors the policy checks
and command/profile generation used by the Rust Toz implementation.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Policy:
    read_roots: tuple[Path, ...]
    write_roots: tuple[Path, ...]
    scratch_dir: Path
    network: bool = False
    env_allow: tuple[str, ...] = ()
    protected_roots: tuple[Path, ...] = ()


@dataclass(frozen=True)
class CheckedPolicy:
    read_roots: tuple[Path, ...]
    write_roots: tuple[Path, ...]
    scratch_dir: Path
    network: bool
    executable: Path
    cwd: Path
    protected_roots: tuple[Path, ...]


def _canonical_dir(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"sandbox path {path} is not a directory")
    return resolved


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _system_read_roots(platform: str) -> tuple[Path, ...]:
    if platform == "darwin":
        values = (
            "/System",
            "/usr",
            "/bin",
            "/sbin",
            "/Library",
            "/private/var/db/dyld",
            "/private/etc/ssl",
        )
    elif platform.startswith("linux"):
        values = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc/ssl", "/etc/pki")
    else:
        values = ()
    return tuple(Path(value) for value in values)


def check_policy(policy: Policy, executable: Path, cwd: Path) -> CheckedPolicy:
    """Resolve policy paths and reject access overlapping protected roots."""
    reads = tuple(_canonical_dir(path) for path in policy.read_roots)
    writes = tuple(_canonical_dir(path) for path in policy.write_roots)
    protected = tuple(path.resolve(strict=True) for path in policy.protected_roots)
    if not protected:
        raise ValueError("sandbox policy requires a protected store path")
    for root in protected:
        for system in _system_read_roots(sys.platform):
            if _under(root, system):
                raise ValueError(
                    f"protected store {root} is inside required system path {system}"
                )

    scratch = _canonical_dir(policy.scratch_dir)
    executable = executable.resolve(strict=True)
    if not executable.is_file():
        raise ValueError("worker executable must be a file")
    cwd = _canonical_dir(cwd)
    for granted in (*reads, *writes, scratch):
        for root in protected:
            if _under(granted, root) or _under(root, granted):
                raise ValueError(
                    f"sandbox access to {granted} overlaps protected store {root}"
                )
    if any(_under(executable, root) for root in protected):
        raise ValueError("worker executable is inside the protected store")
    if not any(_under(cwd, root) for root in (*reads, *writes, scratch)):
        raise ValueError(f"worker directory {cwd} is not permitted by sandbox policy")
    return CheckedPolicy(
        reads, writes, scratch, policy.network, executable, cwd, protected
    )


def _seatbelt_path(path: Path) -> str:
    value = os.fspath(path)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("control character in sandbox path")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def seatbelt_profile(policy: CheckedPolicy) -> str:
    """Return the Rust Seatbelt profile text for a checked policy."""
    profile = (
        "(version 1)\n(deny default)\n(allow process-exec*)\n(allow process-fork)\n"
        "(allow process-info* (target self))\n(allow sysctl-read)\n"
        '(allow file-read-metadata (subpath "/"))\n'
        '(allow file-read-data (literal "/"))\n'
    )
    reads = {
        Path(value)
        for value in (
            "/System",
            "/usr",
            "/bin",
            "/sbin",
            "/Library",
            "/private/var/db/dyld",
            "/private/etc/ssl",
        )
    }
    reads.update(policy.read_roots)
    reads.update(policy.write_roots)
    reads.update((policy.scratch_dir, policy.executable))
    for path in sorted(reads):
        profile += f"(allow file-read* (subpath {_seatbelt_path(path)}))\n"
    for path in ("/dev/null", "/dev/random", "/dev/urandom", "/dev/tty"):
        profile += f'(allow file-read* (literal "{path}"))\n'
    for path in (*policy.write_roots, policy.scratch_dir):
        profile += f"(allow file-write* (subpath {_seatbelt_path(path)}))\n"
    profile += (
        '(allow file-write* (literal "/dev/null"))\n'
        '(allow file-write* (literal "/dev/tty"))\n'
    )
    if policy.network:
        profile += "(allow network*)\n(allow mach-lookup)\n"
    for path in policy.protected_roots:
        profile += f"(deny file-read* file-write* (subpath {_seatbelt_path(path)}))\n"
    return profile


def bubblewrap_args(
    policy: CheckedPolicy, args: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """Return Bubblewrap arguments without executing Bubblewrap."""
    result = ["--unshare-all", "--die-with-parent", "--new-session"]
    if policy.network:
        result.append("--share-net")
    result.extend(("--tmpfs", "/", "--proc", "/proc", "--dev", "/dev"))
    reads = {
        Path(value)
        for value in ("/usr", "/bin", "/sbin", "/lib", "/lib64")
        if Path(value).exists()
    }
    if policy.network:
        reads.update(
            Path(value)
            for value in (
                "/etc/resolv.conf",
                "/etc/hosts",
                "/etc/nsswitch.conf",
                "/etc/ssl",
                "/etc/pki",
            )
            if Path(value).exists()
        )
    reads.update(policy.read_roots)
    reads.add(policy.executable)
    writes = set(policy.write_roots)
    writes.add(policy.scratch_dir)
    dirs = {
        parent
        for path in reads | writes
        for parent in path.parents
        if parent != Path("/")
    }
    for directory in sorted(dirs, key=lambda value: (len(value.parts), value)):
        result.extend(("--dir", os.fspath(directory)))
    for path in sorted(reads - writes):
        if any(path != other and _under(path, other) for other in reads) or any(
            _under(path, other) for other in writes
        ):
            continue
        result.extend(("--ro-bind", os.fspath(path), os.fspath(path)))
    for path in sorted(writes):
        result.extend(("--bind", os.fspath(path), os.fspath(path)))
    result.extend(
        ("--chdir", os.fspath(policy.cwd), "--", os.fspath(policy.executable), *args)
    )
    return tuple(result)
