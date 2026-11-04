"""Deterministic session logic kept independent of terminal input and output."""

import random
from collections.abc import Mapping, Sequence
from typing import Any


def build_schedule(
    units: Sequence[Mapping[str, Any]],
    *,
    seed: int,
    settings: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return randomized presentation entries; control positions are 1-based."""
    options = settings or {}
    _validate_schedule_options(options)
    by_id = {unit["id"]: unit for unit in units}
    if len(by_id) != len(units):
        raise ValueError("unit ids must be unique")
    control_positions, control_unit_ids = _control_positions(options, len(units), by_id)
    options = {**options, "control_unit_ids": control_unit_ids}
    rng = random.Random(seed)  # noqa: S311 - Seeded randomness keeps calibration sessions reproducible.
    distractor_unit_ids, designated_distractors = _distractor_ids(options, rng, by_id)
    excluded = (
        set(control_unit_ids)
        | set(designated_distractors)
        | set(options.get("excluded_unit_ids", ()))
    )
    ordered = [unit for unit in units if unit["id"] not in excluded]
    rng.shuffle(ordered)
    ordered = _interleave_tasks(ordered, rng)
    entries = [_entry(unit, "standard", rng) for unit in ordered]
    _insert_reshews(entries, by_id, options.get("reshow_interval"), rng)
    _insert_distractors(entries, distractor_unit_ids, by_id, rng)
    _insert_controls(entries, control_positions, by_id, rng)
    return _finish_schedule(entries, options, rng)


def _validate_schedule_options(options: Mapping[str, Any]) -> None:
    if not 0 <= options.get("reason_rate", 0.2) <= 1:
        raise ValueError("reason_rate must be between 0 and 1")
    for name in ("reshow_interval", "break_every", "control_every"):
        value = options.get(name)
        if value is not None and value < 1:
            raise ValueError(f"{name} must be positive")
    if options.get("distractor_count", 0) < 0:
        raise ValueError("distractor_count must be non-negative")


def _control_positions(
    options: Mapping[str, Any], unit_count: int, by_id: Mapping[str, Mapping[str, Any]]
) -> tuple[dict[int, str], list[str]]:
    positions = dict(options.get("control_positions", {}))
    control_ids = list(options.get("control_unit_ids", positions.values()))
    interval = options.get("control_every")
    if interval:
        if not control_ids:
            raise ValueError("control_every requires designated control units")
        excluded_count = len(
            set(control_ids)
            | set(options.get("available_distractor_ids", ()))
            | set(options.get("excluded_unit_ids", ()))
        )
        standard_count = max(0, unit_count - excluded_count)
        control_index = 0
        for position in range(interval, standard_count + 1, interval):
            if position not in positions:
                positions[position] = control_ids[control_index % len(control_ids)]
                control_index += 1
    known_controls = set(control_ids)
    if any(
        position < 1 or unit_id not in by_id or unit_id not in known_controls
        for position, unit_id in positions.items()
    ):
        raise ValueError(
            "control positions require a designated control unit and positive position"
        )
    return positions, control_ids


def _distractor_ids(
    options: Mapping[str, Any], rng: random.Random, by_id: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    selected = list(options.get("distractor_unit_ids", ()))
    designated = list(options.get("available_distractor_ids", selected))
    control_ids = set(options.get("control_unit_ids", ()))
    if control_ids & set(selected):
        raise ValueError("a unit cannot be both a control and a distractor")
    available = [unit_id for unit_id in designated if unit_id not in control_ids]
    count = options.get("distractor_count", 0)
    if count > len(available):
        raise ValueError("distractor count exceeds designated distractor units")
    if count:
        selected.extend(rng.sample(available, count))
    if any(unit_id not in by_id or unit_id not in designated for unit_id in selected):
        raise ValueError("unknown or undesignated distractor unit")
    if len(set(selected)) != len(selected):
        raise ValueError("duplicate distractor unit")
    return selected, designated


def _insert_reshews(
    entries: list[dict[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
    interval: int | None,
    rng: random.Random,
) -> None:
    if interval is None:
        return
    original = list(entries)
    repeat_indexes = range(0, len(original) - interval, interval)
    for original_index in reversed(list(repeat_indexes)):
        entry = original[original_index]
        entries.insert(
            original_index + interval + 1,
            _entry(by_id[entry["unit_id"]], "reshow", rng),
        )


def _insert_distractors(
    entries: list[dict[str, Any]],
    unit_ids: Sequence[str],
    by_id: Mapping[str, Mapping[str, Any]],
    rng: random.Random,
) -> None:
    for unit_id in unit_ids:
        entries.insert(
            rng.randrange(len(entries) + 1), _entry(by_id[unit_id], "distractor", rng)
        )


def _insert_controls(
    entries: list[dict[str, Any]],
    positions: Mapping[int, str],
    by_id: Mapping[str, Mapping[str, Any]],
    rng: random.Random,
) -> None:
    for position, unit_id in sorted(positions.items()):
        entries.insert(
            min(position - 1, len(entries)), _entry(by_id[unit_id], "control", rng)
        )


def _finish_schedule(
    entries: list[dict[str, Any]], options: Mapping[str, Any], rng: random.Random
) -> list[dict[str, Any]]:
    reason_rate = options.get("reason_rate", 0.2)
    break_every = options.get("break_every")
    for index, entry in enumerate(entries):
        entry["schedule_id"] = f"entry-{index + 1:06d}"
        entry["reason_prompt"] = rng.random() < reason_rate
        entry["break_after"] = bool(break_every and (index + 1) % break_every == 0)
    return entries


def _interleave_tasks(
    units: Sequence[Mapping[str, Any]], rng: random.Random
) -> list[Mapping[str, Any]]:
    remaining = list(units)
    ordered: list[Mapping[str, Any]] = []
    while remaining:
        previous_task = ordered[-1].get("task_id") if ordered else None
        candidates = [
            index
            for index, unit in enumerate(remaining)
            if unit.get("task_id") != previous_task
        ]
        index = rng.choice(candidates) if candidates else 0
        ordered.append(remaining.pop(index))
    return ordered


def _entry(unit: Mapping[str, Any], role: str, rng: random.Random) -> dict[str, Any]:
    order = list(unit["item_ids"])
    rng.shuffle(order)
    return {
        "unit_id": unit["id"],
        "kind": unit["kind"],
        "item_order": order,
        "task_id": unit.get("task_id"),
        "role": role,
    }


def assemble_display(
    unit: Mapping[str, Any],
    task: Mapping[str, Any],
    items: Mapping[str, Mapping[str, Any]],
    schedule_entry: Mapping[str, Any],
) -> dict[str, Any]:
    """Build blind display data containing task text and code only."""
    order = schedule_entry["item_order"]
    texts = {item_id: items[item_id]["text"] for item_id in order}
    pairs = [(order[0], order[1])]
    if unit["kind"] == "triple":
        pairs = [(order[0], order[1]), (order[0], order[2]), (order[1], order[2])]
    return {
        "task_description": task["description"],
        "unit_id": unit["id"],
        "pairs": [{"a": texts[left], "b": texts[right]} for left, right in pairs],
    }


def display_unit(
    unit: Mapping[str, Any],
    task: Mapping[str, Any],
    items: Mapping[str, Mapping[str, Any]],
    schedule_entry: Mapping[str, Any],
) -> str:
    """Return task instructions and anonymous A/B code blocks for a unit."""
    display = assemble_display(unit, task, items, schedule_entry)
    blocks = [display["task_description"]]
    for number, pair in enumerate(display["pairs"], start=1):
        if len(display["pairs"]) > 1:
            blocks.append(f"Pair {number} of {len(display['pairs'])}")
        blocks.extend(("A:\n" + pair["a"], "B:\n" + pair["b"]))
    return "\n\n".join(blocks)


def prompt_choice(
    prompt: str = "Choose [a/b/t]: ", *, input_fn: Any | None = None
) -> str:
    """Read one A, B, or tie choice, retrying until a valid key is entered."""
    choices = {"a": "A", "b": "B", "t": "tie"}
    reader = input_fn or input
    while True:
        choice = reader(prompt).strip().lower()
        if choice in choices:
            return choices[choice]
        print("Enter a, b, or t.")


def make_session(
    session_id: str, rater_id: str, *, seed: int, schedule: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "id": session_id,
        "rater_id": rater_id,
        "seed": seed,
        "schedule": [dict(entry) for entry in schedule],
        "cursor": 0,
        "labels": [],
        "paused": False,
    }


def record_label(
    schedule_entry: Mapping[str, Any],
    *,
    choice: str,
    confidence: str,
    duration_ms: int,
    reason: str | None = None,
) -> dict[str, Any]:
    if choice not in {"A", "B", "tie", "skip"}:
        raise ValueError("choice must be A, B, tie, or skip")
    if confidence not in {"high", "medium", "low"}:
        raise ValueError("confidence must be high, medium, or low")
    if duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")
    record = {
        "record_id": f"label-{schedule_entry['schedule_id']}",
        "unit_id": schedule_entry["unit_id"],
        "choice": choice,
        "confidence": confidence,
        "duration_ms": duration_ms,
    }
    if reason:
        record["reason"] = reason.strip().splitlines()[0]
    return record


def resume_session(
    session: Mapping[str, Any],
    *,
    cursor: int,
    label: Mapping[str, Any] | None,
    paused: bool,
) -> dict[str, Any]:
    updated = dict(session)
    schedule = session["schedule"]
    if not 0 <= cursor <= len(schedule):
        raise ValueError("cursor is outside the schedule")
    labels = list(session.get("labels", []))
    if label is not None:
        record_id = label["record_id"]
        labels = [record for record in labels if record["record_id"] != record_id]
        labels.append(dict(label))
    updated.update(cursor=cursor, labels=labels, paused=paused)
    return updated


def amend_record(
    old_record: Mapping[str, Any], *, choice: str, confidence: str, duration_ms: int
) -> dict[str, Any]:
    amended = dict(old_record)
    amended.update(
        record_id=(
            f"{old_record['record_id']}-amend-"
            f"{len(old_record.get('amendments', [])) + 1}"
        ),
        amends=old_record["record_id"],
        choice=choice,
        confidence=confidence,
        duration_ms=duration_ms,
    )
    return amended
