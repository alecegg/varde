"""Lightweight harness hook dispatcher (no argparse or script runtime import)."""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
from contextlib import contextmanager, nullcontext, suppress
from typing import Any


def _phase_span(name: str):
    if os.environ.get("VARDE_TOZ_PHASE_TRACE"):
        from varde_toz.phase_trace import span

        return span(name)
    return nullcontext()


MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
INLINE_THRESHOLD = 64 * 1024
SHELL_THRESHOLD = 8 * 1024
HOOK_TIMEOUT_SECONDS = 6.0
HARNESSES = ("claude", "codex", "opencode", "pi")
HELP = (
    "Usage: varde hook {event} --harness <claude|codex|opencode|pi>\n\n"
    "Options:\n  --harness <HARNESS>  Harness the hook runs for (required)\n"
    "  -h, --help           Print help"
)


def _options(argv: list[str]) -> tuple[str | None, bool, bool]:
    harness = None
    help_requested = any(arg in ("-h", "--help") for arg in argv)
    invalid = False
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg.startswith("--harness="):
            harness = arg.partition("=")[2]
        elif arg == "--harness":
            if index + 1 < len(argv):
                index += 1
                harness = argv[index]
            else:
                invalid = True
        index += 1
    if harness not in HARNESSES:
        invalid = True
    return harness if not invalid else None, help_requested, invalid


def main(argv: list[str]) -> int:
    event = argv[0] if argv else ""
    harness, help_requested, invalid = _options(argv[1:])
    if help_requested:
        print(HELP.format(event=event))
        return 0
    if invalid or event not in ("post-tool-use", "session-start"):
        print(
            "varde hook: --harness <claude|codex|opencode|pi> is required",
            file=sys.stderr,
        )
        return 2
    if harness is None:
        raise AssertionError("validated hook arguments require a harness")
    output = None
    try:
        with _hook_deadline():
            with _phase_span("config load"):
                config = _varde_config()
            with _phase_span("provider routing"):
                providers = _providers(config, event)
            if event == "post-tool-use":
                with _phase_span("payload read"):
                    payload = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
                if len(payload) > MAX_PAYLOAD_BYTES:
                    return 0
                if "capture" not in providers:
                    return 0
                with _phase_span("capture dispatch and setup"):
                    output = _capture_hook(payload, harness)
            else:
                _session_start(harness, config, providers)
    except Exception:
        # Hooks must fail open so tool output remains visible to the harness.
        return 0
    if output:
        sys.stdout.buffer.write(output)
    return 0


@contextmanager
def _hook_deadline():
    try:
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
    except ValueError, AttributeError:
        yield
        return
    try:
        signal.signal(signal.SIGALRM, _raise_hook_timeout)
    except ValueError, AttributeError:
        yield
        return
    try:
        signal.setitimer(signal.ITIMER_REAL, HOOK_TIMEOUT_SECONDS)
    except ValueError, AttributeError:
        signal.signal(signal.SIGALRM, previous_handler)
        yield
        return
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def _raise_hook_timeout(_signum, _frame):
    raise TimeoutError("hook timed out")


def _varde_config() -> dict[str, Any]:
    import tomllib

    from varde_toz.config import varde_config_dir

    path = varde_config_dir() / "config.toml"
    try:
        return tomllib.loads(path.read_text())
    except OSError, tomllib.TOMLDecodeError:
        return {}


def _providers(config: dict[str, Any], event: str) -> list[str]:
    hooks = config.get("hooks", {})
    section = (
        hooks.get("post_tool_use" if event == "post-tool-use" else "session_start", {})
        if isinstance(hooks, dict)
        else {}
    )
    providers = section.get("providers", []) if isinstance(section, dict) else []
    return (
        [value for value in providers if isinstance(value, str)]
        if isinstance(providers, list)
        else []
    )


