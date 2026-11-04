"""Trigger eval scoring for Claude, Codex, and OpenCode traces."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Never, Protocol

from varde_learn.loop.process import RunRequest, run_with_timeout


def _raise(error: Exception) -> Never:
    raise error


@dataclass(frozen=True)
class Harness:
    name: str


CLAUDE = Harness("claude")
CODEX = Harness("codex")
OPENCODE = Harness("opencode")


@dataclass(frozen=True)
class Query:
    query: str
    should_trigger: bool


@dataclass(frozen=True)
class TriggerRequest:
    skill_name: str
    queries_path: Path
    harness: Harness
    runs: int = 1
    timeout_seconds: int = 300
    skill_path: Path | None = None
    split: str = "all"


@dataclass(frozen=True)
class TriggerReport:
    fail_lines: list[str]
    summary_line: str
    failed: bool


class HarnessRunner(Protocol):
    def __call__(
        self, harness: Harness, query: str, query_number: int, timeout_seconds: int
    ) -> tuple[bytes, bytes, int]: ...


AUTH_PHRASES = (
    "not logged in",
    "please run /login",
    "authentication required",
    "log in to continue",
)
SHAPE_ERROR = (
    "queries must be a non-empty JSON array with string query and boolean "
    "should_trigger fields"
)


def contains_auth_phrase(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in AUTH_PHRASES)


def parse_events(trace: bytes) -> list[dict]:
    try:
        lines = trace.decode("utf-8").splitlines()
        events = [json.loads(line.strip()) for line in lines if line.strip()]
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("unusable trace") from error
    if not events:
        raise ValueError("unusable trace")
    return events


def parse_claude(trace: bytes, skill: str) -> bool:
    events = parse_events(trace)
    if any(
        not isinstance(e, dict)
        or e.get("type")
        not in {"system", "assistant", "user", "result", "rate_limit_event"}
        for e in events
    ):
        raise ValueError("unusable Claude trace")
    assistants = [e for e in events if e["type"] == "assistant"]
    if not assistants:
        raise ValueError("unusable Claude trace")
    hit = False
    for event in assistants:
        content = event.get("message", {}).get("content")
        if not isinstance(content, list):
            raise ValueError("unusable Claude trace")
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "tool_use" and item.get("name") == "Skill":
                value = item.get("input")
                if not isinstance(value, dict) or not isinstance(
                    value.get("skill"), str
                ):
                    raise ValueError("unusable Claude trace")
                hit |= value["skill"] == skill
            if item.get("type") == "text" and contains_auth_phrase(
                str(item.get("text", ""))
            ):
                raise ValueError("unusable Claude trace")
    results = [e for e in events if e["type"] == "result"]
    if (
        len(results) != 1
        or results[0].get("subtype") != "success"
        or results[0].get("is_error") is not False
    ):
        raise ValueError("unusable Claude trace")
    return hit


def parse_opencode(trace: bytes, skill: str) -> bool:
    events = parse_events(trace)
    allowed = {"step_start", "text", "reasoning", "tool_use", "step_finish", "error"}
    if any(
        not isinstance(e, dict)
        or e.get("type") not in allowed
        or e.get("type") == "error"
        for e in events
    ):
        raise ValueError("unusable OpenCode trace")
    hit = False
    for event in events:
        kind, part = event["type"], event.get("part")
        if kind == "step_start" and (
            not isinstance(part, dict) or part.get("type") != "step-start"
        ):
            raise ValueError("unusable OpenCode trace")
        if kind == "tool_use":
            state = part.get("state") if isinstance(part, dict) else None
            data = state.get("input") if isinstance(state, dict) else None
            if (
                not isinstance(part, dict)
                or part.get("type") != "tool"
                or not isinstance(part.get("tool"), str)
                or not isinstance(state, dict)
                or state.get("status") != "completed"
                or not isinstance(data, dict)
            ):
                raise ValueError("unusable OpenCode trace")
            if part["tool"] == "skill":
                if not isinstance(data.get("id"), str):
                    raise ValueError("unusable OpenCode trace")
                hit |= data["id"] == skill
        if kind == "step_finish" and (
            not isinstance(part, dict)
            or part.get("type") != "step-finish"
            or part.get("reason") not in {"tool-calls", "stop"}
        ):
            raise ValueError("unusable OpenCode trace")
        if kind == "text" and (
            not isinstance(part, dict)
            or part.get("type") != "text"
            or not isinstance(part.get("text"), str)
            or contains_auth_phrase(part["text"])
        ):
            raise ValueError("unusable OpenCode trace")
    last = events[-1]
    stopped = (
        last.get("type") == "step_finish"
        and last.get("part", {}).get("reason") == "stop"
    )
    final_text = (
        last.get("type") == "text"
        and last.get("part", {}).get("time", {}).get("end") is not None
    )
    if not any(e["type"] == "step_start" for e in events) or not (
        stopped or final_text
    ):
        raise ValueError("unusable OpenCode trace")
    return hit


def load_queries(path: Path) -> list[Query]:
    try:
        values = json.loads(path.read_text())
        if not isinstance(values, list) or not values:
            _raise(ValueError())
        result = []
        for item in values:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("query"), str)
                or not isinstance(item.get("should_trigger"), bool)
            ):
                _raise(ValueError())
            result.append(Query(item["query"], item["should_trigger"]))
    except (OSError, ValueError) as error:
        raise ValueError(SHAPE_ERROR) from error
    else:
        return result


TRAIN_SHARE = 0.6
SPLITS = ("all", "train", "validation")


def _digest(query: Query) -> str:
    return hashlib.sha256(query.query.encode()).hexdigest()


def split_queries(queries: list[Query], split: str) -> list[Query]:
    """Fixed 60/40 train/validation split, stratified by label, independent of order."""
    if split == "all":
        return queries
    train: set[str] = set()
    for label in (True, False):
        group = sorted(
            (item for item in queries if item.should_trigger is label), key=_digest
        )
        train.update(item.query for item in group[: round(len(group) * TRAIN_SHARE)])
    return [item for item in queries if (item.query in train) == (split == "train")]


def precision_recall(outcomes: list[tuple[bool, bool]]) -> tuple[str, str]:
    """Precision and recall of (should_trigger, actual) pairs; n/a when undefined."""
    hits = sum(want and got for want, got in outcomes)
    fired = sum(got for _, got in outcomes)
    wanted = sum(want for want, _ in outcomes)
    return (
        f"{hits / fired:.2f}" if fired else "n/a",
        f"{hits / wanted:.2f}" if wanted else "n/a",
    )


def run_trigger(
    request: TriggerRequest, runner: HarnessRunner | None = None
) -> TriggerReport:
    if request.runs <= 0 or request.timeout_seconds <= 0:
        raise ValueError("--runs and --timeout-seconds must be positive integers")
    if request.split not in SPLITS:
        raise ValueError("--split must be all, train, or validation")
    if not request.queries_path.is_file():
        raise ValueError(f"queries file not found: {request.queries_path}")
    if runner is None and shutil.which(request.harness.name) is None:
        raise ValueError(f"{request.harness.name} CLI is required")
    skill_path = None
    if request.harness == CODEX:
        if request.skill_path is None:
            raise ValueError("Codex proxy requires --skill-path /path/to/SKILL.md")
        skill_path = request.skill_path.resolve()
        if not skill_path.is_file():
            raise ValueError(f"Codex skill path is not a file: {skill_path}")
    elif request.skill_path is not None:
        raise ValueError("--skill-path is only used by the Codex proxy")
    parse = {CLAUDE: parse_claude, OPENCODE: parse_opencode}
    failures: list[str] = []
    passed = 0
    outcomes: list[tuple[bool, bool]] = []
    selected = split_queries(load_queries(request.queries_path), request.split)
    if not selected:
        raise ValueError(f"no queries in the {request.split} split")
    for number, query in enumerate(selected, 1):
        hits = 0
        for _run in range(1, request.runs + 1):
            stdout, stderr, status = (runner or invoke_harness)(
                request.harness, query.query, number, request.timeout_seconds
            )
            if status:
                detail = stderr.decode(errors="replace").splitlines()
                raise RuntimeError(
                    f"{request.harness.name} CLI exited {status} for query {number}"
                    + (f": {detail[0]}" if detail else "")
                )
            if request.harness == CODEX and skill_path is not None:
                from varde_learn.loop.codex import parse_codex

                hit = parse_codex(stdout, skill_path)
            else:
                hit = parse[request.harness](stdout, request.skill_name)
            hits += int(hit)
        actual = hits / request.runs > 0.5
        outcomes.append((query.should_trigger, actual))
        if actual == query.should_trigger:
            passed += 1
        else:
            failures.append(
                f"FAIL [harness={request.harness.name} "
                f"want={str(query.should_trigger).lower()} hits={hits}/{request.runs}] "
                f"{query.query}"
            )
    failed = len(failures) > 0
    suffix = " codex_measure=implicit_read_proxy" if request.harness == CODEX else ""
    precision, recall = precision_recall(outcomes)
    summary = (
        f"evals: pass={passed} fail={len(failures)} skill={request.skill_name} "
        f"harness={request.harness.name} split={request.split} "
        f"precision={precision} recall={recall}{suffix}"
    )
    return TriggerReport(failures, summary, failed)


def invoke_harness(
    harness: Harness, query: str, query_number: int, timeout_seconds: int
) -> tuple[bytes, bytes, int]:
    args = {
        CLAUDE: ["-p", query, "--output-format", "stream-json", "--verbose"],
        OPENCODE: ["run", "--format", "json", query],
        CODEX: ["exec", "--json", query],
    }[harness]
    with (
        tempfile.TemporaryDirectory(prefix="varde-learn-trigger-sbox-") as sandbox,
        tempfile.TemporaryDirectory() as output,
    ):
        stdout_path, stderr_path = Path(output) / "stdout", Path(output) / "stderr"
        outcome = run_with_timeout(
            RunRequest(
                harness.name,
                args,
                Path(sandbox),
                {},
                b"",
                stdout_path,
                stderr_path,
                timeout_seconds,
            )
        )
        if outcome.timed_out:
            raise TimeoutError(
                f"{harness.name} CLI timed out after {timeout_seconds} seconds for "
                f"query {query_number}; no score recorded"
            )
        if outcome.result is None:
            raise TypeError("completed process has no exit result")
        stdout, stderr = stdout_path.read_bytes(), stderr_path.read_bytes()
        if len(stdout) > 16 * 1024 * 1024 or len(stderr) > 64 * 1024:
            raise ValueError(
                f"{harness.name} CLI capture exceeded size limit; no score recorded"
            )
        return stdout, stderr, outcome.result.as_shell_code()
