"""Terminal loop for human calibration labels."""

import argparse
import json
import re
import shlex
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from varde_dev.calibrate.labeller.session import (
    amend_record,
    build_schedule,
    display_unit,
    make_session,
    prompt_choice,
    record_label,
    resume_session,
)
from varde_dev.calibrate.store import append_label_batch, import_dataset

_SESSION_NAME = re.compile(r"[A-Za-z0-9._-]+")


class _InputEnded(Exception):
    """Raised when the terminal closes before the current unit is complete."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m varde_dev.calibrate label")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--session")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--control-every", type=int)
    parser.add_argument("--control-positions", type=_parse_control_positions)
    parser.add_argument("--reshow-interval", type=int)
    parser.add_argument("--distractors", type=int, default=0)
    parser.add_argument("--reason-rate", type=float, default=0.2)
    parser.add_argument("--break-every", type=int, default=20)
    parser.add_argument("--max-minutes", "--hard-stop-minutes", type=float, default=120)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"calibrate label: {error}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    dataset = args.dataset
    units = _read_jsonl(dataset / "units.jsonl")
    items = {item["id"]: item for item in _read_jsonl(dataset / "items.jsonl")}
    tasks = {task["id"]: task for task in _read_jsonl(dataset / "tasks.jsonl")}
    derived_units = _ensure_triple_pair_units(dataset, units)
    units = _read_jsonl(dataset / "units.jsonl")
    role_config = _read_role_config(dataset, units)
    session_name = args.session or datetime.now(UTC).strftime("human-%Y%m%d-%H%M%S")
    if not _SESSION_NAME.fullmatch(session_name):
        raise ValueError(
            "session name may contain only letters, numbers, dot, underscore, and "
            "hyphen"
        )
    session_path = dataset / "sessions" / f"{session_name}.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    if session_path.exists():
        session = json.loads(session_path.read_text(encoding="utf-8"))
        session_id = session["id"]
        if session.get("completed_at") and session["cursor"] >= len(
            session["schedule"]
        ):
            print(f"Session {session_name} is already complete.")
            return 0
        print(f"Resuming session {session_name} at unit {session['cursor'] + 1}.")
    else:
        seed = (
            args.seed
            if args.seed is not None
            else int.from_bytes(uuid.uuid4().bytes[:4], "big")
        )
        settings = {
            **role_config,
            "control_every": args.control_every,
            "control_positions": args.control_positions or {},
            "control_unit_ids": sorted(
                set(role_config["control_unit_ids"])
                | set((args.control_positions or {}).values())
            ),
            "reshow_interval": args.reshow_interval,
            "distractor_count": args.distractors,
            "reason_rate": args.reason_rate,
            "break_every": args.break_every,
            "excluded_unit_ids": set(derived_units),
        }
        schedule = build_schedule(units, seed=seed, settings=settings)
        session_id = str(uuid.uuid4())
        session = make_session(session_id, "human", seed=seed, schedule=schedule)
        session.update(
            started_at=datetime.now(UTC).isoformat(),
            active_seconds=0.0,
            records=[],
            skipped=[],
            skipped_history=[],
        )
        _write_session(session_path, session)
    print(_resume_message(session_path, session_name=session_name))
    context = {
        "dataset": dataset,
        "session_path": session_path,
        "session_id": session_id,
        "unit_by_id": {unit["id"]: unit for unit in units},
        "items": items,
        "tasks": tasks,
        "records": list(session.get("records", [])),
        "derived_pair_by_items": _derived_pair_map(units),
        "active_seconds_before": session.get("active_seconds", 0.0),
        "active_started": time.monotonic(),
    }
    options = {
        "hard_stop_seconds": args.max_minutes * 60,
    }
    return _label_loop(context, session, options)


def _label_loop(
    context: dict[str, Any],
    session: dict[str, Any],
    options: Mapping[str, Any],
) -> int:
    schedule = session["schedule"]
    while True:
        if session["cursor"] >= len(schedule):
            if session.get("skipped"):
                _queue_skipped(context, session)
                continue
            break
        cursor = session["cursor"]
        action = _process_entry(context, session, cursor)
        if action == "pause":
            return 0
        if action == "submit":
            entry = schedule[cursor]
            if entry.get("break_after"):
                print("Suggested break: take a short pause before continuing.")
        if (
            action == "submit"
            and not session.get("hard_stop_warned", False)
            and session.get("active_seconds", 0) >= options["hard_stop_seconds"]
        ):
            print("Hard-stop time reached. Consider pausing and resuming later.")
            session["hard_stop_warned"] = True
            _save_session(context, session)
    session["records"] = context["records"]
    session["paused"] = False
    session["completed_at"] = datetime.now(UTC).isoformat()
    _save_session(context, session)
    print(f"Session complete: {len(context['records'])} labels saved.")
    return 0


def _process_entry(
    context: dict[str, Any], session: dict[str, Any], cursor: int
) -> str:
    entry = session["schedule"][cursor]
    unit = context["unit_by_id"][entry["unit_id"]]
    if unit["kind"] == "single":
        print(
            f"Skipping unsupported single unit {unit['id']}; ordinal rating is not "
            "available."
        )
        _skip(context, session, entry, cursor, retry=False)
        return "skip"
    print(f"\nProgress: {cursor + 1}/{len(session['schedule'])}")
    print(
        display_unit(unit, context["tasks"][unit["task_id"]], context["items"], entry)
    )
    unit_started = time.monotonic()
    key = _read_action()
    if key == "p":
        _pause(context, session, cursor)
        return "pause"
    if key == "s":
        _skip(context, session, entry, cursor)
        return "skip"
    if key == "amend":
        _amend(context["dataset"], context["records"], context["session_id"])
        _save_session(context, session)
        return "amend"
    choice = {"a": "A", "b": "B", "t": "tie"}.get(key)
    if choice is None:
        print("Enter a, b, t, s, p, or amend.")
        return "invalid"
    try:
        if unit["kind"] == "triple":
            _submit_triple(context, session, entry, choice, unit_started)
        elif unit["kind"] == "pair":
            _submit(context, session, entry, choice, unit_started)
        else:
            raise ValueError(f"unsupported unit kind: {unit['kind']}")
    except _InputEnded:
        _pause(context, session, cursor)
        return "pause"
    return "submit"


def _read_action() -> str:
    try:
        return (
            input(
                "[a/b/t] choose, [s] skip, [p] pause, [amend] change an earlier label: "
            )
            .strip()
            .lower()
        )
    except (
        EOFError,
        KeyboardInterrupt,
    ):
        return "p"


def _pause(context: dict[str, Any], session: dict[str, Any], cursor: int) -> None:
    session.update(resume_session(session, cursor=cursor, label=None, paused=True))
    _save_session(context, session)
    print(
        "Paused. "
        + _resume_message(
            context["session_path"], session_name=context["session_path"].stem
        )
    )


def _skip(
    context: dict[str, Any],
    session: dict[str, Any],
    entry: Mapping[str, Any],
    cursor: int,
    *,
    retry: bool = True,
) -> None:
    session.update(resume_session(session, cursor=cursor + 1, label=None, paused=False))
    session["skipped_history"] = [
        *session.get("skipped_history", []),
        entry["schedule_id"],
    ]
    if retry and not entry.get("retry"):
        session["skipped"] = [*session.get("skipped", []), dict(entry)]
    _save_session(context, session)


def _submit(
    context: dict[str, Any],
    session: dict[str, Any],
    entry: Mapping[str, Any],
    choice: str,
    unit_started: float,
) -> None:
    unit = context["unit_by_id"][entry["unit_id"]]
    cursor = session["cursor"]
    confidence = _prompt_confidence()
    reason = _prompt_reason(entry)
    duration_ms = round((time.monotonic() - unit_started) * 1000)
    label = record_label(
        entry,
        choice=choice,
        confidence=confidence,
        duration_ms=duration_ms,
        reason=reason,
    )
    label.update(_store_fields(unit, entry, label, context["session_id"]))
    append_label_batch(context["dataset"], [label])
    context["records"].append(label)
    session.update(
        resume_session(session, cursor=cursor + 1, label=label, paused=False)
    )
    _save_session(context, session)


def _save_session(context: dict[str, Any], session: dict[str, Any]) -> None:
    session["records"] = context["records"]
    session["active_seconds"] = context["active_seconds_before"] + (
        time.monotonic() - context["active_started"]
    )
    _write_session(context["session_path"], session)


def _queue_skipped(context: dict[str, Any], session: dict[str, Any]) -> None:
    skipped = list(session["skipped"])
    session["skipped"] = []
    for entry in skipped:
        retry = dict(entry)
        retry["schedule_id"] = f"{entry['schedule_id']}-retry"
        retry["role"] = "retry"
        retry["retry"] = True
        session["schedule"].append(retry)
    _save_session(context, session)


def _submit_triple(
    context: dict[str, Any],
    session: dict[str, Any],
    entry: Mapping[str, Any],
    first_choice: str,
    first_started: float,
) -> None:
    cursor = session["cursor"]
    order = entry["item_order"]
    pair_orders = [(order[0], order[1]), (order[0], order[2]), (order[1], order[2])]
    pair_labels: list[dict[str, Any]] = []
    for index, (a_id, b_id) in enumerate(pair_orders):
        print(f"Pair {index + 1} of 3: choose [a/b/t].")
        if index == 0:
            choice = first_choice
            started = first_started
        else:
            started = time.monotonic()
            choice = _read_triple_choice()
        mini_entry = {
            "schedule_id": f"{entry['schedule_id']}-pair-{index + 1}",
            "unit_id": context["derived_pair_by_items"][tuple(sorted((a_id, b_id)))],
            "item_order": [a_id, b_id],
            "reason_prompt": entry["reason_prompt"],
        }
        confidence = _prompt_confidence()
        reason = _prompt_reason(mini_entry)
        duration_ms = round((time.monotonic() - started) * 1000)
        label = record_label(
            mini_entry,
            choice=choice,
            confidence=confidence,
            duration_ms=duration_ms,
            reason=reason,
        )
        pair_unit = context["unit_by_id"][mini_entry["unit_id"]]
        label.update(_store_fields(pair_unit, mini_entry, label, context["session_id"]))
        pair_labels.append(label)
    append_label_batch(context["dataset"], pair_labels)
    context["records"].extend(pair_labels)
    session.update(
        resume_session(session, cursor=cursor + 1, label=pair_labels[-1], paused=False)
    )
    _save_session(context, session)


def _read_triple_choice() -> str:
    options = {"a": "A", "b": "B", "t": "tie"}
    while True:
        key = _read_required("Choose [a/b/t]: ").strip().lower()
        if key in options:
            return options[key]
        if key in {"p", "s"}:
            raise _InputEnded
        print("Enter a, b, or t to finish this triple.")


def _store_fields(
    unit: Mapping[str, Any],
    entry: Mapping[str, Any],
    label: Mapping[str, Any],
    session_id: str,
) -> dict[str, Any]:
    a_id, b_id = entry["item_order"]
    timestamp = datetime.now(UTC).isoformat()
    fields: dict[str, Any] = {
        "record_id": f"label-{entry['schedule_id']}",
        "unit_id": unit["id"],
        "a_item_id": a_id,
        "b_item_id": b_id,
        "order_shown": [a_id, b_id],
        "choice": label["choice"],
        "confidence": label["confidence"],
        "session_id": session_id,
        "rater_id": "human",
        "rater_kind": "human",
        "label_source": "label",
        "timestamp": timestamp,
        "duration_ms": label["duration_ms"],
    }
    if label.get("reason"):
        fields["reason"] = label["reason"]
    return fields


def _prompt_confidence() -> str:
    values = {"h": "high", "m": "medium", "l": "low"}
    while True:
        answer = _read_required("Confidence [h/m/l]: ").strip().lower()
        if answer in values:
            return values[answer]
        print("Enter h, m, or l.")


def _prompt_reason(entry: Mapping[str, Any]) -> str | None:
    prompt = (
        "Reason prompt (optional): [r/Enter] "
        if entry["reason_prompt"]
        else "Add reason? [r/Enter]: "
    )
    answer = _read_required(prompt).strip()
    if answer.lower() == "r":
        answer = _read_required("Reason: ").strip()
    return answer.splitlines()[0] if answer else None


def _amend(dataset: Path, records: list[dict[str, Any]], session_id: str) -> None:
    for index, record in enumerate(records, start=1):
        print(
            f"{index}: {record['unit_id']} {record['choice']} ({record['record_id']})"
        )
    try:
        selected = int(_read_required("Label number to amend: ")) - 1
    except (
        ValueError,
        _InputEnded,
    ):
        print("No label amended.")
        return
    if not 0 <= selected < len(records):
        print("No label amended.")
        return
    old = records[selected]
    started = time.monotonic()
    try:
        choice = prompt_choice(input_fn=_read_required)
        confidence = _prompt_confidence()
        reason = _prompt_reason({"reason_prompt": False})
    except _InputEnded:
        print("Amendment cancelled; no record was appended.")
        return
    amended = amend_record(
        old,
        choice=choice,
        confidence=confidence,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    amended.update(
        session_id=session_id,
        timestamp=datetime.now(UTC).isoformat(),
        label_source="label",
        rater_id="human",
        rater_kind="human",
    )
    if reason:
        amended["reason"] = reason
    else:
        amended.pop("reason", None)
    append_label_batch(dataset, [amended])
    records.append(amended)


def _read_required(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt) as error:
        raise _InputEnded from error


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"missing schema header: {path.name}")
    header = json.loads(lines[0])
    if header.get("record_type") not in {"items", "units", "tasks"}:
        raise ValueError(f"unexpected record type in {path.name}")
    return [json.loads(line) for line in lines[1:] if line]


def _parse_control_positions(value: str) -> dict[int, str]:
    positions: dict[int, str] = {}
    for entry in value.split(","):
        try:
            position_text, unit_id = entry.split("=", maxsplit=1)
            position = int(position_text)
        except ValueError as error:
            raise argparse.ArgumentTypeError(
                "control positions use POSITION=UNIT_ID pairs separated by commas"
            ) from error
        if position < 1 or not unit_id:
            raise argparse.ArgumentTypeError(
                "control positions must be positive and have a unit id"
            )
        if position in positions:
            raise argparse.ArgumentTypeError(f"duplicate control position: {position}")
        positions[position] = unit_id
    return positions


def _read_role_config(
    dataset: Path, units: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    config_path = dataset / "label-config.json"
    config = (
        json.loads(config_path.read_text(encoding="utf-8"))
        if config_path.exists()
        else {}
    )
    controls = set(config.get("controls", []))
    distractors = set(config.get("distractors", []))
    for unit in units:
        metadata = unit.get("metadata", {})
        role = metadata.get("label_role", metadata.get("role"))
        if metadata.get("control") or role == "control":
            controls.add(unit["id"])
        if metadata.get("distractor") or role == "distractor":
            distractors.add(unit["id"])
    if controls & distractors:
        raise ValueError("a unit cannot be designated as both control and distractor")
    return {
        "control_unit_ids": sorted(controls),
        "available_distractor_ids": sorted(distractors),
    }


def _ensure_triple_pair_units(
    dataset: Path, units: Sequence[Mapping[str, Any]]
) -> set[str]:
    existing_ids = {unit["id"] for unit in units}
    derived_ids: set[str] = set()
    additions: list[dict[str, Any]] = []
    for unit in units:
        if unit["kind"] != "triple":
            continue
        for index, pair in enumerate(combinations(unit["item_ids"], 2), start=1):
            pair_id = f"{unit['id']}::pair-{index}"
            derived_ids.add(pair_id)
            if pair_id in existing_ids:
                continue
            additions.append(
                {
                    "id": pair_id,
                    "kind": "pair",
                    "item_ids": list(pair),
                    "pair_group_id": unit["pair_group_id"],
                    "task_id": unit["task_id"],
                    "split": unit["split"],
                    "metadata": {"labeller_parent_triple": unit["id"]},
                }
            )
    if additions:
        import_dataset(dataset, items=[], units=additions, tasks=[])
    return derived_ids


def _derived_pair_map(units: Sequence[Mapping[str, Any]]) -> dict[tuple[str, ...], str]:
    return {
        tuple(sorted(unit["item_ids"])): unit["id"]
        for unit in units
        if unit.get("metadata", {}).get("labeller_parent_triple")
    }


def _write_session(path: Path, session: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(session, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _resume_message(path: Path, *, session_name: str) -> str:
    dataset = shlex.quote(str(path.parent.parent))
    name = shlex.quote(session_name)
    return (
        f"Resume with: python -m varde_dev.calibrate label {dataset} --session {name}"
    )
