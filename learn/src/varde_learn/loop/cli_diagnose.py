"""CLI dispatch for diagnose and eval commands."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import fields, is_dataclass
from enum import Enum
from importlib.resources import files
from pathlib import Path
from typing import Any, Never

from varde_core.envelope import success, tool_error


def _raise(error: Exception) -> Never:
    raise error


_HELP_FILES = {
    "diagnose": "help/diagnose.txt",
    "diagnose capture": "help/diagnose/capture.txt",
    "diagnose list": "help/diagnose/list.txt",
    "diagnose summary": "help/diagnose/summary.txt",
    "diagnose inspect": "help/diagnose/inspect.txt",
    "eval": "help/eval.txt",
    "eval trigger": "help/eval/trigger.txt",
    "eval output": "help/eval/output.txt",
    "eval calibrate": "help/eval/calibrate.txt",
}


def help_text(path: str = "") -> str:
    """Read the committed Rust help snapshot for a command path."""
    command = " ".join(path.split())
    command = command.removeprefix("learn ")
    if command in _HELP_FILES:
        return files("varde_learn.loop").joinpath(_HELP_FILES[command]).read_text()
    if command in {"", "learn"}:
        return (
            "Usage: varde learn <COMMAND>\n\nCommands:\n  diagnose\n  eval\n"
            "  friction\n  adopt\n"
        )
    return help_text(command.rsplit(" ", 1)[0])


class _ParseFailure(Exception):
    pass


class _DiagnoseError(ValueError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class _Parser:
    """Small option parser that keeps Clap's help in committed snapshots."""

    def __init__(self, command: str, specs: dict[str, tuple[str, bool]]):
        self.command = command
        self.specs = specs

    def parse(self, argv: list[str]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        positional = [
            key for key, (kind, _) in self.specs.items() if kind == "positional"
        ]
        position = 0
        index = 0
        while index < len(argv):
            token = argv[index]
            if token in {"-h", "--help"}:
                print(help_text(self.command), end="")
                raise SystemExit(0)
            if token.startswith("--"):
                name = token[2:].replace("-", "_")
                if name not in self.specs or self.specs[name][0] == "positional":
                    raise _ParseFailure(f"unexpected argument '{token}'")
                kind, takes_value = self.specs[name]
                if takes_value:
                    index += 1
                    if index >= len(argv):
                        raise _ParseFailure(f"a value is required for '{token}'")
                    value = argv[index]
                    if kind in {"int", "optional_int"}:
                        try:
                            value = int(value)
                        except ValueError as error:
                            raise _ParseFailure(
                                f"invalid value '{value}' for '{token}'"
                            ) from error
                else:
                    value = True
                if name == "eval":
                    values.setdefault(name, []).append(value)
                else:
                    values[name] = value
            elif token.startswith("-"):
                raise _ParseFailure(f"unexpected argument '{token}'")
            elif position < len(positional):
                values[positional[position]] = token
                position += 1
            else:
                raise _ParseFailure(f"unexpected argument '{token}'")
            index += 1
        for name, (kind, _) in self.specs.items():
            if kind == "flag":
                values.setdefault(name, False)
        return values


def run(argv: list[str], io: object | None = None) -> int:
    """Run diagnose or eval with arguments after the top-level command."""
    del io
    args = list(argv)
    if args and args[0] in {"diagnose", "eval"}:
        top = args.pop(0)
    elif len(args) > 1 and args[1] in {"diagnose", "eval"}:
        args.pop(0)
        top = args.pop(0)
    else:
        return _error("usage_error", "expected diagnose or eval command", 2)
    if top == "diagnose":
        return _run_diagnose(args)
    return _run_eval(args)


def _run_diagnose(args: list[str]) -> int:  # noqa: PLR0912
    if not args:
        print(help_text("diagnose"), end="")
        return 0
    command = args.pop(0)
    specs = {
        "inspect": {
            "harness": ("text", True),
            "current": ("flag", False),
            "session": ("text", True),
            "path": ("text", True),
            "snapshot_in": ("text", True),
            "snapshot_out": ("text", True),
            "cutoff_anchor": ("text", True),
            "offset": ("int", True),
            "limit": ("int", True),
            "json": ("flag", False),
        },
        "list": {
            "harness": ("text", True),
            "repository": ("text", True),
            "limit": ("int", True),
            "run": ("text", True),
            "json": ("flag", False),
        },
        "summary": {
            "harness": ("text", True),
            "repository": ("text", True),
            "limit": ("int", True),
            "new": ("flag", False),
            "mark": ("flag", False),
            "json": ("flag", False),
        },
        "capture": {
            "file": ("text", True),
            "snapshot": ("text", True),
            "source_id": ("text", True),
            "record_index": ("int", True),
            "native_id": ("text", True),
            "kind": ("text", True),
            "evidence": ("text", True),
            "item_id": ("int", True),
            "item_source": ("text", True),
            "item_title": ("text", True),
            "item_target": ("text", True),
            "json": ("flag", False),
        },
    }
    if command not in specs:
        return _parse_error(
            f"unexpected argument '{command}'", "diagnose" in args or "--json" in args
        )
    options: dict[str, Any] = {}
    try:
        options = _Parser(f"diagnose {command}", specs[command]).parse(args)
        _validate_diagnose(command, options)
        if not options.get("json") and command in {"list", "capture"}:
            _raise(ValueError(f"diagnose {command} requires --json"))
        if command == "inspect":
            data, meta, human = _inspect(options)
        elif command == "list":
            data, meta, human = _list(options)
        elif command == "summary":
            from .diagnose.summary import summarize

            data, meta, human = summarize(options)
        else:
            from .diagnose.capture import (
                CaptureError,
                CaptureFlags,
                capture,
                capture_from_flags,
            )

            if not options.get("json"):
                _raise(ValueError("diagnose capture requires --json"))
            flag_form_options = (
                "snapshot",
                "source_id",
                "record_index",
                "native_id",
                "kind",
                "item_id",
                "item_source",
                "item_title",
                "item_target",
                "evidence",
            )
            if options.get("file") and any(
                options.get(name) is not None for name in flag_form_options
            ):
                _raise(
                    CaptureError(
                        "diagnose_capture_invalid",
                        "--file cannot be combined with capture flags",
                    )
                )
            persist = _persist_capture
            if options.get("file"):
                data = capture(Path(options["file"]), persist=persist)
            elif options.get("snapshot"):
                required = ("source_id", "record_index", "kind", "evidence")
                if any(options.get(key) is None for key in required):
                    _raise(
                        ValueError(
                            "--snapshot requires --source-id, --record-index, "
                            "--kind, and --evidence"
                        )
                    )
                data = capture_from_flags(
                    CaptureFlags(
                        Path(options["snapshot"]),
                        options["source_id"],
                        int(options["record_index"]),
                        options.get("native_id"),
                        options["kind"],
                        options.get("item_id"),
                        options.get("item_source"),
                        options.get("item_title"),
                        options.get("item_target"),
                        options["evidence"],
                    ),
                    persist=persist,
                )
            else:
                _raise(ValueError("pass exactly one of --file or --snapshot"))
            meta: dict[str, Any] = {"truncated": False}
            human = ""
        if options.get("json"):
            _print_json(success(data, meta))
        else:
            print(human)
            for warning in meta.get("warnings", []):
                print(f"WARNING {warning}")
    except SystemExit as exit_error:
        return int(exit_error.code or 0)
    except _ParseFailure as error:
        return _parse_error(str(error), "--json" in args)
    except Exception as error:
        return _error(
            getattr(error, "code", "diagnose_error"),
            str(error),
            2,
            json_requested=bool(options.get("json")),
        )
    else:
        return 0


def _validate_diagnose(command: str, options: dict[str, Any]) -> None:
    if command == "inspect":
        if int(options.get("limit", 100)) < 1 or int(options.get("limit", 100)) > 1000:
            raise ValueError("--limit must be between 1 and 1000")
        if int(options.get("offset", 0)) < 0:
            raise ValueError("--offset must be non-negative")
        chosen = sum(
            (
                bool(options.get("current")),
                options.get("session") is not None,
                options.get("path") is not None,
                options.get("snapshot_in") is not None,
            )
        )
        if chosen != 1:
            raise ValueError(
                (  # noqa: UP034 - keep the wrapped message explicitly grouped
                    "choose exactly one intake: --current, --session, --path, or "
                    "--snapshot-in"
                )
            )
        if options.get("snapshot_in") is None and options.get("harness") not in {
            "codex",
            "claude",
            "opencode",
        }:
            raise ValueError("--harness is required for a live intake")
        if options.get("snapshot_in") is not None and (
            options.get("snapshot_out") is not None
            or options.get("cutoff_anchor") is not None
        ):
            raise ValueError(
                (  # noqa: UP034 - keep the wrapped message explicitly grouped
                    "--snapshot-in cannot be combined with --snapshot-out or "
                    "--cutoff-anchor"
                )
            )
    if command in {"list", "summary"}:
        if options.get("harness") not in {"codex", "claude", "opencode", "all"}:
            raise ValueError("--harness must be codex, claude, opencode, or all")
        if not options.get("repository"):
            raise ValueError(
                "the following required arguments were not provided: --repository"
            )
        if not 1 <= int(options.get("limit", 5)) <= 10:
            raise ValueError("--limit must be between 1 and 10")


def _inspect(options: dict[str, Any]):
    from types import SimpleNamespace

    from .diagnose.capture import load_snapshot
    from .diagnose.model import harness_adapter
    from .diagnose.snapshot import apply_cutoff, snapshot_document, write_snapshot

    harness = options.get("harness")
    harness_key: str = harness if isinstance(harness, str) else ""
    if options.get("snapshot_in"):
        frozen = load_snapshot(Path(options["snapshot_in"]))
        records = frozen["records"]
        offset, limit = int(options.get("offset", 0)), int(options.get("limit", 100))
        page = records[offset : offset + limit]
        value = {
            "session": frozen["session"],
            "children": frozen["children"],
            "sources": frozen["sources"],
            "records": page,
            "overlap": frozen["overlap"],
            "coverage": frozen["coverage"],
            "snapshot": {"digest": frozen["digest"]},
        }
        total = len(records)
        meta = {
            "offset": min(offset, total),
            "limit": limit,
            "total": total,
            "returned": len(page),
            "truncated": bool(
                frozen["coverage"].get("truncated") or offset + len(page) < total
            ),
        }
        human = (
            f"{frozen['session']['harness']} session "
            f"{frozen['session']['thread_id']} ({frozen['overlap']} overlap): "
            f"{len(page)} evidence records"
        )
        return value, meta, human
    roots = {
        "codex": Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        / "projects",
        "opencode": _opencode_root(),
    }
    if harness_key not in roots and not options.get("current"):
        raise ValueError("--harness must be codex, claude, or opencode")
    if options.get("current"):
        if harness == "claude":
            request = _claude_current_request(roots["claude"])
        elif harness == "codex":
            thread_id = os.environ.get("CODEX_THREAD_ID")
            if not thread_id:
                raise _DiagnoseError(
                    (
                        "Codex did not provide a verified current thread ID; use "
                        "--session or --path"
                    ),
                    "diagnose_current_unavailable",
                )
            request = SimpleNamespace(
                source_root=roots["codex"],
                root=roots["codex"],
                session_id=thread_id,
                path=None,
            )
        else:
            raise _DiagnoseError(
                (
                    "OpenCode does not expose a verified caller context for "
                    "current-session inspection"
                ),
                "diagnose_current_unavailable",
            )
    elif options.get("session"):
        request = SimpleNamespace(
            source_root=roots[harness_key],
            projects_root=roots[harness_key],
            root=roots[harness_key],
            session_id=options["session"],
            path=None,
        )
    else:
        request = SimpleNamespace(
            source_root=roots[harness_key],
            projects_root=roots[harness_key],
            root=roots[harness_key],
            session_id=None,
            path=Path(options["path"]),
        )
    result = harness_adapter(harness_key).inspect(request)
    if (
        options.get("current")
        and harness == "claude"
        and result.session.session_id != request.session_id
    ):
        raise _DiagnoseError(
            "Claude hook session ID does not match the selected transcript",
            "diagnose_current_unavailable",
        )
    records = result.records
    offset = int(options.get("offset", 0))
    limit = int(options.get("limit", 100))
    coverage: dict[str, Any] = _plain(result.coverage)
    if getattr(result.overlap, "value", result.overlap) in {"current", "unknown"}:
        coverage["complete"] = False
        coverage["analysis_ready"] = False
        warning = (
            "current-session overlap is current or unknown and no verified "
            "pre-orchestration cutoff was supplied"
        )
        if warning not in coverage.get("warnings", []):
            coverage.setdefault("warnings", []).append(warning)
    full = {
        "session": _plain(result.session),
        "children": _plain(result.children),
        "sources": [
            _plain_source(source, result.session.harness) for source in result.sources
        ],
        "records": _plain(records),
        "overlap": _plain(result.overlap),
        "coverage": coverage,
        "snapshot": {"digest": result.snapshot.digest},
    }
    if options.get("cutoff_anchor"):
        apply_cutoff(full, Path(options["cutoff_anchor"]))
    if options.get("snapshot_out"):
        snapshot = snapshot_document(full)
        full["snapshot"]["digest"] = snapshot["digest"]
        write_snapshot(Path(options["snapshot_out"]), snapshot)
    records = full["records"]
    page = records[offset : offset + limit]
    value = {**full, "records": page}
    total = len(records)
    meta = {
        "offset": min(offset, total),
        "limit": limit,
        "total": total,
        "returned": len(page),
        "truncated": bool(
            full["coverage"].get("truncated", False) or offset + len(page) < total
        ),
    }
    human = (
        f"{result.session.harness} session {result.session.thread_id} "
        f"({result.overlap} overlap): {len(page)} evidence records"
    )
    return value, meta, human


def _claude_current_request(projects_root: Path):
    from types import SimpleNamespace

    try:
        if sys.stdin.isatty():
            _raise(ValueError("Claude --current requires command-hook JSON on stdin"))
        raw = sys.stdin.buffer.read(64 * 1024 + 1)
        if not raw or len(raw) > 64 * 1024:
            _raise(ValueError("Claude hook input is empty or exceeds the 64 KiB limit"))
        hook = json.loads(raw)
        session_id = hook.get("session_id")
        transcript = hook.get("transcript_path")
        if not isinstance(session_id, str) or not session_id.strip():
            _raise(ValueError("Claude hook input is missing `session_id`"))
        if not isinstance(transcript, str) or not Path(transcript).is_absolute():
            _raise(ValueError("Claude hook `transcript_path` must be an absolute path"))
        path = Path(transcript).resolve(strict=True)
        if not path.is_relative_to(projects_root.resolve(strict=True)):
            _raise(ValueError("Claude hook transcript is outside the projects root"))
        return SimpleNamespace(
            projects_root=projects_root,
            root=projects_root,
            session_id=session_id,
            path=path,
            is_current=True,
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        AttributeError,
        ValueError,
    ) as error:
        failure = _DiagnoseError(str(error), "diagnose_current_unavailable")
        raise failure from error


def _list(options: dict[str, Any]):
    from .diagnose.list import ListRequest, list_sessions
    from .diagnose.model import harness_adapter

    roots = {
        "codex": Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        / "projects",
        "opencode": _opencode_root(),
    }
    harnesses = (
        ("codex", "claude", "opencode")
        if options["harness"] == "all"
        else (options["harness"],)
    )
    for name in harnesses:
        harness_adapter(name)
    paseo_home = (
        Path(os.environ["PASEO_HOME"]) if os.environ.get("PASEO_HOME") else None
    )
    request = ListRequest(
        options["harness"],
        Path(options["repository"]),
        roots["codex"],
        roots["claude"],
        roots["opencode"],
        paseo_home=paseo_home,
        limit=int(options.get("limit", 5)),
        run=options.get("run"),
    )
    result = list_sessions(request)
    data = result.to_dict()
    # summary returns warnings through the same envelope as list mode.
    return (
        data,
        {"truncated": bool(result.warnings), "warnings": result.warnings},
        json.dumps(data, separators=(",", ":")),
    )


def _run_eval(args: list[str]) -> int:
    from .cli_diagnose_eval import run_eval

    return run_eval(args)


def _opencode_root() -> Path:
    from .sources import _opencode_root as resolve_opencode_root

    return resolve_opencode_root(dict(os.environ))


def _persist_capture(request):
    from . import cli_friction
    from .diagnose.capture import CaptureError

    handler = getattr(cli_friction, "record_historical_capture", None)
    if handler is None:
        raise CaptureError(
            "diagnose_capture_store_unavailable",
            "historical capture store interface is not available",
        )
    return handler(request)


def _plain_source(source, harness: str) -> dict[str, object]:
    path = source.canonical_path
    formats = {
        "codex": "codex-jsonl",
        "claude": "claude-jsonl",
        "opencode": "opencode-sqlite-2.0.12",
    }
    data = {
        "source_id": source.source_id,
        "canonical_path": path,
        "device": source.device,
        "inode": source.inode,
        "initial_length": source.length,
        "captured_length": source.length,
        "modified_ns": source.modified_ns,
        "prefix_digest": source.digest,
        "harness": harness,
        "format": formats[harness],
    }
    if harness == "claude":
        data["session_thread_id"] = getattr(source, "session_thread_id", None)
        data["transcript_id"] = getattr(source, "transcript_id", None)
    if harness == "opencode":
        data["companions"] = _plain(source.companions) or [
            {"path": path + suffix, "present": False} for suffix in ("-wal", "-shm")
        ]
    return {key: _plain(value) for key, value in data.items() if value is not None}


_EXTENSION_NONE_FIELDS = {
    "SourceCompanion": {"device", "inode", "length", "modified_ns", "digest"},
    "SourceSnapshot": {"session_thread_id", "transcript_id"},
    "SessionMetadata": {
        "transcript_id",
        "project_namespace",
        "agent_id",
        "parent_agent_id",
        "parent_tool_use_id",
        "current_directory",
        "fork_session_id",
        "fork_boundary",
    },
    "RecordAnchor": {"session_id", "storage_sequence", "context_digest"},
    "EvidenceRecord": {
        "transcript_id",
        "provider_message_id",
        "agent_id",
        "parent_agent_id",
        "parent_native_id",
        "tool_use_id",
        "parent_tool_use_id",
        "is_sidechain",
        "is_meta",
        "is_compact_summary",
        "timestamp_raw",
        "session_location",
        "location_provenance",
    },
    "ToolObservation": {
        "tool_use_id",
        "tool_name",
        "input_excerpt",
        "output_excerpt",
        "status",
        "error",
    },
}


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        optional_fields = _EXTENSION_NONE_FIELDS.get(type(value).__name__, set())
        return {
            item.name: _plain(getattr(value, item.name))
            for item in fields(value)
            if not (item.name in optional_fields and getattr(value, item.name) is None)
            and not (
                item.name in {"tool_observations", "companions"}
                and getattr(value, item.name) == []
            )
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def _print_json(value: object, *, error: bool = False) -> None:
    print(
        json.dumps(value, separators=(",", ":"), sort_keys=True),
        file=sys.stderr if error else sys.stdout,
    )


def _error(
    code: str, message: str, status: int, *, json_requested: bool = False
) -> int:
    if json_requested:
        _print_json(tool_error(code, message), error=True)
    else:
        print(f"error: {message}", file=sys.stderr)
    return status


def _parse_error(message: str, json_requested: bool) -> int:
    return _error("usage_error", message, 2, json_requested=json_requested)
