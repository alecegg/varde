"""Pure prompt, hygiene, call planning, response, and logging operations."""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Literal, TypedDict

Choice = Literal["A", "B", "tie"]
Order = Literal["AB", "BA"]
_FORBIDDEN = (
    "over_split",
    "sensible",
    "padded",
    "tiny",
    "variant",
    "golden",
    "monolith",
    "label",
)
_PATH = re.compile(
    r"(?:^|\s)(?:/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*"
    r"|[A-Za-z]:\\[^\s]+|(?:\.{1,2}/)?[\w.-]+/(?:[\w.-]+/)*[\w.-]+\.[A-Za-z0-9]{1,8})(?=$|[\s:])"
)
_DOCSTRING = re.compile(r'(?s)(""".*?"""|\'\'\'.*?\'\'\')')
_LINE_COMMENT = re.compile(r"(?m)^\s*(?:#|//|/\*|\*)\s*(.*)$")
_TRAILING_COMMENT = re.compile(r"(?m)(?<=\S)\s+(?:#|//)\s*(.*)$")
_REVEALING_COMMENT = re.compile(
    r"\b(?:refactor\w*|original|helper|split|version\w*)\b", re.IGNORECASE
)


class CallSpec(TypedDict):
    order: Order
    repeat: int
    left: str
    right: str


class HygieneResult(TypedDict):
    excluded: bool
    reasons: list[str]


class ParsedResponse(TypedDict):
    parsed: dict[str, object] | None
    parse_ok: bool
    retry_count: int
    retry: bool


class Verdict(TypedDict):
    choice: Choice | Literal["inconsistent"]
    confidence: str | None
    valid_count: int


class RunLogRecord(TypedDict):
    run_id: str
    pair_id: str
    lens: str
    lens_sha256: str
    idiom_notes_sha256: str
    model_id: str
    provider_version: str | None
    client_name: str
    client_version: str
    temperature: object
    seed: object
    max_tokens: object
    top_p: object
    thinking_settings: object
    order: Order
    seed_index: int
    prompt_sha256: str
    system_prompt_sha256: str | None
    response_raw: str
    parsed: dict[str, object] | None
    parse_ok: bool
    retry_count: int
    tokens_in: int | None
    tokens_out: int | None
    request_id: str | None
    timestamp: str


def opaque_pair_id(pair_id: str) -> str:
    """Derive a stable opaque identifier for presentation to a judge."""
    return hashlib.sha256(pair_id.encode("utf-8")).hexdigest()


def client_identity(client: str) -> dict[str, str | None]:
    """Return the configured public identity for a supported client adapter."""
    identities = {
        "codex": {
            "client_name": "codex",
            "model_id": "gpt-6-luna",
            "system_prompt_sha256": None,
        },
        "pi": {"client_name": "pi", "model_id": None, "system_prompt_sha256": None},
        "claude-code": {
            "client_name": "claude-code",
            "model_id": None,
            "system_prompt_sha256": None,
        },
    }
    try:
        return identities[client]
    except KeyError as error:
        raise ValueError(f"unknown panel client: {client}") from error


def assemble_prompt(
    lens_body: str,
    idiom_notes: str,
    task: str,
    pair: tuple[str, str, str],
    order: Order = "AB",
) -> str:
    """Build the judge payload from rubric, language notes, task, and code only."""
    if order not in ("AB", "BA"):
        raise ValueError("order must be AB or BA")
    pair_id, left_code, right_code = pair
    shown_left, shown_right = (
        (left_code, right_code) if order == "AB" else (right_code, left_code)
    )
    return (
        f"{lens_body.rstrip()}\n\n"
        f"LANGUAGE IDIOM NOTES\n{idiom_notes.strip()}\n\n"
        f"TASK: {task.strip()}\n"
        f"PAIR ID: {pair_id}\n\n"
        f"A:\n```\n{shown_left.rstrip()}\n```\n\n"
        f"B:\n```\n{shown_right.rstrip()}\n```"
    )


def check_hygiene(code_a: str, code_b: str, task: str) -> HygieneResult:
    """Exclude pairs whose code/task leaks labels or has unequal comment volume."""
    reasons: list[str] = []
    for text in (code_a, code_b, task):
        lowered = text.lower()
        if any(word in lowered for word in _FORBIDDEN):
            reasons.append("forbidden terminology")
            break
        if _PATH.search(text):
            reasons.append("path-like text")
            break
    comments_a = _comment_classes(code_a)
    comments_b = _comment_classes(code_b)
    if len(comments_a) != len(comments_b) or comments_a != comments_b:
        reasons.append("comment parity mismatch")
    if any(
        _REVEALING_COMMENT.search(comment)
        for comment in (*_comment_texts(code_a), *_comment_texts(code_b))
    ):
        reasons.append("prompt-revealing comment")
    return {"excluded": bool(reasons), "reasons": reasons}


