"""Bounded model extraction and synthesis for daily reviews."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .redact import redact

PROMPT_PREFIX = "varde-daily-review"
DEFAULT_MODEL = "haiku"
MAX_ERROR_CHARS = 300


@dataclass
class Budget:
    """Track token and wall-clock limits, reserving capacity for synthesis."""

    token_limit: int
    wall_clock_seconds: float = 600
    synthesis_fraction: float = 0.2
    synthesis_input_cap: int = 20_000
    started_at: float | None = None
    used_tokens: int = 0
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        if self.token_limit < 1 or self.wall_clock_seconds <= 0:
            raise ValueError("budget limits must be positive")
        if not 0 < self.synthesis_fraction < 1 or self.synthesis_input_cap < 1:
            raise ValueError("synthesis reserve and input cap must be positive")
        if self.started_at is None:
            self.started_at = self.clock()

    @property
    def remaining(self) -> int:
        return max(0, self.token_limit - self.used_tokens)

    @property
    def synthesis_reserve(self) -> int:
        return math.ceil(self.token_limit * self.synthesis_fraction)

    def can_afford(self, estimate: int, *, synthesis: bool = False) -> bool:
        if estimate < 0 or self.remaining < estimate:
            return False
        if (
            self.started_at is not None
            and self.clock() - self.started_at >= self.wall_clock_seconds
        ):
            return False
        return synthesis or self.remaining - estimate >= self.synthesis_reserve

    def charge(self, tokens: int) -> None:
        if tokens < 0:
            raise ValueError("token usage cannot be negative")
        self.used_tokens += tokens


@dataclass(frozen=True)
class ModelResult:
    text: str | None
    tokens: int
    cost_usd: float | None
    status: str
    error: str | None = None


Runner = Callable[..., Any]


@dataclass(frozen=True)
class BatchResult:
    results: list[ModelResult]
    stop_reason: str | None
    stop_error: str | None = None


def review_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load model and per-run limits from the learn review config."""
    config_path = (
        Path(path)
        if path is not None
        else Path.home() / ".config/varde/learn/review.toml"
    )
    try:
        value = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "model_id": DEFAULT_MODEL,
            "token_budget": 20_000,
            "wall_clock_seconds": 600,
        }
    settings = value.get("review", value)
    if not isinstance(settings, dict):
        raise TypeError("review config must contain a table")
    model_id = settings.get("model_id", DEFAULT_MODEL)
    token_budget = settings.get("token_budget", 20_000)
    wall_clock = settings.get("wall_clock_seconds", 600)
    synthesis_cap = settings.get("synthesis_input_cap", 20_000)
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("review model_id must be non-empty")
    for name, number in (
        ("token_budget", token_budget),
        ("synthesis_input_cap", synthesis_cap),
    ):
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise ValueError(f"review {name} must be a positive integer")
    if (
        not isinstance(wall_clock, (int, float))
        or isinstance(wall_clock, bool)
        or wall_clock <= 0
    ):
        raise ValueError("review wall_clock_seconds must be positive")
    return {
        "model_id": model_id,
        "token_budget": token_budget,
        "wall_clock_seconds": wall_clock,
        "synthesis_input_cap": synthesis_cap,
    }


def extract_with_claude(
    prompt: str,
    *,
    budget: Budget,
    model_id: str | None = None,
    runner: Runner = subprocess.run,
    synthesis: bool = False,
    structured_output: bool = False,
) -> ModelResult:
    """Call the official Claude CLI with redacted input and bounded output."""
    resolved_model = model_id or str(review_config()["model_id"])
    safe_prompt = f"{PROMPT_PREFIX}: {redact(prompt)}"
    input_tokens = _estimate_tokens(safe_prompt)
    if synthesis and input_tokens > budget.synthesis_input_cap:
        return ModelResult(None, 0, None, "budget_exhausted")
    if not budget.can_afford(input_tokens, synthesis=synthesis):
        return ModelResult(None, 0, None, "budget_exhausted")
    if not shutil.which("claude") and runner is subprocess.run:
        return ModelResult(None, 0, None, "failed", "claude CLI unavailable")
    output_reserve = 0 if synthesis else budget.synthesis_reserve
    output_cap = budget.remaining - input_tokens - output_reserve
    if output_cap < 1:
        return ModelResult(None, 0, None, "budget_exhausted")
    started_at = budget.started_at if budget.started_at is not None else budget.clock()
    elapsed = budget.clock() - started_at
    remaining_time = budget.wall_clock_seconds - elapsed
    if remaining_time <= 0:
        return ModelResult(None, 0, None, "budget_exhausted")
    completed, invocation_error = _invoke_claude(
        safe_prompt, resolved_model, output_cap, remaining_time, runner
    )
    if invocation_error is not None:
        return invocation_error
    if completed is None:
        return ModelResult(None, 0, None, "failed", "Claude CLI failed")
    return _parse_client_response(
        completed,
        budget=budget,
        input_tokens=input_tokens,
        structured_output=structured_output,
    )