def _capture_hook(raw: bytes, harness: str) -> bytes:
    try:
        try:
            with _phase_span("payload parse"):
                payload = json.loads(raw)
        except ValueError, UnicodeDecodeError:
            _record_outcome(harness, "failed", "invalid-payload", "", len(raw))
            return b""
        if not isinstance(payload, dict):
            _record_outcome(harness, "skipped", "unsupported-shape", "", len(raw))
            return b""
        with _phase_span("payload shaping"):
            tool_value = payload.get("tool_name")
            tool = tool_value if isinstance(tool_value, str) else ""
            tool_input = payload.get("tool_input")
            response = payload.get("tool_response")
            if not isinstance(tool_input, dict):
                tool_input = {}
            if _has_binary_media(response):
                _record_outcome(harness, "skipped", "binary-media", tool, len(raw))
                return b""
            shape = _extract(tool, tool_input, response, harness)
            if shape is None:
                _record_outcome(harness, "skipped", "unsupported-shape", tool, len(raw))
                return b""
            source = shape["source"]
            shell_source = next(
                (
                    tool_input[k]
                    for k in ("command", "cmd")
                    if isinstance(tool_input.get(k), str) and tool_input[k]
                ),
                None,
            )
            from varde_toz.hook_input.cwd_noise import strip

            stdout, stderr = shape["stdout"], shape["stderr"]
            raw_stdout, raw_stderr = stdout, stderr
            if shell_source is not None:
                stdout, stderr = strip(stdout), strip(stderr)
        from varde_toz.config import load_config
        from varde_toz.project import project_root
        from varde_toz.redact_toz import configured_redactor

        toz_config = load_config()
        clean_stdout, clean_stderr = stdout, stderr
        with _phase_span("project-root resolution"):
            root = project_root()
        with _phase_span("hook redaction"):
            redactor = configured_redactor(root)
            stdout, stdout_notices, stdout_reusable = _redact_hook_text(
                stdout, redactor
            )
            stderr, stderr_notices, stderr_reusable = _redact_hook_text(
                stderr, redactor
            )
        notices = stdout_notices + stderr_notices
        with _phase_span("scope and readonly checks"):
            if shell_source is not None:
                from varde_toz.hook_input.scoped import is_scoped

                scoped = (
                    is_scoped(source)
                    and len(stdout.encode()) + len(stderr.encode()) <= 64 * 1024
                )
            else:
                scoped = False
            threshold = _threshold_for(tool, tool_input, toz_config)
        with _phase_span("hook classification and scope checks"):
            if (
                shape["kind"] in ("content_field", "structured_hint")
                and shape.get("structured") is not None
            ):
                try:
                    shape["structured"] = json.loads(stdout).get("structuredContent")
                    shape["stdout"] = stdout
                except ValueError, AttributeError:
                    pass
            masked = bool(notices) or stdout != clean_stdout or stderr != clean_stderr
            changed = masked or stdout != raw_stdout or stderr != raw_stderr
            pass_through = scoped and not masked
            total = len(stdout.encode()) + len(stderr.encode())
            unchanged_below_threshold = total <= threshold and not changed
        if pass_through:
            _record_outcome(harness, "skipped", "pass-through", tool, total)
            return b""
        if unchanged_below_threshold:
            return b""
        if shell_source is not None:
            with _phase_span("command scanning"):
                toz_only = _toz_only_shell_source(source)
        else:
            toz_only = False
        if toz_only:
            return b""
        if total <= threshold:
            return _render_small(
                harness,
                shape,
                response,
                stdout,
                stderr,
                shell_source is not None,
                notices,
            )
        from varde_toz.capture import CaptureInput, capture

        with _phase_span("capture input encoding"):
            capture_input = CaptureInput(
                stdout.encode(),
                stderr.encode(),
                shape["label"],
                source,
                f"hook:{tool}",
                shape["exit_code"],
                _capture_session(payload, harness),
                threshold=threshold,
                content_redacted=(
                    stdout_reusable
                    and stderr_reusable
                    and "\x1b" not in stdout
                    and "\x1b" not in stderr
                ),
            )
        capture_result = capture(capture_input, config=toz_config)
        status, preview = capture_result.status, capture_result.output
        if not status:
            _record_outcome(harness, "skipped", "excluded", tool, total)
            return _render_small(
                harness,
                shape,
                response,
                stdout,
                stderr,
                shell_source is not None,
                notices,
            )
        _record_outcome(harness, "captured", "stored", tool, total)
        with _phase_span("output"):
            return _render_captured(
                harness, shape, response, preview, shell_source is not None, notices
            )
    except Exception:
        _record_outcome(harness, "failed", "hook-error", "", 0)
        return b""