def build_call_specs(repeats: int) -> list[CallSpec]:
    """Plan independent calls for both orders, repeat by repeat."""
    if repeats < 1:
        raise ValueError("repeats must be positive")
    return [
        {"order": order, "repeat": repeat, "left": order[0], "right": order[1]}
        for order in ("AB", "BA")
        for repeat in range(1, repeats + 1)
    ]


def map_verdict(
    results: Sequence[Mapping[str, object]], mode: Literal["acceptance", "development"]
) -> Verdict:
    """Map valid order judgements to a choice when the required threshold agrees."""
    threshold = 5 if mode == "acceptance" else 4
    valid = [result for result in results if result.get("choice") in ("A", "B", "tie")]
    normalized = [
        {
            **result,
            "choice": _original_choice(str(result["choice"]), result.get("order")),
        }
        for result in valid
    ]
    counts = Counter(str(result["choice"]) for result in normalized)
    winner = next(
        (choice for choice in ("A", "B", "tie") if counts[choice] >= threshold), None
    )
    agreeing = (
        [result for result in normalized if result.get("choice") == winner]
        if winner
        else []
    )
    confidence = min(
        (
            str(result["confidence"])
            for result in agreeing
            if result.get("confidence") is not None
        ),
        key=_confidence_rank,
        default=None,
    )
    choice: Choice | Literal["inconsistent"] = winner or "inconsistent"  # type: ignore[assignment]
    if len(valid) < threshold:
        choice = "inconsistent"
        confidence = None
    return {"choice": choice, "confidence": confidence, "valid_count": len(valid)}


def parse_response(response_raw: str, retry_count: int = 0) -> ParsedResponse:
    """Parse and validate a response, requesting at most one retry."""
    parsed: dict[str, object] | None = None
    try:
        value = json.loads(response_raw)
        if isinstance(value, dict) and value.get("choice") in ("A", "B", "tie"):
            confidence = value.get("confidence")
            if confidence in ("high", "medium", "low"):
                parsed = value
    except json.JSONDecodeError:
        pass
    parse_ok = parsed is not None
    return {
        "parsed": parsed,
        "parse_ok": parse_ok,
        "retry_count": retry_count if parse_ok else min(retry_count + 1, 1),
        "retry": not parse_ok and retry_count < 1,
    }


def run_log_record(**fields: object) -> RunLogRecord:
    """Build a complete per-call JSONL-shaped log record."""
    required = set(RunLogRecord.__annotations__)
    missing = required - fields.keys()
    extra = fields.keys() - required
    if missing or extra:
        raise ValueError(
            f"invalid run log fields; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return dict(fields)


def _comment_classes(code: str) -> list[int]:
    return sorted(len(comment) // 20 for comment in _comment_texts(code))


def _comment_texts(code: str) -> list[str]:
    comments = [match.group(0).strip() for match in _DOCSTRING.finditer(code)]
    without_docstrings = _DOCSTRING.sub("", code)
    comments.extend(_LINE_COMMENT.findall(without_docstrings))
    comments.extend(_TRAILING_COMMENT.findall(without_docstrings))
    return [comment.strip() for comment in comments]


def _confidence_rank(confidence: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(confidence, -1)


def _original_choice(choice: str, order: object) -> str:
    if order == "BA" and choice in ("A", "B"):
        return "B" if choice == "A" else "A"
    return choice


def build_codex_command(
    executable: str, working_directory: str, schema_path: str, output_path: str
) -> list[str]:
    """Build the configured Codex CLI invocation without executing it."""
    return [
        executable,
        "exec",
        "-m",
        "gpt-6-luna",
        "-c",
        'model_reasoning_effort="medium"',
        "-s",
        "read-only",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-C",
        working_directory,
        "--output-schema",
        schema_path,
        "--json",
        "-o",
        output_path,
        "-",
    ]


def pi_command(*_args: object, **_kwargs: object) -> list[str]:
    """Report that the Pi adapter has not been configured."""
    raise NotImplementedError("Pi panel client is not configured")


def claude_code_command(*_args: object, **_kwargs: object) -> list[str]:
    """Report that the Claude Code adapter has not been configured."""
    raise NotImplementedError("Claude Code panel client is not configured")