def _invoke_claude(
    prompt: str,
    model_id: str,
    output_cap: int,
    remaining_time: float,
    runner: Runner,
) -> tuple[Any | None, ModelResult | None]:
    try:
        completed = runner(
            [
                "claude",
                "-p",
                "--model",
                model_id,
                "--no-session-persistence",
                "--tools",
                "",
                "--output-format",
                "json",
            ],
            input=prompt,
            env={**os.environ, "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(output_cap)},
            capture_output=True,
            text=True,
            check=False,
            timeout=max(0.001, remaining_time),
        )
    except subprocess.TimeoutExpired:
        return None, ModelResult(None, 0, None, "failed", "Claude CLI timed out")
    except FileNotFoundError:
        return None, ModelResult(None, 0, None, "failed", "Claude CLI unavailable")
    return completed, None


def _parse_client_response(
    completed: Any,
    *,
    budget: Budget,
    input_tokens: int,
    structured_output: bool,
) -> ModelResult:
    raw = completed.stdout or ""
    raw_stderr = completed.stderr or ""
    try:
        response = json.loads(raw)
    except TypeError, json.JSONDecodeError:
        response = None
    if not isinstance(response, dict):
        return _invalid_client_json(
            completed.returncode, raw_stderr, raw, budget, input_tokens
        )
    stderr = redact(raw_stderr)[:MAX_ERROR_CHARS]
    if _is_rate_limited(completed.returncode, raw_stderr, response):
        return _rate_limited_result(response, raw_stderr)
    if response.get("is_error") is True:
        return _client_failure(response, raw, stderr, budget, input_tokens)
    if completed.returncode:
        return ModelResult(
            None,
            0,
            None,
            "failed",
            stderr or "Claude CLI failed",
        )
    usage = response.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    tokens = sum(
        _nonnegative_int(usage.get(key))
        for key in (
            "input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
            "output_tokens",
        )
    )
    if tokens == 0:
        tokens = input_tokens + _estimate_tokens(str(response.get("result", "")))
    budget.charge(tokens)
    value = response.get("result")
    text = value.strip() if isinstance(value, str) else None
    if text is not None and not structured_output:
        text = redact(text)
    if not text:
        return ModelResult(None, tokens, None, "failed", "empty client result")
    cost = response.get("total_cost_usd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        measured_cost = float(cost)
    else:
        measured_cost = None
    return ModelResult(text, tokens, measured_cost, "ok" if text else "failed")


def _rate_limited_result(response: Any, stderr: str) -> ModelResult:
    error = stderr
    if isinstance(response, dict):
        error = response.get("error", "") or response.get("subtype", "") or error
    error = redact(str(error or "rate limited"))[:MAX_ERROR_CHARS]
    return ModelResult(None, 0, None, "rate_limited", error)


def _client_failure(
    response: dict[str, Any], raw: str, stderr: str, budget: Budget, input_tokens: int
) -> ModelResult:
    tokens = input_tokens + _estimate_tokens(raw)
    budget.charge(tokens)
    error = response.get("error") or response.get("subtype") or stderr
    return ModelResult(
        None,
        tokens,
        None,
        "failed",
        redact(str(error or "Claude client error"))[:MAX_ERROR_CHARS],
    )


def _invalid_client_json(
    returncode: int, stderr: str, raw: str, budget: Budget, input_tokens: int
) -> ModelResult:
    if _is_rate_limited(returncode, stderr, {}):
        return _rate_limited_result({}, stderr)
    tokens = input_tokens + _estimate_tokens(raw)
    budget.charge(tokens)
    return ModelResult(None, tokens, None, "failed", "invalid client JSON")


def extract_batch(
    prompts: Sequence[str],
    *,
    budget: Budget,
    model_id: str | None = None,
    runner: Runner = subprocess.run,
) -> BatchResult:
    """Extract prompts in order; return current and remaining work when stopped."""
    results: list[ModelResult] = []
    for prompt in prompts:
        result = extract_with_claude(
            prompt, budget=budget, model_id=model_id, runner=runner
        )
        if result.status in {"budget_exhausted", "rate_limited"}:
            return BatchResult(results, result.status, result.error)
        results.append(result)
        if result.status == "failed":
            return BatchResult(results, "failed", result.error)
    return BatchResult(results, None)


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively redact strings before storing or rendering model data."""
    return {redact(str(key)): redact_value(item) for key, item in value.items()}


def redact_ledger_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Redact textual ledger fields before append-only persistence."""
    safe = dict(row)
    for key in ("reason", "last_error", "excerpt"):
        if isinstance(safe.get(key), str):
            safe[key] = redact(safe[key])[:MAX_ERROR_CHARS]
    return safe


def mark_review_row(
    store_dir: str | Path,
    row: Mapping[str, Any],
    *,
    latest_by_key: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Append a review ledger row after redacting every persisted text field."""
    from .ledger import mark

    return mark(
        store_dir,
        redact_ledger_row(row),
        latest_by_key=latest_by_key,
    )


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def _estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def _nonnegative_int(value: Any) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def _is_rate_limited(returncode: int, stderr: str, response: Any) -> bool:
    if isinstance(response, dict):
        subtype = str(response.get("subtype", "")).lower()
        if subtype in {"rate_limit", "rate_limited", "usage_limit", "overloaded"}:
            return True
        api_error = response.get("error")
        if isinstance(api_error, dict):
            status = api_error.get("status", api_error.get("status_code"))
            if status in {429, "429", "rate_limit_error"}:
                return True
    return returncode == 429 or (
        returncode != 0
        and any(
            marker in stderr.lower()
            for marker in ("429", "rate limit", "usage limit", "overloaded")
        )
    )