_MEDIA_KEYS = ("type", "mimeType", "mime_type", "media_type")
_MEDIA_DEPTH = 6


def _is_media_type(value: Any) -> bool:
    return isinstance(value, str) and (
        value.startswith("image/") or value == "application/pdf"
    )


def _has_binary_media(value: Any, depth: int = 0) -> bool:
    """True when a tool response carries image, base64 or PDF content."""
    if depth > _MEDIA_DEPTH:
        return False
    if isinstance(value, list):
        return any(_has_binary_media(item, depth + 1) for item in value)
    if not isinstance(value, dict):
        return False
    if value.get("type") in ("image", "base64"):
        return True
    if isinstance(value.get("base64"), str):
        return True
    if any(_is_media_type(value.get(key)) for key in _MEDIA_KEYS):
        return True
    return any(
        _has_binary_media(item, depth + 1)
        for item in value.values()
        if isinstance(item, (dict, list))
    )


def _record_outcome(
    harness: str, outcome: str, reason: str, tool: str, size: int
) -> None:
    try:
        from varde_toz.commands.event_note import record_best_effort

        with _phase_span("outcome event/note"):
            record_best_effort(
                "claude-code" if harness == "claude" else harness,
                outcome,
                reason,
                tool,
                size,
            )
    except Exception:
        pass


def _capture_session(payload: dict[str, Any], harness: str) -> str | None:
    from varde_toz.config import env_os

    configured = env_os("TOZ_SESSION")
    if configured:
        return configured
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    canonical = "claude-code" if harness == "claude" else harness
    return f"{canonical}-{session_id}"


def _extract(
    tool: str, tool_input: dict[str, Any], response: Any, harness: str
) -> dict[str, Any] | None:
    from pathlib import Path

    path: list[str] | None = None
    if isinstance(response, dict) and (
        isinstance(response.get("stdout"), str)
        or isinstance(response.get("output"), str)
    ):
        stdout_value = response.get("stdout")
        if not isinstance(stdout_value, str):
            stdout_value = response.get("output", "")
        stdout = stdout_value if isinstance(stdout_value, str) else ""
        path = response.get("persistedOutputPath")
        if isinstance(path, str):
            try:
                full = Path(path).read_text()
                if len(full) > len(stdout):
                    stdout = full
            except OSError:
                pass
        stderr = response.get("stderr", "")
        if not isinstance(stderr, str):
            stderr = ""
        completed = _completed(response)
        if harness == "codex" and not completed:
            return None
        source = _source(tool, tool_input)
        return {
            "kind": "streams",
            "stdout": stdout,
            "stderr": stderr,
            "source": source,
            "label": f"{tool}: {_truncate(source, 100)}",
            "exit_code": response.get("exit_code")
            if isinstance(response.get("exit_code"), int)
            else None,
        }
    if (
        isinstance(response, dict)
        and harness in ("claude", "codex")
        and response.get("structuredContent") is not None
    ):
        content = _content_text(response)
        envelope = {
            "contentText": content or "",
            "structuredContent": response["structuredContent"],
        }
        source = _source(tool, tool_input)
        return {
            "kind": "content_field" if content is not None else "structured_hint",
            "stdout": json.dumps(
                envelope, sort_keys=True, indent=2, ensure_ascii=False
            ),
            "stderr": "",
            "source": source,
            "label": f"{tool}: {_truncate(source, 100)}",
            "exit_code": None,
            "structured": response["structuredContent"],
        }
    if isinstance(response, str):
        text = _follow_truncation(response, harness)
        kind = "plain"
    elif isinstance(response, (dict, list)):
        content = _content_text(response)
        if content is not None:
            text, kind = (
                content,
                "content_blocks" if isinstance(response, list) else "content_field",
            )
        elif isinstance(response, dict):
            found = _dominant_text(response)
            if not found:
                return None
            path, text = found
            text, kind = _follow_truncation(text, harness), "field"
        else:
            return None
    else:
        return None
    source = _source(tool, tool_input)
    return {
        "kind": kind,
        "stdout": text,
        "stderr": "",
        "source": source,
        "label": f"{tool}: {_truncate(source, 100)}",
        "exit_code": None,
        "field_path": path if kind == "field" else None,
    }


