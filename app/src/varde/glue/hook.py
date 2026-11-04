"""In-process dispatch for the harness hook events."""

from __future__ import annotations

import json
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

from .tool_install_guard import deny_worktree_tool_install
from .worktree_prune_guard import deny_worktree_prune, resolve_unmailboxed_caller

MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
HARNESSES = ("claude", "codex", "opencode", "pi")
PROVIDER_TIMEOUT = 5.0
SESSION_PROVIDERS = (
    "orchestration",
    "toz_note",
    "nav_map",
    "inbox",
    "loop_nudge",
    "memory",
)
SUBAGENT_HARNESSES = ("claude", "codex")


def dispatch(payload: Any, harness: str) -> int:
    """Dispatch an event payload. `payload` has event and optional input fields."""
    if harness not in HARNESSES:
        print(
            "varde hook: --harness <claude|codex|opencode|pi> is required",
            file=sys.stderr,
        )
        return 2
    if not isinstance(payload, dict):
        return 0
    event = payload.get("event")
    if event == "pre-tool-use":
        pre_tool_use(harness, payload.get("input", b""))
    elif event == "post-tool-use":
        post_tool_use(harness, payload.get("input", b""))
    elif event == "stop":
        stop(harness, payload.get("input", b""))
    elif event == "user-prompt-submit":
        user_prompt_submit(harness, payload.get("input", b""))
    elif event == "session-start":
        session_start(harness, payload.get("input", b""))
    elif event == "subagent-start":
        subagent_start(harness, payload.get("input", b""))
    else:
        return 2
    return 0


def pre_tool_use(harness: str, raw: bytes | str) -> None:
    try:
        value = json.loads(raw)
    except ValueError, TypeError:
        return
    if not isinstance(value, dict) or value.get("tool_name") != "Bash":
        return
    tool_input = value.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    cwd = value.get("cwd")
    if not isinstance(command, str):
        return

    prune_detected = False

    def resolve_prune_address() -> str | None:
        nonlocal prune_detected
        prune_detected = True
        if "agent_id" in value:
            return None
        try:
            from .inbox_hook import resolve_address, runner_on

            if not runner_on():
                return resolve_unmailboxed_caller(value, cwd)

            return resolve_address(harness, value.get("session_id"))
        except Exception:  # noqa: BLE001 - unresolved callers must be denied.
            return None

    prune_reason = deny_worktree_prune(command, resolve_prune_address)
    if prune_detected:
        from .hook_record import record_firing

        record_firing("hook-pre-tool-worktree-prune", blocked=prune_reason is not None)
        if prune_reason is not None:
            _print_pre_tool_deny(prune_reason)
            return

    if not isinstance(cwd, str):
        return
    reason = deny_worktree_tool_install(command, cwd)
    if reason:
        _print_pre_tool_deny(reason)
        from .hook_record import record_firing

        record_firing("hook-pre-tool-install-guard", blocked=True)


def _print_pre_tool_deny(reason: str) -> None:
    # Claude Code PreToolUse contract: https://code.claude.com/docs/en/hooks
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def _config() -> dict[str, Any]:
    import tomllib

    from varde_learn.knowledge.memory_config import config_path

    path = config_path()
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, tomllib.TOMLDecodeError:
        return {}


def _session_config() -> tuple[dict[str, Any], str | None]:
    import tomllib

    from varde_learn.knowledge.memory_config import config_path

    path: Path | None = None
    content = ""
    try:
        path = config_path()
        if not path.exists():
            return {}, None
        content = path.read_text(encoding="utf-8")
        return tomllib.loads(content), None
    except (OSError, tomllib.TOMLDecodeError) as error:
        if isinstance(error, tomllib.TOMLDecodeError):
            assert path is not None  # noqa: S101 - type narrowing only.
            return {}, _config_parse_error(path, content, error)
        if path is None:
            return {}, f"failed to resolve memory path config: {error}"
        return {}, f"failed to read memory path config {path}: {error}"


def _config_parse_error(path: Path, content: str, error: Any) -> str:
    message = str(error)
    if not message.startswith("Expected ']' at the end of a table declaration"):
        return f"failed to parse memory path config {path}: {message}"
    line_number = error.lineno
    column = error.colno
    line = content.splitlines()[line_number - 1]
    diagnostic = (
        f"TOML parse error at line {line_number}, column {column}\n"
        f"  |\n{line_number} | {line}\n  | {' ' * (column - 1)}^\n"
        "invalid table header\nexpected `.`, `]`\n"
    )
    return f"failed to parse memory path config {path}: {diagnostic}"


