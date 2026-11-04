"""Reserve stable per-session note paths and nudge on context threshold crossings."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from varde_learn.knowledge.memory import MemoryPaths
from varde_learn.knowledge.memory_config import config_path, load_config

from . import handoff_checkpoint

MAX_SESSION_ID = 256
DEFAULT_NOTES_AT_TOKENS = 200_000
PIPELINE_WORKER_NOTES_AT_TOKENS = 250_000
SESSION_NOTES_DIR = "session-notes"
NOTES_FILE = "notes.md"
LEGACY_HANDOFFS_DIR = "handoffs"
LEGACY_HANDOFF_FILE = "handoff.md"


def validate_session_id(value: str) -> str | None:
    """Accept bounded printable IDs that cannot control paths or logs."""
    if (
        not value
        or len(value.encode()) > MAX_SESSION_ID
        or any(unicodedata.category(char) == "Cc" for char in value)
    ):
        return None
    return value


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


def _session_paths(harness: str, session_id: str) -> tuple[Path, Path]:
    root = config_path().parent / "sessions"
    key = f"{harness}-{_session_hash(session_id)}"
    return root / f"{key}.json", root / f"{key}.lock"


def _working_path() -> Path:
    return MemoryPaths.resolve(Path.cwd()).working.path


def _valid_note_path(path: Path, working: Path, suffix: str) -> bool:
    filename = path.name
    parent = path.parent
    session_dir = parent.name
    valid_root = (
        filename == NOTES_FILE and parent.parent == working / SESSION_NOTES_DIR
    ) or (
        filename == LEGACY_HANDOFF_FILE
        and parent.parent == working / LEGACY_HANDOFFS_DIR
    )
    if not path.is_absolute() or not valid_root or not session_dir.endswith(suffix):
        return False
    try:
        return path.resolve().is_relative_to(parent.resolve())
    except OSError:
        return True


def _find_existing_note(working: Path, suffix: str) -> Path | None:
    for directory, filename in (
        (SESSION_NOTES_DIR, NOTES_FILE),
        (LEGACY_HANDOFFS_DIR, LEGACY_HANDOFF_FILE),
    ):
        try:
            matches = sorted(
                candidate / filename
                for candidate in (working / directory).iterdir()
                if (candidate / filename).is_file()
                and _valid_note_path(candidate / filename, working, suffix)
            )
        except OSError:
            continue
        if matches:
            return matches[0]
    return None


def _initial_note_path(working: Path, suffix: str) -> Path:
    existing = _find_existing_note(working, suffix)
    if existing is not None:
        return existing
    from datetime import UTC, datetime

    date = datetime.now(UTC).strftime("%Y-%m-%d")
    return working / SESSION_NOTES_DIR / f"{date}-{suffix}" / NOTES_FILE


def _with_state(harness: str, session_id: str, update: Any) -> Any:
    working = _working_path()
    suffix = f"session-{_session_hash(session_id)}"
    state_path, lock_path = _session_paths(harness, session_id)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except OSError, ValueError:
                state = None
            note_path: Path | None = None
            if (
                isinstance(state, dict)
                and state.get("harness") == harness
                and state.get("session_id") == session_id
            ):
                raw_path = state.get("notes_path", state.get("handoff_path"))
                if isinstance(raw_path, str):
                    candidate = Path(raw_path)
                    if _valid_note_path(candidate, working, suffix):
                        note_path = candidate
            if note_path is None:
                note_path = _initial_note_path(working, suffix)
                state = {
                    "harness": harness,
                    "session_id": session_id,
                    "notes_path": str(note_path),
                    "above_threshold": False,
                    "turn_count": 0,
                    "turn_waiting": False,
                    "pending_turn": 1,
                    "current_tokens": None,
                    "handoff_prompted_turn": 0,
                    "handoff_completed_turn": 0,
                }
            else:
                assert isinstance(state, dict)  # noqa: S101 - Narrows state after validated path reuse.
                state["notes_path"] = str(note_path)
            result = update(state)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{state_path.name}.", suffix=".tmp", dir=state_path.parent
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    json.dump(state, output, separators=(",", ":"))
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary_name, state_path)
            except OSError:
                with contextlib.suppress(OSError):
                    os.unlink(temporary_name)
                raise
        except OSError:
            return None
        else:
            return result
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def reserve_session(harness: str, session_id: str) -> Path | None:
    """Reserve and persist this session's stable session-notes path."""
    if validate_session_id(session_id) is None:
        return None
    return _with_state(harness, session_id, lambda state: Path(state["notes_path"]))