def _completed(response: dict[str, Any]) -> bool:
    if "exit_code" in response:
        return isinstance(response["exit_code"], int)
    status = response.get("status")
    if isinstance(status, str):
        return status.lower() in (
            "complete",
            "completed",
            "done",
            "exited",
            "finished",
            "success",
        )
    return "session_id" not in response and "process_id" not in response


def _truncate(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return value[: max(0, maximum - 1)] + "…"


def _source(tool: str, value: dict[str, Any]) -> str:
    if isinstance(value.get("pattern"), str) and isinstance(value.get("path"), str):
        return f"{tool.lower()} {value['pattern']} {value['path']}"
    for key in (
        "command",
        "cmd",
        "file_path",
        "filePath",
        "path",
        "url",
        "query",
        "pattern",
    ):
        if isinstance(value.get(key), str) and value[key]:
            return value[key]
    return f"{tool} {json.dumps(value, separators=(',', ':'), ensure_ascii=False)}"


def _content_text(value: Any) -> str | None:
    items = (
        value
        if isinstance(value, list)
        else value.get("content")
        if isinstance(value, dict)
        else None
    )
    if isinstance(items, list):
        texts = [
            item["text"]
            for item in items
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]
        return "\n".join(texts) if texts else None
    return None


def _dominant_text(value: dict[str, Any]) -> tuple[list[str], str] | None:
    metadata = {
        "filePath",
        "file_path",
        "url",
        "type",
        "mode",
        "durationMs",
        "code",
        "codeText",
        "title",
    }
    best: tuple[list[str], str] | None = None

    def visit(obj: dict[str, Any], depth: int, prefix: list[str]) -> None:
        nonlocal best
        for key, child in obj.items():
            if key in metadata:
                continue
            text = (
                child
                if isinstance(child, str)
                else "\n".join(child)
                if isinstance(child, list)
                and child
                and all(isinstance(x, str) for x in child)
                else None
            )
            if text is not None and (best is None or len(text) > len(best[1])):
                best = (prefix + [key], text)
            elif isinstance(child, dict) and depth < 2:
                visit(child, depth + 1, prefix + [key])

    visit(value, 0, [])
    return best


def _follow_truncation(text: str, harness: str) -> str:
    import re
    from pathlib import Path

    marks = ("full output saved to: ", "Full output: ")
    found = max(
        ((text.rfind(mark), mark) for mark in marks if text.rfind(mark) >= 0),
        default=None,
    )
    if found is None:
        return text
    offset, mark = found
    path = text[offset + len(mark) :].split("]", 1)[0].split("\n", 1)[0].strip()
    if not path:
        return text
    candidate = Path(path)
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            return text
        if harness == "opencode":
            from varde_toz.config import data_dir

            roots = [
                Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
                / "opencode/tool-output"
            ]
            root = data_dir()
            if root:
                roots.append(root / "opencode/tool-output")
            if not resolved.name.startswith("tool_") or not any(
                resolved.parent == p.resolve() for p in roots if p.exists()
            ):
                return text
        elif harness == "pi":
            if (
                not re.fullmatch(r"pi-bash-[0-9a-f]+\.log", resolved.name)
                or resolved.parent
                != Path(os.getenv("TMPDIR", tempfile.gettempdir())).resolve()
            ):
                return text
        else:
            return text
        full = resolved.read_text()
        return full if len(full) > len(text) else text
    except OSError:
        return text


def _redact_hook_text(text: str, config: dict[str, Any]) -> tuple[str, list[str], bool]:
    from varde_core.redact import RedactConfig, Redactor, SecretValue

    values = [SecretValue(name, value) for name, value in config["values"].items()]
    result = Redactor(
        RedactConfig(
            builtin=bool(config["builtin"]),
            patterns=config["patterns"],
            values=values,
            reveal=int(config["reveal"]),
        )
    ).redact(text)
    notices = []
    for notice in result.notices:
        noun = "value" if notice.kind == "value" else "pattern"
        if notice.count != 1:
            noun += "s"
        notices.append(f"redacted {notice.count} {noun}: {notice.label}")
    can_reuse = not result.notices or (not config["patterns"] and not config["values"])
    return result.text, notices, can_reuse


def _threshold_for(
    tool: str, tool_input: dict[str, Any], config: dict[str, Any] | None = None
) -> int:
    from varde_toz.config import env_os, load_config

    if config is None:
        config = load_config()
    threshold = int(config.get("threshold", 4096))
    thresholds = config.get("thresholds", {})
    thresholds = thresholds if isinstance(thresholds, dict) else {}
    if tool in thresholds:
        return int(thresholds[tool])
    shell_tool = tool.lower() in ("bash", "cmd", "command", "shell")
    explicit = "threshold" in config or env_os("TOZ_THRESHOLD") is not None
    default_threshold = threshold if not shell_tool or explicit else SHELL_THRESHOLD
    command = next(
        (
            tool_input[key]
            for key in ("command", "cmd")
            if isinstance(tool_input.get(key), str)
        ),
        None,
    )
    is_file_read = tool.lower() == "read"
    if command:
        from varde_toz.hook_input.readonly import is_readonly

        is_file_read = is_file_read or is_readonly(command)
        if (
            not is_file_read
            and not any(token in command for token in ("|", ">", "<", "$(", "`", "\n"))
            and "&" not in command
        ):
            has_read = False
            for segment in command.replace("&&", ";").split(";"):
                words = segment.split()
                if not words or words[0] in ("cd", "echo"):
                    continue
                if words[0] in ("cat", "head", "tail", "nl") or (
                    words[0] == "sed" and "-n" in words[1:]
                ):
                    has_read = True
                else:
                    return default_threshold
            is_file_read |= has_read
    if is_file_read:
        return int(thresholds.get("read", max(INLINE_THRESHOLD, threshold)))
    return default_threshold


def effective_thresholds(config: dict[str, Any]) -> tuple[int, int, int]:
    from varde_toz.config import env_os

    threshold = int(config.get("threshold", 4096))
    overrides = config.get("thresholds", {})
    overrides = overrides if isinstance(overrides, dict) else {}
    explicit = "threshold" in config or env_os("TOZ_THRESHOLD") is not None
    return (
        int(overrides.get("bash", threshold if explicit else SHELL_THRESHOLD)),
        int(overrides.get("read", max(INLINE_THRESHOLD, threshold))),
        threshold,
    )


def _toz_only_shell_source(source: str) -> bool:
    commands: list[list[tuple[str, bool]]] = []
    words: list[tuple[str, bool]] = []
    value: list[str] = []
    started = False
    quoted_assignment_name = False
    quote: str | None = None
    and_or_pending = False

    def flush_word() -> None:
        nonlocal started, quoted_assignment_name
        if started:
            words.append(("".join(value), quoted_assignment_name))
            value.clear()
            started = False
            quoted_assignment_name = False

    index = 0
    size = len(source)
    while index < size:
        char = source[index]
        if quote == "'" and char == "'" or quote == '"' and char == '"':
            quote = None
        elif quote == '"' and char in "$`\\":
            return False
        elif quote:
            value.append(char)
            started = True
        elif char in "'\"":
            if "=" not in value:
                quoted_assignment_name = True
            quote = char
            started = True
        elif char in "\\$`#()<>*?[{}":
            return False
        elif char in "&|":
            if index + 1 >= size or source[index + 1] != char:
                return False
            index += 1
            flush_word()
            if not words:
                return False
            commands.append(words)
            words = []
            and_or_pending = True
        elif char in ";\n":
            flush_word()
            if not words:
                if char == ";":
                    return False
            else:
                commands.append(words)
                words = []
                and_or_pending = False
        elif char in " \t":
            flush_word()
        else:
            value.append(char)
            started = True
        index += 1
    if quote:
        return False
    flush_word()
    if not words and and_or_pending:
        return False
    if words:
        commands.append(words)
    if not commands:
        return False

    has_toz = False
    for command_words in commands:
        index = 0
        while index < len(command_words) and _shell_assignment(command_words[index][0]):
            if command_words[index][1]:
                return False
            index += 1
        if index == len(command_words):
            if index == 0:
                return False
            continue
        command = command_words[index][0]
        if command == "cd":
            if len(command_words) == index + 2 and command_words[index + 1][
                0
            ].startswith("/"):
                continue
            return False
        if command == "env":
            index += 1
            while index < len(command_words) and _shell_assignment(
                command_words[index][0]
            ):
                if command_words[index][1]:
                    return False
                index += 1
        elif command == "command":
            index += 1
            if index < len(command_words) and command_words[index][0] == "-p":
                index += 1
        elif command == "exec":
            index += 1
        if index >= len(command_words) or command_words[index][0].startswith("-"):
            return False
        executable = command_words[index][0].rsplit("/", 1)[-1]
        is_toz = executable in ("toz", "varde-toz") or (
            executable == "varde"
            and index + 1 < len(command_words)
            and command_words[index + 1][0] in ("run", "capture", "note", "event")
        )
        if not is_toz:
            return False
        has_toz = True
    return has_toz


def _shell_assignment(value: str) -> bool:
    name, sep, _value = value.partition("=")
    return bool(
        sep
        and name
        and (name[0].isalpha() or name[0] == "_")
        and name.isascii()
        and all(char.isalnum() or char == "_" for char in name)
    )


def _render_captured(
    harness: str,
    shape: dict[str, Any],
    response: Any,
    preview: str,
    shell: bool,
    notices: list[str],
) -> bytes:
    import re

    text = preview
    if shell:
        from varde_toz.hook_input.compound import heading

        title = heading(shape["source"])
        if title:
            text = title + "\n" + text
    header = text.splitlines()[0] if text else ""
    found = re.search(
        r"captured (.+? bytes) → handle ([a-z0-9_-]+) \(\d+ lines, (\d+) chunks?\)",
        header,
    )
    handle_context = ""
    if found:
        size, handle, chunks = found.groups()
        handle_context = (
            f"varde-toz: stored this output as handle {handle} "
            f"({size}, {chunks} chunks). Later: "
            f'varde run query --handle {handle} "<query>" | '
            f"varde run query --handle {handle} --chunk N"
        )
    hook_notices = ([handle_context] if handle_context else []) + notices
    if harness == "codex" and shape["kind"] in ("streams", "plain"):
        context = "\n".join(([handle_context] if handle_context else []) + notices)
        result = {
            "continue": False,
            "stopReason": text,
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            },
        }
    elif harness == "codex":
        context = "\n".join(notices)
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            }
        }
    else:
        result = _replacement_result(
            harness,
            shape,
            response,
            text,
            "",
            hook_notices if harness == "codex" else notices,
        )
    return (
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def _render_small(
    harness: str,
    shape: dict[str, Any],
    response: Any,
    stdout: str,
    stderr: str,
    shell: bool,
    notices: list[str],
) -> bytes:
    text = stdout
    if shell:
        from varde_toz.hook_input.compound import heading

        title = heading(shape["source"])
        if title:
            text = title + "\n" + text
    if harness == "codex" and shape["kind"] in ("streams", "plain"):
        context = "\n".join(notices)
        result = {
            "continue": False,
            "stopReason": text + stderr,
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            },
        }
    else:
        result = _replacement_result(harness, shape, response, text, stderr, notices)
    return (
        json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def _replacement_result(
    harness: str,
    shape: dict[str, Any],
    response: Any,
    text: str,
    stderr: str,
    notices: list[str],
) -> dict[str, Any]:
    if harness == "codex":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n".join(notices),
            }
        }
    kind = shape["kind"]
    if kind == "streams":
        key, value = (
            "updatedToolOutput",
            {
                "stdout": text,
                "stderr": stderr,
                "interrupted": bool(response.get("interrupted", False))
                if isinstance(response, dict)
                else False,
            },
        )
    elif kind == "plain":
        key, value = "updatedToolOutput", text
    elif kind == "content_blocks":
        key, value = "updatedMCPToolOutput", _content_preview(response, text)
    elif kind == "content_field":
        key, value = "updatedToolOutput", dict(response)
        if shape.get("structured") is not None:
            with suppress(ValueError, KeyError, TypeError):
                value["structuredContent"] = json.loads(shape["stdout"])[
                    "structuredContent"
                ]
        value["content"] = _content_preview(response.get("content"), text)
    elif kind == "structured_hint":
        try:
            redacted = json.loads(shape["stdout"]).get("structuredContent")
        except ValueError, AttributeError:
            redacted = (
                response.get("structuredContent")
                if isinstance(response, dict)
                else None
            )
        if isinstance(response, dict) and redacted == response.get("structuredContent"):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": "\n".join(notices),
                }
            }
        key, value = "updatedToolOutput", dict(response)
        with suppress(ValueError, KeyError, TypeError):
            value["structuredContent"] = json.loads(shape["stdout"])[
                "structuredContent"
            ]
    elif kind == "field":
        key, value = "updatedToolOutput", dict(response)
        target = value
        path = shape.get("field_path", [])
        for part in path[:-1]:
            if not isinstance(target.get(part), dict):
                target[part] = {}
            target = target[part]
        if path:
            previous = target.get(path[-1])
            target[path[-1]] = [text] if isinstance(previous, list) else text
    else:
        key, value = "updatedToolOutput", text
    output = {"hookSpecificOutput": {"hookEventName": "PostToolUse", key: value}}
    if notices:
        output["hookSpecificOutput"]["additionalContext"] = "\n".join(notices)
    return output