def _providers(
    config: dict[str, Any], key: str, defaults: tuple[str, ...]
) -> list[str]:
    """Configured providers for an event; an explicit list replaces the defaults,
    so `memory` runs at SessionStart only when listed."""
    hooks = config.get("hooks")
    section = hooks.get(key) if isinstance(hooks, dict) else None
    providers = section.get("providers") if isinstance(section, dict) else None
    if providers is None:
        return list(defaults)
    return (
        [item for item in providers if isinstance(item, str)]
        if isinstance(providers, list)
        else []
    )


def _bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode()
    return b""


def _session_notes():
    from . import session_notes

    return session_notes


def post_tool_use(harness: str, raw: bytes) -> None:
    # A harness that sends nothing has no event to capture; parsing the empty
    # payload would record it as a failed invalid-payload outcome.
    if not raw.strip():
        return
    config = _config()
    raw = raw[: MAX_PAYLOAD_BYTES + 1]
    if len(raw) > MAX_PAYLOAD_BYTES:
        return
    capture = b""
    contexts = []
    for name in _providers(
        config, "post_tool_use", ("capture", "session_notes", "inbox")
    ):
        if name == "capture":
            from varde_toz.hook import _capture_hook

            capture = _capture_hook(raw, harness)
        elif name == "session_notes":
            try:
                value = json.loads(raw)
                sid = value.get("session_id") if isinstance(value, dict) else None
                if (
                    isinstance(sid, str)
                    and isinstance(value, dict)
                    and "agent_id" not in value
                ):
                    context = _session_notes().nudge(harness, sid, raw, config)
                    if context:
                        contexts.append(context)
            except ValueError, ImportError:
                pass
        elif name == "inbox":
            try:
                from .inbox_hook import prompt_inbox

                sections = prompt_inbox(harness, raw)
                contexts.extend(sections)
            except OSError, ValueError, ImportError:
                pass
        else:
            print(f"varde hook: unknown provider `{name}` skipped", file=sys.stderr)
    capture = _rust_capture_output(capture)
    if not contexts:
        if capture:
            sys.stdout.buffer.write(capture)
        return
    try:
        output = json.loads(capture) if capture else {}
    except ValueError, UnicodeDecodeError:
        output = {}
    if not isinstance(output, dict):
        output = {}
    target = output
    if harness in ("claude", "codex"):
        specific = output.get("hookSpecificOutput")
        if not isinstance(specific, dict):
            specific = {"hookEventName": "PostToolUse"}
            output["hookSpecificOutput"] = specific
        target = specific
    _append_context(target, "additionalContext", "\n\n".join(contexts))
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _rust_capture_output(raw: bytes) -> bytes:
    try:
        value = json.loads(raw)
    except ValueError, UnicodeDecodeError:
        return raw

    def normalize(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: normalize(value) for key, value in item.items()}
        if isinstance(item, list):
            return [normalize(value) for value in item]
        if isinstance(item, str):
            lines = item.splitlines(keepends=True)
            for index, line in enumerate(lines):
                ending = "\n" if line.endswith("\n") else ""
                content = line.removesuffix("\n")
                if content.startswith("… ") and content.endswith(
                    " more section(s) omitted"
                ):
                    lines[index] = (
                        f"     {content.removesuffix(' section(s) omitted')}{ending}"
                    )
            return "".join(lines)
        return item

    return json.dumps(
        normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _append_context(target: dict[str, Any], key: str, addition: str) -> None:
    previous = target.get(key)
    target[key] = (
        f"{previous}\n\n{addition}"
        if isinstance(previous, str) and previous
        else addition
    )


def user_prompt_submit(harness: str, raw: bytes) -> None:
    from .inbox_hook import prompt_inbox

    config = _config()
    notices: list[str] = []
    sections: list[str] = []
    for name in _providers(config, "user_prompt_submit", ("inbox",)):
        if name != "inbox":
            notices.append(f"varde hook: unknown provider `{name}` skipped")
            continue
        try:
            lines = prompt_inbox(harness, raw)
            sections.extend(lines)
        except (OSError, ValueError, ImportError) as exc:
            notices.append(f"varde hook: provider `inbox` skipped: {exc}")
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict) and "agent_id" not in payload:
            session_id = payload.get("session_id")
            if isinstance(session_id, str):
                checkpoint = _session_notes().turn_prompt(harness, session_id)
                if checkpoint:
                    sections.append(checkpoint)
    except (OSError, ValueError, ImportError) as exc:
        notices.append(f"varde hook: pipeline checkpoint prompt skipped: {exc}")
    for notice in notices:
        print(notice, file=sys.stderr)
    if sections:
        joined = "\n".join(sections)
        output = (
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": joined,
                    }
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if harness in ("claude", "codex")
            else joined
        )
        try:
            sys.stdout.write(output + "\n")
        except BrokenPipeError:
            return


