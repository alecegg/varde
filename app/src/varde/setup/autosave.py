"""Scheduled commits and secret-scanned pushes for standalone Git stores."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from varde_toz.redact_toz import redact_capture

from .old_store import SetupError, check_old_store

DEFAULT_BRANCH = "main"
DEFAULT_MAX_FILE_MB = 50
TEST_PLIST_DIR = "VARDE_AUTOSAVE_TEST_PLIST_DIR"
TEST_LAUNCHCTL = "VARDE_AUTOSAVE_TEST_LAUNCHCTL"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="varde setup autosave",
        description=(
            "Schedule commits and secret-scanned pushes for a standalone Git store"
        ),
    )
    commands = parser.add_subparsers(dest="action", required=True)
    install = commands.add_parser(
        "install",
        help="Install the scheduled autosave job for an explicit standalone store",
    )
    _repo_arg(install)
    _branch_arg(install)
    install.add_argument(
        "--interval-minutes",
        type=int,
        default=30,
        help="Minutes between scheduled runs",
    )
    install.add_argument(
        "--max-file-mb", type=_nonnegative_int, default=DEFAULT_MAX_FILE_MB
    )
    install.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plist and launchctl commands without writing or running them",
    )
    uninstall = commands.add_parser(
        "uninstall", help="Remove the scheduled autosave job"
    )
    _repo_arg(uninstall)
    run = commands.add_parser("run", help="Run one autosave tick")
    _repo_arg(run)
    _branch_arg(run)
    run.add_argument(
        "--max-file-mb", type=_nonnegative_int, default=DEFAULT_MAX_FILE_MB
    )
    run.add_argument(
        "--scan-only",
        action="store_true",
        help="Scan outgoing commits without staging, committing, or pushing",
    )
    return parser


def _repo_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repo", required=True, metavar="DIR", help="Standalone Git store root"
    )


def _branch_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--branch", default=DEFAULT_BRANCH, metavar="NAME", help="Branch to autosave"
    )


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def _git(
    repo: Path, *args: str, input: bytes | None = None, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(  # noqa: S603 - Git runs the fixed autosave operations on the selected repository.
        ["git", "-C", str(repo), *args],  # noqa: S607 - Git is the required executable for autosave operations.
        input=input,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(detail or f"command exited with {result.returncode}")
    return result


def _store_root(value: str) -> Path:
    try:
        requested = Path(value).resolve(strict=True)
    except OSError:
        raise RuntimeError(f"not a git repo: {value}") from None
    ancestor = requested.parent
    while ancestor != ancestor.parent:
        if (ancestor / ".git").exists():
            raise RuntimeError(
                f"inside a code repo at {ancestor}; autosave commits all non-ignored "
                "files and could commit work in progress to its history"
            )
        ancestor = ancestor.parent
    try:
        root = Path(
            _git(requested, "rev-parse", "--show-toplevel").stdout.decode().strip()
        ).resolve(strict=True)
    except OSError, RuntimeError:
        raise RuntimeError(f"not a git repo: {requested}") from None
    if root != requested:
        raise RuntimeError(f"not a git repo root: {requested} (Git root is {root})")
    return requested


def _upstream(repo: Path, branch: str) -> str:
    try:
        return (
            _git(repo, "rev-parse", "--symbolic-full-name", f"{branch}@{{upstream}}")
            .stdout.decode()
            .strip()
        )
    except RuntimeError:
        raise RuntimeError(f"no upstream configured for branch {branch}") from None


@dataclass
class _Change:
    mode: bytes
    blob: str
    status: bytes
    path: bytes


def _parse_raw(raw: bytes) -> list[_Change]:
    result: list[_Change] = []
    fields = iter(raw.split(b"\0"))
    for header in fields:
        if not header:
            continue
        path = next(fields, None)
        if path is None:
            raise RuntimeError("malformed git raw diff")
        values = header.split()
        if len(values) != 5:
            raise RuntimeError("malformed git raw diff header")
        result.append(
            _Change(values[1], values[3].decode(errors="replace"), values[4], path)
        )
    return result


def _staged_changes(repo: Path) -> list[_Change]:
    return _parse_raw(
        _git(repo, "diff", "--cached", "--raw", "-z", "--no-renames").stdout
    )


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stage_and_commit(repo: Path, max_file_mb: int) -> None:
    _git(repo, "add", "-A")
    changes = _staged_changes(repo)
    oversized: list[bytes] = []
    max_bytes = max(0, max_file_mb) * 1024 * 1024
    for change in changes:
        if change.status[:1] not in (b"A", b"M", b"T") or change.mode not in (
            b"100644",
            b"100755",
        ):
            continue
        size = int(_git(repo, "cat-file", "-s", change.blob).stdout.strip())
        if size > max_bytes:
            print(
                "autosave: skipping oversized file "
                f"{change.path.decode(errors='replace')!r} ({size} bytes)",
                file=sys.stderr,
            )
            oversized.append(change.path)
    if oversized:
        _git(
            repo,
            "--literal-pathspecs",
            "restore",
            "--staged",
            "--pathspec-from-file=-",
            "--pathspec-file-nul",
            input=b"\0".join(oversized) + b"\0",
        )
        changes = _staged_changes(repo)
    if changes:
        _git(repo, "commit", "-q", "-m", f"autosave {_timestamp()}")


def _parse_batch(raw: bytes) -> list[bytes]:
    blobs: list[bytes] = []
    offset = 0
    while offset < len(raw):
        end = raw.find(b"\n", offset)
        if end < 0:
            raise RuntimeError("malformed git cat-file batch header")
        fields = raw[offset:end].split()
        if len(fields) != 3 or fields[1] != b"blob":
            raise RuntimeError("git cat-file returned a non-blob object")
        try:
            size = int(fields[2])
        except ValueError:
            raise RuntimeError("malformed git cat-file batch header") from None
        body_start = end + 1
        body_end = body_start + size
        if body_end >= len(raw) or raw[body_end : body_end + 1] != b"\n":
            raise RuntimeError("malformed git cat-file batch body")
        blobs.append(raw[body_start:body_end])
        offset = body_end + 1
    return blobs


def _scan_outgoing(repo: Path, upstream: str, branch: str) -> None:
    commits = (
        _git(repo, "rev-list", "--reverse", f"{upstream}..{branch}")
        .stdout.decode()
        .splitlines()
    )
    seen: set[str] = set()
    blobs: list[tuple[str, str, str]] = []
    for commit in commits:
        raw = _git(
            repo,
            "diff-tree",
            "--root",
            "-m",
            "-r",
            "--raw",
            "-z",
            "--no-commit-id",
            "--no-renames",
            "--diff-filter=AMT",
            commit,
        ).stdout
        for change in _parse_raw(raw):
            if change.mode in (b"100644", b"100755") and change.blob not in seen:
                seen.add(change.blob)
                blobs.append(
                    (change.blob, change.path.decode(errors="replace"), commit)
                )
    if not blobs:
        return
    raw_batch = _git(
        repo,
        "cat-file",
        "--batch",
        input=("\n".join(blob[0] for blob in blobs) + "\n").encode(),
    ).stdout
    contents = _parse_batch(raw_batch)
    hits: list[tuple[str, str, str]] = []
    for blob, body in zip(blobs, contents, strict=False):
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if redact_capture(text)[1]:
            hits.append(blob)
    for _, path, commit in hits:
        print(
            f"autosave: secret detected in {path!r} (commit {commit})", file=sys.stderr
        )
    if hits:
        raise RuntimeError("outgoing commit scan found secret patterns; not pushing")


def _in_progress(repo: Path) -> bool:
    for state in (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REBASE_HEAD",
        "rebase-merge",
        "rebase-apply",
    ):
        path = Path(
            _git(repo, "rev-parse", "--git-path", state).stdout.decode().strip()
        )
        if not path.is_absolute():
            path = repo / path
        if path.exists():
            return True
    return False


def _tick(args: argparse.Namespace) -> None:
    repo = _store_root(args.repo)
    upstream = _upstream(repo, args.branch)
    if args.scan_only:
        _scan_outgoing(repo, upstream, args.branch)
        return
    current = _git(repo, "symbolic-ref", "--short", "HEAD", check=False)
    if current.returncode:
        _skip("detached HEAD")
        return
    if current.stdout.decode().strip() != args.branch:
        _skip(f"not on branch {args.branch}")
        return
    if _in_progress(repo):
        _skip("merge or rebase in progress")
        return
    lock = Path(
        _git(repo, "rev-parse", "--git-path", "index.lock").stdout.decode().strip()
    )
    if not lock.is_absolute():
        lock = repo / lock
    if lock.exists():
        _skip("index.lock exists")
        return
    try:
        _stage_and_commit(repo, args.max_file_mb)
    except RuntimeError as error:
        if "index.lock" in str(error):
            _skip("index.lock blocked a Git operation")
            return
        raise
    _scan_outgoing(repo, upstream, args.branch)
    ahead = int(
        _git(repo, "rev-list", "--count", f"{upstream}..{args.branch}").stdout.strip()
        or b"0"
    )
    if not ahead:
        return
    pushed = _git(repo, "push", check=False)
    if pushed.returncode:
        error = pushed.stderr.decode(errors="replace").strip()
        if "non-fast-forward" in error or "fetch first" in error:
            raise RuntimeError("remote diverged; not pushing")
        raise RuntimeError(error or "git push failed")


def _skip(reason: str) -> None:
    print(f"autosave: {reason}; skipping tick", file=sys.stderr)


def _job_paths(repo: Path) -> tuple[Path, Path, Path]:
    home = os.environ.get("HOME")
    if not home:
        raise RuntimeError("HOME is not set")
    identity = hashlib.sha256(str(repo).encode()).hexdigest()[:12]
    test_dir = os.environ.get(TEST_PLIST_DIR)
    plist_dir = Path(test_dir) if test_dir else Path(home) / "Library" / "LaunchAgents"
    log_dir = plist_dir.parent / "logs" if test_dir else Path(home) / "Library" / "Logs"
    return (
        plist_dir,
        plist_dir / f"varde-autosave-{identity}.plist",
        log_dir / f"varde-autosave-{identity}.log",
    )


def _xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _render_plist(
    repo: Path, branch: str, interval: int, max_file_mb: int, log: Path
) -> str:
    identity = hashlib.sha256(str(repo).encode()).hexdigest()[:12]
    label = f"varde-autosave-{identity}"
    arguments = [
        str(Path(sys.argv[0]).resolve()),
        "setup",
        "autosave",
        "run",
        "--repo",
        str(repo),
    ]
    if branch != DEFAULT_BRANCH:
        arguments.extend(("--branch", branch))
    if max_file_mb != DEFAULT_MAX_FILE_MB:
        arguments.extend(("--max-file-mb", str(max_file_mb)))
    rows = "".join(f"    <string>{_xml(argument)}</string>\n" for argument in arguments)
    path = _xml(os.environ.get("PATH", ""))
    return (
        (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n<dict>\n'
        )
        + f"  <key>Label</key><string>{label}</string>\n"
        + "  <key>ProgramArguments</key><array>\n"
        + f"{rows}  </array>\n"
        + f"  <key>StartInterval</key><integer>{interval * 60}</integer>\n"
        + "  <key>RunAtLoad</key><false/>\n"
        + "  <key>EnvironmentVariables</key><dict>"
        + f"<key>PATH</key><string>{path}</string></dict>\n"
        + f"  <key>StandardOutPath</key><string>{_xml(str(log))}</string>\n"
        + f"  <key>StandardErrorPath</key><string>{_xml(str(log))}</string>\n"
        + "</dict>\n</plist>\n"
    )


def _launchctl(action: str, plist: Path) -> None:
    executable = os.environ.get(TEST_LAUNCHCTL, "launchctl")
    if (
        action == "bootstrap"
        and not os.environ.get(TEST_LAUNCHCTL)
        and sys.platform != "darwin"
    ):
        raise RuntimeError(
            "launchd install is available only on macOS; use `varde setup autosave "
            "run` with a scheduler on this host"
        )
    uid = (
        subprocess.run(["id", "-u"], capture_output=True, check=True)  # noqa: S607 - id reads the current user's numeric id for launchd.
        .stdout.decode()
        .strip()
    )
    result = subprocess.run(  # noqa: S603 - launchctl receives the selected action and generated plist path.
        [executable, action, f"gui/{uid}", str(plist)],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        if action == "bootout" and (
            "Could not find service" in detail or "No such process" in detail
        ):
            return
        raise RuntimeError(detail or f"command exited with {result.returncode}")


def _dispatch(args: argparse.Namespace) -> None:
    if args.action == "run":
        _tick(args)
        return
    repo = _store_root(args.repo)
    plist_dir, plist, log = _job_paths(repo)
    if args.action == "uninstall":
        if plist.exists():
            _launchctl("bootout", plist)
            plist.unlink()
        return
    if args.interval_minutes < 1:
        raise RuntimeError("argument --interval-minutes: must be >= 1")
    if args.max_file_mb < 0:
        raise RuntimeError("argument --max-file-mb: must be >= 0")
    _upstream(repo, args.branch)
    plist_text = _render_plist(
        repo, args.branch, args.interval_minutes, args.max_file_mb, log
    )
    if args.dry_run:
        uid = (
            subprocess.run(["id", "-u"], stdout=subprocess.PIPE, check=True)  # noqa: S607 - id reads the current user's numeric id for dry-run output.
            .stdout.decode()
            .strip()
        )
        print(plist_text, end="")
        print(f"launchctl bootstrap gui/{uid} {plist}")
        print(f"launchctl bootout gui/{uid} {plist}")
        return
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist.write_text(plist_text)
    _launchctl("bootstrap", plist)


def run(argv: list[str], io: object) -> int:
    """Run an autosave command and return its process exit status."""
    del io
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.action in ("install", "uninstall"):
            check_old_store()
        _dispatch(args)
    except SystemExit as error:
        return int(error.code or 0)
    except (OSError, RuntimeError, ValueError, SetupError) as error:
        print(f"autosave: {error}", file=sys.stderr)
        return 1
    else:
        return 0