def _content_preview(response: Any, text: str) -> Any:
    items = (
        response
        if isinstance(response, list)
        else response.get("content", [])
        if isinstance(response, dict)
        else []
    )
    result = []
    replaced = False
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("type") == "text":
            if not replaced:
                result.append({"type": "text", "text": text})
                replaced = True
        else:
            result.append(item)
    return result


def _session_start(harness: str, config: dict[str, Any], providers: list[str]) -> None:
    from pathlib import Path

    from varde_core.constants import TOZ_BLOCK_END, TOZ_BLOCK_START

    instructions = config.get("instructions", {})
    targets = instructions.get("targets", []) if isinstance(instructions, dict) else []
    has_block = False
    for target in targets if isinstance(targets, list) else []:
        if not isinstance(target, str):
            continue
        try:
            content = Path(target).read_text()
            has_block |= _has_managed_block(content, TOZ_BLOCK_START, TOZ_BLOCK_END)
        except OSError:
            continue
    sections = []
    if "toz_note" in providers and not has_block:
        from varde_toz.commands.event_note import note_text

        sections.append(note_text())
    joined = "\n\n".join(sections)
    if harness in ("claude", "codex"):
        value = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": joined,
            }
        }
        print(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        )
    elif joined:
        print(joined)


def _has_managed_block(content: str, start_marker: str, end_marker: str) -> bool:
    start = content.find(start_marker)
    while start >= 0:
        end = content.find(end_marker, start + len(start_marker))
        if end >= 0:
            return True
        start = content.find(start_marker, start + len(start_marker))
    return False
