"""Ranked "what to change" for a file below its reference line.

Only measures that move the score under the calibration (split/size and
one-call wrappers) get a ``predicted_score``: a facts-level edit of the record,
scored with the same scorer. Nesting, vague names and every non-Python language
are advisory: they name a change and claim no score. This module reads no
accept/reject labels and never edits the scoring path.
"""

from __future__ import annotations

from typing import Any

from .calibration import Calibration
from .fixedpoint.arithmetic import MICRO
from .guidance import ACTIONS, short_name
from .reference import score_of_facts
from .scoring import score_scope

ADVISORY_NOTE = "advisory, does not change score"
SCORED_LANGUAGES = frozenset({"python"})
DEFAULT_TOP = 5
ADVISORY_CAP = 3
MIN_WRAPPER_GAIN = 0.5


def _halve(function: dict[str, Any], key: str) -> tuple[int, int]:
    value = function.get(key) or 0
    return value - value // 2, value // 2


def split_in_two(record: dict[str, Any], function_id: str) -> dict[str, Any]:
    """The record with one function replaced by two halves (tokens, cognitive)."""
    functions: list[dict[str, Any]] = []
    for function in record["functions"]:
        if function["id"] != function_id:
            functions.append(function)
            continue
        tokens, cognitive = _halve(function, "tokens"), _halve(function, "cognitive")
        functions.extend(
            {
                **function,
                "id": f"{function['id']}~{part}",
                "tokens": tokens[part],
                "cognitive": cognitive[part],
                "delegates": False,
            }
            for part in (0, 1)
        )
    return {**record, "functions": functions}


def drop_function(record: dict[str, Any], function_id: str) -> dict[str, Any]:
    """The record without one function, its tokens removed from the file."""
    kept = [f for f in record["functions"] if f["id"] != function_id]
    removed = sum(f.get("tokens") or 0 for f in record["functions"] if f not in kept)
    return {
        **record,
        "functions": kept,
        "tokens": (record.get("tokens") or 0) - removed,
    }


def _limits(calibration: Calibration, language: str) -> dict[str, int]:
    parameters = calibration.languages[language].parameters
    return {
        key: parameters[key] // MICRO
        for key in ("Phi", "c0", "n0", "nm0")
        if key in parameters
    }


