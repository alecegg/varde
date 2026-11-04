"""Check the Toz store, FTS features, cache, and conflicting plugins."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from varde_toz.config import (
    config_dir,
    env_os,
    load_config,
    varde_toz_dir,
)
from varde_toz.hook import effective_thresholds
from varde_toz.profile import load_profiles
from varde_toz.store import Store

from ._maintenance import current_project, current_store, error, json_enabled, version

if TYPE_CHECKING:
    from varde_toz.doctor import DoctorSection

HELP = """Check the install: store, FTS5, cache, conflicting plugins

event states are installed, missing, edited, unsupported, or blocked.

Usage: varde setup doctor [OPTIONS]

Options:
      --fallback-dir <FALLBACK_DIR>
          External store to try after primary-store access fails

      --project <PROJECT>
          Project directory (default: git root of cwd, else cwd)

      --json
          Machine-readable JSON output

      --quiet
          Print only the handle line on overflow

  -h, --help
          Print help (see a summary with '-h')
"""


def render_doctor_section(
    section: DoctorSection | None,
) -> tuple[str, list[str], list[Any]] | None:
    if section is None:
        return None
    return (
        section.key,
        [entry.line for entry in section.entries],
        [entry.json for entry in section.entries],
    )


def _hooks(home: Path) -> list[dict]:
    entries = []
    sources = {
        "claude": (
            home / ".claude/settings.json",
            ["SessionStart", "PostToolUse", "UserPromptSubmit"],
        ),
        "codex": (
            home / ".codex/hooks.json",
            ["SessionStart", "PostToolUse", "UserPromptSubmit"],
        ),
        "opencode": (home / ".config/opencode/plugin/varde.ts", ["plugin"]),
        "pi": (home / ".pi/agent/extensions/varde.ts", ["plugin"]),
    }
    for harness, (path, targets) in sources.items():
        for target in targets:
            state = "current" if path.is_file() else "missing"
            item = {
                "harness": harness,
                "target": target,
                "state": state,
                "path": str(path),
            }
            if state != "current":
                item["fix"] = f"varde setup hooks install --harness {harness}"
            entries.append(item)
        if harness == "opencode":
            entries.append(
                {
                    "harness": harness,
                    "target": "user-prompt-submit",
                    "state": "unsupported",
                    "reason": (
                        "no per-user-prompt hook adds context; the context hook runs "
                        "on every model call"
                    ),
                    "path": str(path),
                }
            )
    return entries


def _diagnostics() -> dict:
    summary = {
        "captured": 0,
        "skipped": 0,
        "failed": 0,
        "unreadable_lines": 0,
        "unavailable_sources": 0,
        "failures_by_reason": {},
        "last_failure": None,
    }
    cutoff = int(time.time()) - 7 * 24 * 3600
    root = config_dir()
    for name in ("diagnostics.1.jsonl", "diagnostics.jsonl"):
        try:
            lines = (root / name).read_text().splitlines()
        except FileNotFoundError:
            continue
        except OSError:
            summary["unavailable_sources"] += 1
            continue
        for line in lines:
            try:
                event = json.loads(line)
                if int(event["time"]) < cutoff:
                    continue
                outcome = event.get("outcome")
                if outcome in ("captured", "skipped"):
                    summary[outcome] += 1
                elif outcome == "failed":
                    summary["failed"] += 1
                    reason = event.get("reason", "other")
                    summary["failures_by_reason"][reason] = (
                        summary["failures_by_reason"].get(reason, 0) + 1
                    )
                    timestamp = int(event["time"])
                    if summary.get("_failure_time", -1) <= timestamp:
                        summary["_failure_time"] = timestamp
                        summary["last_failure"] = (
                            f"{event.get('harness', '')} {event.get('tool', '')} "
                            f"{reason} at unix {timestamp}"
                        )
            except ValueError, TypeError, KeyError:
                summary["unreadable_lines"] += 1
    summary.pop("_failure_time", None)
    return summary


def _config_checks(cfg: dict, checks: list[tuple[bool, str]]) -> None:
    root = config_dir()
    cfg_path = root / "config.toml"
    config_status = (
        "config.toml present" if cfg_path.exists() else "defaults; no config.toml"
    )
    checks.append(
        (
            True,
            f"config dir {root} ({config_status})",
        )
    )
    cache = root / "cache"
    try:
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        probe = cache / ".doctor-probe"
        probe.write_text("ok")
        probe.unlink()
        checks.append((True, f"fetch cache writable at {cache}"))
    except OSError as exc:
        checks.append((False, f"fetch cache not writable: {exc}"))
    certs = (
        [Path(os.environ["SSL_CERT_FILE"])]
        if os.environ.get("SSL_CERT_FILE")
        else [
            Path(path)
            for path in (
                "/etc/ssl/cert.pem",
                "/etc/ssl/certs/ca-certificates.crt",
                "/etc/pki/tls/certs/ca-bundle.crt",
                "/etc/ssl/ca-bundle.pem",
            )
        ]
    )
    bundle = next((path for path in certs if path.is_file()), None)
    if bundle:
        roots = len(re.findall(rb"-----BEGIN CERTIFICATE-----", bundle.read_bytes()))
        checks.append((True, f"fetch verifies TLS against {bundle} ({roots} roots)"))
    else:
        checks.append(
            (
                False,
                (
                    "no CA bundle found; fetch falls back to the OS trust store, "
                    "which fails inside a sandboxed shell. Set SSL_CERT_FILE to a "
                    "PEM bundle."
                ),
            )
        )
    redact = cfg.get("redact", {}) if isinstance(cfg.get("redact", {}), dict) else {}
    capture = cfg.get("capture", {}) if isinstance(cfg.get("capture", {}), dict) else {}
    thresholds = (
        cfg.get("thresholds", {}) if isinstance(cfg.get("thresholds", {}), dict) else {}
    )
    overrides = (
        "none"
        if not thresholds
        else ", ".join(f"{key}={value}" for key, value in sorted(thresholds.items()))
    )
    redact_text = (
        f"builtin + {len(redact.get('patterns', []))} user pattern(s)"
        if redact.get("builtin", True)
        else f"{len(redact.get('patterns', []))} user pattern(s), builtin OFF"
    )
    never = capture.get("never", [])
    never_text = (
        f"builtin + {len(never)}"
        if capture.get("builtin_never", True)
        else f"{len(never)}, builtin OFF"
    )
    checks.append(
        (
            True,
            (
                f"thresholds shell/read/base "
                f"{'/'.join(map(str, effective_thresholds(cfg)))} bytes "
                f"(per-tool overrides: {overrides}); redaction {redact_text}; "
                f"never-capture {never_text} pattern(s)"
            ),
        )
    )
    raw = cfg.get("raw", {}) if isinstance(cfg.get("raw", {}), dict) else {}
    checks.append(
        (
            True,
            (
                f"raw exact output "
                f"{'enabled' if raw.get('enabled', False) else 'disabled'} "
                f"(cap {raw.get('max_bytes', 20 * 1024 * 1024)} bytes, "
                f"TTL {raw.get('ttl_secs', 3600)} seconds)"
            ),
        )
    )
    if cfg.get("hook_log"):
        path = Path(cfg["hook_log"])
        size = path.stat().st_size if path.exists() else 0
        checks.append(
            (
                False,
                (
                    f"hook_log is on ({path}, {size:,} bytes) — grows unbounded; "
                    "remove once payload shapes are confirmed"
                ),
            )
        )


def _settings_checks(home: Path, checks: list[tuple[bool, str]]) -> None:
    codex = home / ".codex" / "config.toml"
    try:
        text = codex.read_text()
    except OSError:
        text = ""
    if text:
        root = str(config_dir())
        listed = root in text or root.replace(str(home), "~") in text
        if listed:
            checks.append(
                (
                    True,
                    (
                        f"codex: {root} is listed in writable_roots; "
                        "active sandbox access may differ"
                    ),
                )
            )
        else:
            checks.append(
                (
                    False,
                    (
                        f"codex: add the Toz store to the sandbox so `varde run` "
                        f"can save output:\n                                [sandbox_workspace_write]\n"
                        f'       writable_roots = ["{root}"]  (in {codex})'
                    ),
                )
            )
    settings = home / ".claude" / "settings.json"
    try:
        document = json.loads(settings.read_text())
    except OSError, json.JSONDecodeError:
        return
    plugins = document.get("enabledPlugins", {})
    enabled = isinstance(plugins, dict) and any(
        name.startswith("context-mode@") and on is True for name, on in plugins.items()
    )
    checks.append(
        (
            not enabled,
            (
                "context-mode plugin is enabled in Claude Code — its steering "
                "contradicts toz's; run `claude plugin disable "
                "context-mode@context-mode`"
            )
            if enabled
            else "context-mode plugin not enabled in Claude Code",
        )
    )
    if (
        "context-mode statusline" in settings.read_text()
        or "context-mode-cache-heal" in settings.read_text()
    ):
        checks.append(
            (
                True,
                (
                    "leftover context-mode statusline/hook entries in "
                    "~/.claude/settings.json (harmless; remove if you like)"
                ),
            )
        )


def _store_checks(
    root: Path, checks: list[tuple[bool, str]], profile_diagnostics: list
) -> None:
    store_path = current_store(root)
    configured = varde_toz_dir(root)
    source = (
        "VARDE_TOZ_CONFIG_DIR"
        if os.environ.get("VARDE_TOZ_CONFIG_DIR") is not None
        else "TOZ_CONFIG_DIR"
        if env_os("TOZ_CONFIG_DIR") is not None
        else "varde config"
        if configured
        else "default"
    )
    directory = store_path.parent
    checks.append((True, f"store dir {directory} (source: {source})"))
    try:
        with Store.open(store_path) as store:
            count = store.conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
            checks.append(
                (
                    True,
                    (
                        f"store opens: {store_path} ({count} captures, "
                        f"{store.db_size_bytes():,} bytes)"
                    ),
                )
            )
            try:
                doctor_fts_sql = (
                    "CREATE VIRTUAL TABLE temp.doctor_fts USING "
                    "fts5(x, tokenize='trigram'); DROP TABLE temp.doctor_fts;"
                )
                store.conn.executescript(doctor_fts_sql)
                checks.append((True, "FTS5 with trigram tokenizer available"))
            except sqlite3.Error as exc:
                checks.append((False, f"FTS5/trigram check failed: {exc}"))
            rows = list(
                store.conn.execute(
                    "SELECT profile_id,reason,created_at FROM profile_diagnostics "
                    "ORDER BY created_at DESC,id DESC LIMIT 10"
                )
            )
            for pid, reason, created in rows:
                profile_diagnostics.append(
                    {"profile_id": pid, "reason": reason, "created_at": created}
                )
            if rows:
                checks.append(
                    (
                        False,
                        (
                            f"{len(rows)} recent profile script diagnostic(s); latest: "
                            f"{rows[0][0]} — {rows[0][1]}"
                        ),
                    )
                )
            else:
                checks.append((True, "no recent profile script diagnostics"))
    except (OSError, sqlite3.Error) as exc:
        checks.append((False, f"store {store_path}: {exc}"))


def main(
    argv: list[str] | None = None, doctor_section: DoctorSection | None = None
) -> int:
    values = sys.argv[1:] if argv is None else argv
    if "--help" in values or "-h" in values:
        print(HELP, end="")
        return 0
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fallback-dir")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    try:
        args = parser.parse_args(values)
        if args.fallback_dir and os.environ.get("TOZ_FALLBACK_DIR") is None:
            os.environ["TOZ_FALLBACK_DIR"] = args.fallback_dir
        root = current_project(args.project)
        cfg = load_config()
        checks: list[tuple[bool, str]] = []
        _profiles, profile_load_diagnostics = load_profiles(root)
        for diag in profile_load_diagnostics:
            pid = f"{diag.profile_id} " if diag.profile_id else ""
            checks.append(
                (False, f"profile diagnostic: {pid}{diag.file}: {diag.reason}")
            )
        checks.append((True, f"varde-toz {version()} at {Path(sys.argv[0]).resolve()}"))
        _config_checks(cfg, checks)
        _store_checks(root, checks, profile_diagnostics := [])
        _settings_checks(Path.home(), checks)
        recent = _diagnostics()
        attempts = recent["captured"] + recent["failed"]
        detail = f"; latest: {recent['last_failure']}" if recent["last_failure"] else ""
        hook_ok = (
            recent["failed"]
            == recent["unreadable_lines"]
            == recent["unavailable_sources"]
            == 0
        )
        checks.append(
            (
                hook_ok,
                (
                    f"retained hook outcomes, last 7 days: "
                    f"{recent['captured']} captured, "
                    f"{recent['skipped']} skipped, {recent['failed']} failed "
                    f"({attempts} attempted), {recent['unreadable_lines']} unreadable "
                    f"records, {recent['unavailable_sources']} unavailable "
                    f"sources{detail}"
                ),
            )
        )
        failures = sum(not passed for passed, _ in checks)
        if json_enabled(args):
            hooks = _hooks(Path.home())
            report = {
                "checks": [
                    {"ok": passed, "message": message} for passed, message in checks
                ],
                "warnings": failures,
                "hook_outcomes_7d": recent,
                "profile_diagnostics": profile_diagnostics,
                "profile_load_diagnostics": [
                    asdict(item) for item in profile_load_diagnostics
                ],
                "hooks": hooks,
            }
            rendered = render_doctor_section(doctor_section)
            if rendered is not None:
                key, _lines, entries = rendered
                report[key] = entries
            print(json.dumps(report, separators=(",", ":"), sort_keys=True))
        else:
            for passed, message in checks:
                print(f"{'ok   ' if passed else 'warn '}{message}")
            rendered = render_doctor_section(doctor_section)
            if rendered is not None:
                _key, lines, _entries = rendered
                for line in lines:
                    print(line)
            if rendered is None:
                for entry in _hooks(Path.home()):
                    line = (
                        f"hook {entry['harness']} {entry['target']}: "
                        f"{entry['state']} ({entry['path']})"
                    )
                    if "fix" in entry:
                        line += f"; fix: {entry['fix']}"
                    if "reason" in entry:
                        line = (
                            f"hook {entry['harness']} {entry['target']}: "
                            f"{entry['state']} ({entry['reason']})"
                        )
                    print(line)
            print("all good" if not failures else f"{failures} warning(s)")
        return int(failures != 0)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return error(str(exc))