def stop(harness: str, raw: bytes) -> None:
    from .inbox_hook import prompt_inbox

    try:
        payload = json.loads(raw)
    except ValueError, UnicodeDecodeError:
        return
    if not isinstance(payload, dict) or "agent_id" in payload:
        return
    try:
        lines = prompt_inbox(harness, raw, banner_enabled=False, surface="stop")
    except OSError, ValueError, ImportError:
        lines = []
    mail = [line for line in lines if line.startswith("inbox for ")]
    checkpoint_prompt = None
    session_id = payload.get("session_id")
    if isinstance(session_id, str):
        try:
            checkpoint_prompt = _session_notes().turn_end(harness, session_id, raw)
        except (OSError, ValueError, ImportError) as error:
            checkpoint_prompt = (
                f"Pipeline checkpoint persistence failed: {error}. "
                "Retry before stopping."
            )
    reasons = [*mail, *([checkpoint_prompt] if checkpoint_prompt else [])]
    if not reasons:
        return
    print(
        json.dumps(
            {"decision": "block", "reason": "\n".join(reasons)},
            separators=(",", ":"),
        )
    )
    from .hook_record import record_firing

    record_firing("hook-stop-inbox-block", blocked=True)


def session_start(harness: str, raw: bytes) -> None:
    config, config_error = _session_config()
    sid = _session_id(raw)
    sections = _session_identity_sections(harness, sid)
    providers, targets, notices = _session_providers(config, config_error)
    provider_sections, provider_notices = _run_session_providers(
        providers, targets, harness, raw
    )
    notices.extend(provider_notices)
    sections.extend(provider_sections)
    for notice in notices:
        print(notice, file=sys.stderr)
    sections.extend(notices)
    _write_session_output(harness, sections)


def subagent_start(harness: str, raw: bytes) -> None:
    """Give a starting subagent the memory pointer for its `agent_type`.

    Runs only where the harness has the event (Claude Code, Codex) and the
    `memory` session provider is on; prints nothing when there is no pointer.
    """
    if harness not in SUBAGENT_HARNESSES:
        return
    config, config_error = _session_config()
    if config_error is not None or "memory" not in _providers(
        config, "session_start", SESSION_PROVIDERS
    ):
        return
    from varde_workflow.lib import WithinError, within

    from .memory_subagent import subagent_section

    try:
        text = within(PROVIDER_TIMEOUT, lambda: subagent_section(raw))
    except WithinError as error:
        reason = "timed out after 5s" if error.reason == "timed_out" else "failed"
        print(f"varde hook: provider `memory` skipped: {reason}", file=sys.stderr)
        return
    if text.strip():
        _write_session_output(harness, [text.strip()], "SubagentStart")


def _session_id(raw: bytes) -> str | None:
    try:
        value = json.loads(raw[: MAX_PAYLOAD_BYTES + 1])
    except ValueError, UnicodeDecodeError:
        return None
    sid = value.get("session_id") if isinstance(value, dict) else None
    return sid if isinstance(sid, str) else None


def _session_identity_sections(harness: str, sid: str | None) -> list[str]:
    if sid is None:
        return []
    sections = [f"varde session: {sid}"]
    notes_path = _session_notes().reserve_session(harness, sid)
    if notes_path:
        sections.append(f"varde session notes: {notes_path}")
    return sections


def _session_providers(
    config: dict[str, Any], config_error: str | None
) -> tuple[list[str], list[Any], list[str]]:
    from varde_workflow.lib import SETUP_WARNING

    instructions = config.get("instructions")
    targets = instructions.get("targets", []) if isinstance(instructions, dict) else []
    if config_error is not None:
        return (
            [],
            [],
            [f"varde hook: config unreadable ({config_error}); no providers run"],
        )
    notices = [f"varde hook: {SETUP_WARNING}"] if not targets else []
    providers = _providers(
        config,
        "session_start",
        SESSION_PROVIDERS,
    )
    return providers, targets, notices