def _wrapper_limit(calibration: Calibration, language: str, count: int) -> int:
    share = calibration.languages[language].parameters.get("dg0", MICRO // 3)
    return share * count // MICRO


def _split_measure(function: dict[str, Any], limits: dict[str, int]) -> str | None:
    if (function.get("tokens") or 0) > limits.get("Phi", 96):
        return "long_side"
    if (function.get("cognitive") or 0) > limits.get("c0", 10):
        return "cognitive"
    return None


def _advisory_measure(function: dict[str, Any], limits: dict[str, int]) -> str | None:
    if (function.get("max_nesting") or 0) > limits.get("n0", 1):
        return "nesting"
    if (function.get("vague_names") or 0) > limits.get("nm0", 0):
        return "vague_names"
    return None


def _change(
    measure: str,
    function: dict[str, Any],
    limits: dict[str, int],
    wrappers: tuple[int, int],
) -> str:
    name = short_name(str(function["id"]))
    tokens = function.get("tokens") or 0
    values = {
        "long_side": (tokens, limits.get("Phi", 96)),
        "cognitive": (function.get("cognitive") or 0, limits.get("c0", 10)),
        "delegation": wrappers,
        "nesting": (function.get("max_nesting") or 0, limits.get("n0", 1)),
        "vague_names": (function.get("vague_names") or 0, limits.get("nm0", 0)),
    }
    now, limit = values[measure]
    return ACTIONS[measure].format(f=name, now=now, t=limit, tokens=tokens, cx="")


def _points(micro: float) -> float:
    return round(micro / MICRO, 1)


def _entry(
    function: dict[str, Any],
    measure: str,
    *,
    contribution: float,
    distance: float,
    change: str,
    predicted: float | None,
) -> dict[str, Any]:
    advisory = predicted is None
    return {
        "file": function["path"],
        "line": function.get("line"),
        "function": short_name(str(function["id"])),
        "measure": measure,
        "advisory": advisory,
        "contribution_points": contribution,
        "distance_to_line": distance,
        "change": f"{change} ({ADVISORY_NOTE})" if advisory else change,
        "predicted_score": predicted,
    }


def _shares(scored: Any) -> tuple[dict[str, float], float]:
    """Per-function points lost and the file's delegation points lost."""
    file = scored.files[0]
    lost = file.points_lost / MICRO
    debt = file.debt or 1
    per_function = {f.id: lost * f.debt / debt for f in file.functions}
    delegation = lost * file.components.get("delegation", 0) / debt
    return per_function, delegation


def _wrapper_ids(record: dict[str, Any]) -> list[str]:
    return [
        f["id"]
        for f in record["functions"]
        if f.get("delegates") and not f.get("exempt_role")
    ]


def _candidates(record: dict[str, Any], limits: dict[str, int]) -> list[tuple]:
    """(function, measure, edit) for each function; edit None means advisory."""
    scored = record.get("language") in SCORED_LANGUAGES
    wrappers = set(_wrapper_ids(record)) if scored else set()
    found = []
    for function in record["functions"]:
        function = {**function, "path": record["path"]}  # noqa: PLW2901
        split = _split_measure(function, limits)
        if split:
            found.append((function, split, split_in_two if scored else None))
        if function["id"] in wrappers and not function.get("hook"):
            found.append((function, "delegation", drop_function))
        advisory = _advisory_measure(function, limits)
        if advisory:
            found.append((function, advisory, None))
    return found


class _Context:
    """What every entry of one file shares: its record, score and distance."""

    def __init__(
        self, record: dict[str, Any], calibration: Calibration, line: float
    ) -> None:
        self.record = record
        self.calibration = calibration
        self.score = score_of_facts(record, calibration) or 0.0
        self.distance = round(line - self.score, 1)
        language = record["language"]
        self.limits = _limits(calibration, language)
        self.shares, self.delegation = _shares(score_scope([record], calibration))
        self.wrapper_count = len(_wrapper_ids(record))
        self.wrappers = (
            self.wrapper_count,
            _wrapper_limit(calibration, language, self.wrapper_count),
        )

    def contribution(self, function: dict[str, Any], measure: str) -> float:
        if measure == "delegation":
            return round(self.delegation / max(1, self.wrapper_count), 1)
        return round(self.shares.get(function["id"], 0.0), 1)


def _advisory_entry(
    ctx: _Context, function: dict[str, Any], measure: str
) -> dict[str, Any]:
    return _entry(
        function,
        measure,
        contribution=ctx.contribution(function, measure),
        distance=ctx.distance,
        change=_change(measure, function, ctx.limits, ctx.wrappers),
        predicted=None,
    )


def _scored_entry(
    ctx: _Context, function: dict[str, Any], measure: str, edit: Any
) -> tuple[float, dict[str, Any]] | None:
    """(gain, entry) of a facts-level edit, or None when it does not help."""
    after = score_of_facts(edit(ctx.record, function["id"]), ctx.calibration)
    gain = 0.0 if after is None else round(after - ctx.score, 1)
    if gain < (MIN_WRAPPER_GAIN if measure == "delegation" else 0.1):
        return None
    entry = _entry(
        function,
        measure,
        contribution=ctx.contribution(function, measure),
        distance=ctx.distance,
        change=_change(measure, function, ctx.limits, ctx.wrappers),
        predicted=after,
    )
    return gain, entry


def _rank(
    ranked: list[tuple[float, dict[str, Any]]], advisory: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Scored entries by gain, then at most ``ADVISORY_CAP`` advisory ones by the
    points they lose; ranks from 1."""
    ranked.sort(key=lambda item: (-item[0], item[1]["line"] or 0, item[1]["function"]))
    advisory.sort(
        key=lambda e: (
            -e["contribution_points"],
            e["line"] or 0,
            e["function"],
            e["measure"],
        )
    )
    entries = [entry for _, entry in ranked] + advisory[:ADVISORY_CAP]
    return [{"rank": i, **entry} for i, entry in enumerate(entries, 1)]


def fixes(
    record: dict[str, Any],
    calibration: Calibration,
    line: float,
    *,
    top: int = DEFAULT_TOP,
) -> list[dict[str, Any]]:
    """The ranked fix list of one file's facts; empty when it is at or above ``line``.

    Scored entries come first, ordered by predicted gain, then at most
    ``ADVISORY_CAP`` advisory entries, largest loss first. At most ``top`` in all.
    """
    score = score_of_facts(record, calibration)
    if (
        score is None
        or score >= line
        or record.get("language") not in calibration.languages
    ):
        return []
    ctx = _Context(record, calibration, line)
    ranked: list[tuple[float, dict[str, Any]]] = []
    advisory: list[dict[str, Any]] = []
    for function, measure, edit in _candidates(record, ctx.limits):
        if edit is None:
            advisory.append(_advisory_entry(ctx, function, measure))
            continue
        scored = _scored_entry(ctx, function, measure, edit)
        if scored is not None:
            ranked.append(scored)
    return _rank(ranked, advisory)[:top]


def no_scored_fix_note(
    record: dict[str, Any], calibration: Calibration, fix_list: list[dict[str, Any]]
) -> str:
    """Why a flagged file has no score-predicting fix; empty when it has one."""
    if any(not fix["advisory"] for fix in fix_list):
        return ""
    if fix_list:
        return (
            "no fix with a predicted score for this language or loss; the listed "
            "changes are advisory only"
        )
    components = score_scope([record], calibration).files[0].components
    cause = max(components, key=lambda name: components[name], default=None)
    if cause is None or not components[cause]:
        return "no single function is over its limit, so no function fix is listed"
    return (
        f"no single function fix is listed: the largest loss is {cause}, which "
        "is spread over the file (see the categories of `varde score --file`)"
    )