def _notes_threshold(config: Any, window: int | None) -> tuple[int, bool]:
    default = (
        DEFAULT_NOTES_AT_TOKENS
        if window is None
        else max(1, min(DEFAULT_NOTES_AT_TOKENS, window // 10 * 9))
    )
    document = getattr(config, "document", {})
    session = document.get("session") if isinstance(document, dict) else None
    session = session if isinstance(session, dict) else None
    new = session.get("notes_at_tokens") if session else None
    deprecated = new is None and bool(session and "handoff_at_tokens" in session)
    value = (
        new
        if new is not None
        else (session.get("handoff_at_tokens") if session else None)
    )
    if value is None:
        return default, False
    if type(value) is int and value >= 0:
        return value, deprecated
    key = "handoff_at_tokens" if deprecated else "notes_at_tokens"
    print(
        f"varde hook: invalid [session].{key}; using {default}",
        file=sys.stderr,
    )
    return default, deprecated


def _harness_kind(harness: str) -> str | None:
    return harness if harness in {"claude", "codex", "opencode", "pi"} else None


def _pipeline_binding(harness: str, session_id: str) -> tuple[str, str] | None:
    """Return the pipeline role and plan id for a bound slot."""
    try:
        from .inbox_hook import resolve_address, runner_on

        if not runner_on():
            return None
        address = resolve_address(harness, session_id)
    except Exception:  # noqa: BLE001 - missing address storage must fail open.
        return None
    if not isinstance(address, str) or not address:
        return None
    for role in ("builder", "reviewer"):
        suffix = f"-{role}"
        if address.endswith(suffix):
            return role, address.removesuffix(suffix)
    if (_working_path() / "plans" / address / "plan.md").is_file():
        return "orchestrator", address
    return None


def _pipeline_worker_role(harness: str, session_id: str) -> str | None:
    """Return builder/reviewer for a session bound to a stable pipeline slot."""
    binding = _pipeline_binding(harness, session_id)
    return binding[0] if binding and binding[0] in {"builder", "reviewer"} else None


def _checkpoint_root(plan_id: str, role: str) -> Path | None:
    if (
        not plan_id
        or Path(plan_id).name != plan_id
        or role
        not in {
            "builder",
            "reviewer",
            "orchestrator",
        }
    ):
        return None
    return (
        _working_path()
        / "plans"
        / plan_id
        / "notes"
        / "checkpoints"
        / f"{plan_id}-{role}"
    )


def turn_prompt(harness: str, session_id: str) -> str | None:
    """Count a new pipeline turn and require its structured checkpoint."""
    binding = _pipeline_binding(harness, session_id)
    if binding is None or validate_session_id(session_id) is None:
        return None
    role, plan_id = binding
    root = _checkpoint_root(plan_id, role)
    if root is None:
        return None

    def update(state: dict[str, Any]) -> tuple[int, Path]:
        turn = int(state.get("turn_count", 0)) + 1
        state["pending_turn"] = turn
        state["role"] = role
        return turn, root / "latest.json"

    result = _with_state(harness, session_id, update)
    if result is None:
        return None
    turn, path = result
    return (
        f"Pipeline {role} turn {turn}: before ending this turn, write a complete "
        f"structured checkpoint to `{path}` with schema_version=1, session_id, "
        "harness, role, turn, current_item, worktree, branch, last_commit, "
        "queue_position, decisions_made, pending_findings, next_actions, "
        "files_touched, and token_usage. Use null for unknown scalar values, "
        "empty lists when there are none, and token_usage status `unavailable` "
        "when no cumulative usage is reported. The Stop hook validates and "
        "renders each turn checkpoint; resume only from that record."
    )


def turn_end(  # noqa: PLR0911 - Guard clauses keep boundary failures explicit.
    harness: str, session_id: str, payload: bytes
) -> str | None:
    """Validate and persist a completed turn, then gate any required handoff."""
    binding = _pipeline_binding(harness, session_id)
    if binding is None or validate_session_id(session_id) is None:
        return None
    role, plan_id = binding
    checkpoint_root = _checkpoint_root(plan_id, role)
    if checkpoint_root is None:
        return None

    def begin_boundary(state: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if state.get("turn_waiting") is True:
            turn = int(state.get("turn_count", 0))
        else:
            turn = int(state.get("turn_count", 0)) + 1
            state["turn_count"] = turn
            state["turn_waiting"] = True
        return turn, dict(state)

    boundary = _with_state(harness, session_id, begin_boundary)
    if not isinstance(boundary, tuple):
        return None
    turn, state = boundary
    raw = _parse_object(payload)
    if turn < 1:
        return None
    checkpoint_path = checkpoint_root / "latest.json"
    try:
        record = handoff_checkpoint.read_checkpoint(checkpoint_path)
    except ValueError:
        return _checkpoint_required(role, turn, checkpoint_path)
    if (
        record["turn"] != turn
        or record["role"] != role
        or record["session_id"] != session_id
    ):
        return _checkpoint_required(role, turn, checkpoint_path)

    context_tokens = _context_tokens(harness, raw)
    if context_tokens is None:
        context_tokens = state.get("current_tokens")
    elif context_tokens is not None:
        _with_state(
            harness,
            session_id,
            lambda current: current.update(current_tokens=context_tokens),
        )
    cumulative_tokens = _reported_cumulative_tokens(raw)
    if cumulative_tokens is not None:
        record["token_usage"] = {
            "status": "reported",
            "cumulative_tokens": cumulative_tokens,
        }
    record["harness"] = harness
    paths = handoff_checkpoint.write_checkpoint(checkpoint_root, record)
    if record["current_item"]:
        ledger = _working_path() / "plans" / plan_id / "notes" / "token-ledger.json"
        usage = record["token_usage"]
        handoff_checkpoint.record_usage(
            ledger,
            record["current_item"],
            session_id,
            usage.get("cumulative_tokens") if usage["status"] == "reported" else None,
        )

    reason = handoff_checkpoint.handoff_reason(
        role, context_tokens if type(context_tokens) is int else None, turn
    )
    if reason is None:
        _with_state(
            harness, session_id, lambda current: current.update(turn_waiting=False)
        )
        return None

    if state.get("handoff_completed_turn") == turn:
        _with_state(
            harness, session_id, lambda current: current.update(turn_waiting=False)
        )
        return None

    def mark_prompted(current: dict[str, Any]) -> None:
        current["handoff_prompted_turn"] = turn

    _with_state(harness, session_id, mark_prompted)
    prompt = handoff_checkpoint.resume_prompt(record)
    return (
        f"Pipeline {role} must hand off at this completed turn ({reason}). "
        f"Checkpoint saved to `{paths.machine}` and rendered to `{paths.human}`. "
        "Send the handoff now and do not start another item. Build the replacement "
        f"prompt from this checkpoint only:\n{prompt}"
    )


def complete_native_handoff(harness: str, session_id: str, turn: int) -> bool:
    """Record orchestrator confirmation that this native slot handed off."""
    if harness not in {"claude", "codex"} or validate_session_id(session_id) is None:
        return False

    def complete(state: dict[str, Any]) -> bool:
        if (
            state.get("turn_count") != turn
            or state.get("handoff_prompted_turn") != turn
            or state.get("turn_waiting") is not True
        ):
            return False
        binding = _pipeline_binding(harness, session_id)
        if binding is None:
            return False
        role, plan_id = binding
        root = _checkpoint_root(plan_id, role)
        if root is None:
            return False
        try:
            record = handoff_checkpoint.read_checkpoint(root / "latest.json")
        except ValueError:
            return False
        if (
            record["session_id"] != session_id
            or record["turn"] != turn
            or record["role"] != role
        ):
            return False
        state["handoff_completed_turn"] = turn
        return True

    return _with_state(harness, session_id, complete) is True


def _checkpoint_required(role: str, turn: int, path: Path) -> str:
    return (
        f"Pipeline {role} turn {turn} cannot finish without its structured checkpoint. "
        f"Write a complete record to `{path}` using the fields in the prior prompt, "
        "then stop again."
    )


def _parse_object(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except UnicodeDecodeError, json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _reported_cumulative_tokens(payload: dict[str, Any]) -> int | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    total = usage.get("total_tokens")
    return total if type(total) is int and total >= 0 else None


def _context_tokens(harness: str, payload: dict[str, Any]) -> int | None:
    from varde_learn.loop.diagnose.context_usage import context_usage

    kind = _harness_kind(harness)
    if kind is None:
        return None
    session_file = next(
        (
            payload[key]
            for key in (
                "transcript_path",
                "session_file",
                "sessionFile",
                "session_path",
            )
            if isinstance(payload.get(key), str)
        ),
        None,
    )
    direct = payload.get("context_usage", payload)
    sample = context_usage(
        kind, session_file, direct if isinstance(direct, dict) else None
    )
    return sample.current_tokens if sample is not None else None


def nudge(
    harness: str, session_id: str, payload: bytes, config: Any | None = None
) -> str | None:
    """Return agent-visible context for the first upward threshold crossing."""
    if validate_session_id(session_id) is None:
        return None
    try:
        value = json.loads(payload)
    except UnicodeDecodeError, json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    from varde_learn.loop.diagnose.context_usage import context_usage

    kind = _harness_kind(harness)
    if kind is None:
        return None
    session_file = next(
        (
            value[key]
            for key in (
                "transcript_path",
                "session_file",
                "sessionFile",
                "session_path",
            )
            if isinstance(value.get(key), str)
        ),
        None,
    )
    direct = value.get("context_usage", value)
    sample = context_usage(
        kind, session_file, direct if isinstance(direct, dict) else None
    )
    if sample is None:
        return None
    config = load_config() if config is None else config
    tokens = sample.current_tokens
    threshold, deprecated = _notes_threshold(config, sample.context_window)
    binding = _pipeline_binding(harness, session_id)
    worker_role = (
        binding[0] if binding and binding[0] in {"builder", "reviewer"} else None
    )
    if worker_role is not None:
        threshold = PIPELINE_WORKER_NOTES_AT_TOKENS
    elif binding and binding[0] == "orchestrator":
        threshold = handoff_checkpoint.ORCHESTRATOR_TOKEN_LIMIT
    if threshold == 0:
        return None

    def update(state: dict[str, Any]) -> Path | None:
        state["current_tokens"] = tokens
        above = tokens >= threshold
        fire = above and not state.get("above_threshold", False)
        state["above_threshold"] = above
        return Path(state["notes_path"]) if fire else None

    path = _with_state(harness, session_id, update)
    if path is None:
        return None
    if deprecated:
        print(
            "varde hook: [session].handoff_at_tokens is deprecated; "
            "use [session].notes_at_tokens",
            file=sys.stderr,
        )
    if worker_role is not None:
        message = (
            f"Pipeline {worker_role} context reached {tokens} tokens "
            f"(threshold {threshold}). Finish this turn, save its structured "
            "checkpoint, and hand off at the Stop boundary. The hard stop is "
            "350000 tokens; the turn limit is 60."
        )
    elif binding and binding[0] == "orchestrator":
        message = (
            f"Pipeline orchestrator context reached {tokens} tokens "
            f"(threshold {handoff_checkpoint.ORCHESTRATOR_TOKEN_LIMIT}). "
            "Finish this turn, checkpoint, and hand off at the Stop boundary."
        )
    else:
        message = (
            f"Context reached {tokens} tokens (threshold {threshold}). "
            f"Main/interactive sessions: create or refresh the session note at {path}; "
            "the user compacts. Orchestrators: write HANDOFF.md in the plan notes dir "
            "and send the handoff to main per varde-orchestrate."
        )
    return message