def _nav_map_text() -> str:
    from varde_code.index.paths import repo_db_path
    from varde_code.query.nav_map import nav_map_text

    from varde.glue.contracts import error_envelope_code

    repo_root = Path.cwd()
    text = nav_map_text(
        {"repoRoot": str(repo_root), "dbPath": str(repo_db_path(repo_root))}, True
    )
    code = error_envelope_code(text)
    if code == "index_missing":
        return ""
    if code is not None:
        raise ValueError(code)
    return text


def _run_session_providers(
    providers: list[str], targets: list[Any], harness: str, raw: bytes
) -> tuple[list[str], list[str]]:
    from varde_workflow.lib import WithinError, has_managed_block, within

    sections: list[str] = []
    notices: list[str] = []
    for name in providers:
        if name == "inbox":
            with suppress(OSError, ValueError, ImportError):
                sections.extend(_session_inbox(harness, raw))
            continue
        if name == "orchestration":
            continue
        if name == "toz_note":
            if not any(
                has_managed_block(Path(target))
                for target in targets
                if isinstance(target, str)
            ):
                from varde_toz.commands.event_note import note_text

                sections.append(note_text())
            continue
        if name == "loop_nudge":
            found, skipped = _loop_nudge_provider()
            sections.extend(found)
            notices.extend(skipped)
            continue
        if name == "memory":
            found, skipped = _memory_provider(harness, raw)
            sections.extend(found)
            notices.extend(skipped)
            continue
        if name == "nav_map":
            try:
                text = within(PROVIDER_TIMEOUT, _nav_map_text)
                if text.strip():
                    sections.append(text.strip())
            except WithinError as error:
                if error.reason == WithinError.TIMED_OUT:
                    reason = "varde map timed out after 5s"
                elif isinstance(error.__cause__, ValueError):
                    reason = str(error.__cause__)
                else:
                    reason = "varde map failed: provider panicked"
                notices.append(f"varde hook: provider `nav_map` skipped: {reason}")
            except (ValueError, AttributeError) as error:
                notices.append(f"varde hook: provider `nav_map` skipped: {error}")
            continue
        notices.append(f"varde hook: unknown provider `{name}` skipped")
    return sections, notices


def _loop_nudge_provider() -> tuple[list[str], list[str]]:
    from varde_workflow.lib import WithinError, within

    from .loop_nudge import loop_nudge_section

    try:
        text = within(PROVIDER_TIMEOUT, lambda: loop_nudge_section(Path.cwd()))
    except WithinError as error:
        reason = "timed out after 5s" if error.reason == "timed_out" else "failed"
        return [], [f"varde hook: provider `loop_nudge` skipped: {reason}"]
    return ([text] if text else []), []


def _memory_provider(harness: str, raw: bytes) -> tuple[list[str], list[str]]:
    from varde_workflow.lib import WithinError, within

    from .memory_hook import memory_section

    try:
        text = within(PROVIDER_TIMEOUT, lambda: memory_section(harness, raw))
    except WithinError as error:
        reason = "timed out after 5s" if error.reason == "timed_out" else "failed"
        return [], [f"varde hook: provider `memory` skipped: {reason}"]
    return ([text.strip()] if text.strip() else []), []


def _session_inbox(harness: str, raw: bytes) -> list[str]:
    from .inbox_hook import prompt_inbox, runner_on

    if not runner_on():
        return []
    payload = json.loads(raw)
    lines = prompt_inbox(harness, raw)
    if isinstance(payload, dict) and "agent_id" not in payload:
        from .inbox_hook import resolve_address

        address = resolve_address(harness, payload.get("session_id"))
        if payload.get("source") == "compact":
            message = (
                f"varde address: {address}"
                if address
                else "varde: this session is unregistered; mail is held. "
                "Bind with varde msg address bind <marker>."
            )
            lines.insert(0, message)
        elif not address and not lines:
            lines.append(
                "varde: this session is unregistered; mail is held. "
                "Bind with varde msg address bind <marker>."
            )
    return lines


def _write_session_output(
    harness: str, sections: list[str], event: str = "SessionStart"
) -> None:
    joined = "\n\n".join(sections)
    if harness in ("claude", "codex"):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": event,
                        "additionalContext": joined,
                    }
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    elif joined:
        print(joined)
