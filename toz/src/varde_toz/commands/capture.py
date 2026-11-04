"""The capture command."""

from __future__ import annotations

import json
import sys

HELP = """Capture already-produced output from stdin (or a hook payload)

Usage: varde run capture [OPTIONS]

Options:
      --fallback-dir <FALLBACK_DIR>  External store to try after primary-store access fails
  -l, --label <LABEL>                Human label for the capture
      --project <PROJECT>            Project directory (default: git root of cwd, else cwd)
  -s, --source <SOURCE>              Origin string (command, path, URL) used for the supersession key
      --json                         Machine-readable JSON output
      --kind <KIND>                  Kind tag stored with the capture (e.g. hook:Bash) [default: capture]
      --quiet                        Print only the handle line on overflow
  -t, --threshold <THRESHOLD>        Byte threshold override
      --exit-code <EXIT_CODE>        Exit code to record
      --hook                         Read a hook JSON payload ({tool_name, tool_input, tool_response, session_id}) from stdin
      --harness <HARNESS>            Which harness sent the hook payload: claude-code | pi | opencode | codex [default: claude-code]
      --stderr                       Treat stdin as stderr rather than stdout
      --force                        Store even if under threshold
      --defer-index                  Defer full-text indexing until the first term search
  -h, --help                         Print help
"""


def main(argv: list[str]) -> int:
    if "--hook" in argv:
        harness = "claude-code"
        for index, arg in enumerate(argv):
            if arg.startswith("--harness="):
                harness = arg.partition("=")[2]
            elif arg == "--harness" and index + 1 < len(argv):
                harness = argv[index + 1]
        from varde_toz.hook import MAX_PAYLOAD_BYTES, _capture_hook

        raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
        if len(raw) <= MAX_PAYLOAD_BYTES:
            sys.stdout.buffer.write(
                _capture_hook(raw, "claude" if harness == "claude-code" else harness)
            )
        else:
            from varde_toz.commands.event_note import record_best_effort

            record_best_effort(
                "claude-code" if harness == "claude-code" else harness,
                "failed",
                "invalid-payload",
                "",
                len(raw),
            )
        return 0

    import argparse

    from varde_toz.capture import CaptureInput, capture, capture_spooled

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fallback-dir")
    parser.add_argument("-l", "--label")
    parser.add_argument("--project")
    parser.add_argument("-s", "--source")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--kind", default="capture")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("-t", "--threshold", type=int)
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--hook", action="store_true")
    parser.add_argument("--harness", default="claude-code")
    parser.add_argument("--stderr", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--defer-index", action="store_true")
    if "--help" in argv or "-h" in argv:
        print(HELP, end="")
        return 0
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code is None else int(exc.code)
    from pathlib import Path

    from varde_toz.project import project_root, store_db_path
    from varde_toz.streaming import spool

    raw_file, size = spool(sys.stdin.buffer)
    root = Path(args.project).resolve() if args.project else None
    store_path = None
    raw = None
    stdout, stderr = b"", b""
    source, label, kind, session = args.source or "", args.label, args.kind, None
    if args.fallback_dir:
        fallback_root = root or project_root()
        store_path = store_db_path(fallback_root, Path(args.fallback_dir))
    payload = CaptureInput(
        stdout,
        stderr,
        label,
        source,
        kind,
        args.exit_code,
        session,
        force=args.force,
        defer_index=args.defer_index,
        threshold=args.threshold,
        quiet=args.quiet,
    )
    streamed = size > 1024 * 1024

    def run_capture(fallback: bool = False):
        target = store_path if fallback else None
        if streamed:
            return capture_spooled(
                raw_file,
                size,
                payload,
                root,
                stream_name="stderr" if args.stderr else "stdout",
                store_path=target,
            )
        if raw is None:
            raw_file.seek(0)
            raw_value = raw_file.read()
        else:
            raw_value = raw
        payload.stdout, payload.stderr = (
            (b"", raw_value) if args.stderr else (raw_value, b"")
        )
        return capture(payload, root, target)

    try:
        status, output = run_capture()
    except OSError as exc:
        if not args.fallback_dir:
            print(f"varde-toz: {exc}", file=sys.stderr)
            return 1
        try:
            status, output = run_capture(fallback=True)
        except (OSError, ValueError, RuntimeError) as fallback_exc:
            print(f"varde-toz: {fallback_exc}", file=sys.stderr)
            return 1
    except (ValueError, RuntimeError) as exc:
        print(f"varde-toz: {exc}", file=sys.stderr)
        return 1
    if status:
        if args.json:
            print(
                json.dumps(
                    {"preview": output}, separators=(",", ":"), ensure_ascii=False
                )
            )
        else:
            print(output, end="")
    elif raw is not None:
        sys.stdout.buffer.write(raw)
    else:
        import shutil

        raw_file.seek(0)
        shutil.copyfileobj(raw_file, sys.stdout.buffer)
    return 0


def _hook_source(tool: str, value: object) -> str:
    fields = ("command", "path", "file_path", "url", "query", "pattern")
    if isinstance(value, dict):
        source = next(
            (
                str(value[key])
                for key in fields
                if isinstance(value.get(key), str) and value[key]
            ),
            "",
        )
        if source:
            return source
    return f"{tool} {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"


def _hook_streams(value: object, harness: str = "claude-code") -> tuple[bytes, bytes]:
    if isinstance(value, str):
        return value.encode(), b""
    if isinstance(value, dict):
        has_stream = isinstance(value.get("stdout"), str) or isinstance(
            value.get("output"), str
        )
        stdout = value.get("stdout", value.get("output", ""))
        stderr = value.get("stderr", "")
        if has_stream and isinstance(stdout, str) and isinstance(stderr, str):
            return stdout.encode(), stderr.encode()
        content_text = _hook_content_text(value)
        structured = value.get("structuredContent")
        if harness == "claude":
            harness = "claude-code"
        if harness in ("claude-code", "codex") and structured is not None:
            envelope = {
                "contentText": content_text or "",
                "structuredContent": structured,
            }
            return json.dumps(envelope, ensure_ascii=False, indent=2).encode(), b""
        if content_text is not None:
            return content_text.encode(), b""
        return json.dumps(value, ensure_ascii=False, indent=2).encode(), b""
    if isinstance(value, list):
        text = "\n".join(
            item["text"]
            for item in value
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
        return text.encode(), b""
    return json.dumps(value, ensure_ascii=False, indent=2).encode(), b""


def _hook_content_text(value: object) -> str | None:
    if isinstance(value, list):
        parts = [
            item["text"]
            for item in value
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        return "\n".join(parts) if parts else None
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, list):
            return _hook_content_text(content)
    return None
