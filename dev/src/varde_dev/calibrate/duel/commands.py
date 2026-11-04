"""Adaptive, resumable human head-to-head rating sessions."""

import argparse
import hashlib
import json
import random
import re
import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_dev.calibrate.labeller.session import display_unit
from varde_dev.calibrate.rating import fit, next_pairs, stop_state
from varde_dev.calibrate.reports.dataset import read_dataset_files
from varde_dev.calibrate.store import append_label_batch, import_dataset

_SESSION_NAME = re.compile(r"[A-Za-z0-9._-]+")


class _InputEnded(Exception):
    """The terminal ended before the current answer was complete."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m varde_dev.calibrate duel")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--session")
    parser.add_argument("--group")
    parser.add_argument("--max-matches", type=int)
    parser.add_argument("--seed", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"calibrate duel: {error}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    data = read_dataset_files(args.dataset)
    items = {item["id"]: item for item in data["items"]}
    # Tasks live in tasks.jsonl; the public dataset reader returns core rating data.
    task_records = _read_jsonl(args.dataset / "tasks.jsonl")
    tasks = {task["id"]: task for task in task_records}
    memberships: dict[str, set[str]] = {}
    for item in data["items"]:
        memberships.setdefault(item["pair_group_id"], set()).add(item["id"])
    pair_members: dict[str, set[str]] = {}
    for unit in data["units"]:
        if unit["kind"] != "pair":
            continue
        pair_members.setdefault(unit["pair_group_id"], set()).update(unit["item_ids"])
    all_groups = {group: sorted(ids) for group, ids in memberships.items()}
    session_name = args.session or datetime.now(UTC).strftime("duel-%Y%m%d-%H%M%S")
    if not _SESSION_NAME.fullmatch(session_name):
        raise ValueError(
            "session name may contain only letters, numbers, dot, underscore, and "
            "hyphen"
        )
    session_path = args.dataset / "sessions" / f"duel-{session_name}.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    if session_path.exists():
        session = json.loads(session_path.read_text(encoding="utf-8"))
        groups = session["groups"]
        if args.group and args.group not in groups:
            raise ValueError(
                "session group selection differs; resume with the original session"
            )
        print(
            f"Resuming duel session {session_name} after {session['cursor']} matches."
        )
    else:
        groups = _select_groups(all_groups, pair_members, args.group)
        if not groups:
            return 0
        seed = (
            args.seed
            if args.seed is not None
            else int.from_bytes(uuid.uuid4().bytes[:4], "big")
        )
        session = {
            "id": str(uuid.uuid4()),
            "seed": seed,
            "cursor": 0,
            "side_assignments": 0,
            "pending": None,
            "labels": [],
            "skipped": [],
            "paused": False,
            "groups": groups,
        }
        _write_session(session_path, session)
    print(
        f"Resume with: python -m varde_dev.calibrate duel {args.dataset} "
        f"--session {session_name}"
    )
    context = {
        "args": args,
        "session": session,
        "session_path": session_path,
        "data": data,
        "items": items,
        "tasks": tasks,
        "groups": groups,
    }
    return _loop(context)


def _select_groups(all_groups, pair_members, requested):
    if requested is not None and requested not in all_groups:
        raise ValueError(f"unknown pair_group_id: {requested}")
    selected = {requested: all_groups[requested]} if requested else all_groups
    groups = {}
    for group, ids in sorted(selected.items()):
        if len(ids) < 2:
            print(f"Skipping group {group}: fewer than 2 items.")
            if requested == group:
                print(f"No duel available for group {group}: fewer than 2 items.")
            continue
        eligible = sorted(pair_members.get(group, set()))
        if len(eligible) < 2:
            if requested == group:
                print(f"No duel available for group {group}: it has no pair units.")
            continue
        groups[group] = eligible
    if not groups and requested is None:
        print("No groups with at least two pair items to compare.")
    return groups


def _loop(context: dict[str, Any]) -> int:
    session = context["session"]
    data = context["data"]
    units = {unit["id"]: unit for unit in data["units"]}
    pair_units = {
        (unit["pair_group_id"], *sorted(unit["item_ids"])): unit
        for unit in units.values()
        if unit["kind"] == "pair"
    }
    played = [
        (record["group"], record["x"], record["y"], record["outcome"])
        for record in session["labels"]
    ]
    rng = random.Random(session["seed"])  # noqa: S311 - Seeded randomness reproduces persisted duel assignments.
    for _ in range(session.get("side_assignments", 0)):
        rng.random()
    context.update(units=units, pair_units=pair_units, played=played, rng=rng)
    return _session_loop(context)


def _session_loop(context: dict[str, Any]) -> int:
    session = context["session"]
    session_path = context["session_path"]
    args = context["args"]
    groups = context["groups"]
    played = context["played"]
    ratings = fit(
        played, [(group, item) for group, ids in groups.items() for item in ids]
    )
    state = stop_state(ratings, played, groups, {"confidence": 0.9})
    while True:
        if state["stop"]:
            print(f"Stopped: {state['reason']}.")
            session["paused"] = False
            _write_session(session_path, session)
            return 0
        if args.max_matches is not None and session["cursor"] >= args.max_matches:
            _pause(session, session_path)
            return 0
        action, match = _next_match(context, ratings)
        if action == "pause":
            return 0
        if action == "skip":
            continue
        if action == "invalid":
            continue
        outcome = _save_match(context, match)
        played.append((match["group"], match["x"], match["y"], outcome))
        estimates = fit(
            played, [(g, item) for g, ids in groups.items() for item in ids]
        )
        current_state = stop_state(estimates, played, groups, {"confidence": 0.9})
        if session["cursor"] % 3 == 0 or current_state["stop"]:
            _progress(session["cursor"], current_state)
        ratings = estimates
        state = current_state


def _next_match(
    context: dict[str, Any], ratings: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    session = context["session"]
    session_path = context["session_path"]
    groups = context["groups"]
    played = context["played"]
    pending = session.get("pending")
    if pending is not None and pending["cursor"] == session["cursor"]:
        group, x, y = pending["group"], pending["x"], pending["y"]
        order = pending["order"]
    else:
        selection_history = [
            *played,
            *((*skip, "tie") for skip in session["skipped"]),
        ]
        pairs = next_pairs(ratings, selection_history, groups)
        if not pairs:
            print("No eligible pairs remain.")
            _write_session(session_path, session)
            return "pause", {}
        group, x, y = pairs[0]
        order = [x, y]
        if context["rng"].random() < 0.5:
            order.reverse()
        session["side_assignments"] = session.get("side_assignments", 0) + 1
        session["pending"] = {
            "cursor": session["cursor"],
            "group": group,
            "x": x,
            "y": y,
            "order": order,
        }
        _write_session(session_path, session)
    canonical = (group, x, y)
    unit = _pair_unit(context, canonical)
    entry = {"schedule_id": f"duel-{session['cursor'] + 1:06d}", "item_order": order}
    print(f"\nMatch {session['cursor'] + 1}")
    print(
        display_unit(unit, context["tasks"][unit["task_id"]], context["items"], entry)
    )
    try:
        raw = input("Choose [a/b/t], [s] skip, [p] pause: ").strip().lower()
        if raw == "p":
            _pause(session, session_path)
            return "pause", {}
        if raw == "s":
            session["skipped"].append(list(canonical))
            session["pending"] = None
            _write_session(session_path, session)
            return "skip", {}
        if raw not in {"a", "b", "t"}:
            print("Enter a, b, t, s, or p.")
            return "invalid", {}
        choice = {"a": "A", "b": "B", "t": "tie"}[raw]
        reason = input("Reason (optional, one line): ").strip().splitlines()[0:1]
    except EOFError, KeyboardInterrupt:
        _pause(session, session_path)
        print("Input ended; no label was saved for this match.")
        return "pause", {}
    return "submit", {
        "group": group,
        "x": x,
        "y": y,
        "unit": unit,
        "order": order,
        "choice": choice,
        "reason": reason,
    }


def _pair_unit(context, canonical):
    pair_units = context["pair_units"]
    unit = pair_units.get(canonical)
    if unit is not None:
        return unit
    group, x, y = canonical
    items = context["items"]
    unit_id = "duel-" + hashlib.sha256("\0".join(canonical).encode()).hexdigest()[:20]
    return {
        "id": unit_id,
        "kind": "pair",
        "item_ids": [x, y],
        "pair_group_id": group,
        "task_id": items[x]["task_id"],
        "split": items[x]["split"],
    }


def _persist_pair_unit(context, canonical):
    pair_units = context["pair_units"]
    unit = pair_units.get(canonical)
    if unit is None:
        unit = _pair_unit(context, canonical)
        import_dataset(context["args"].dataset, items=[], units=[unit], tasks=[])
        context["units"][unit["id"]] = unit
        context["data"]["units"].append(unit)
        pair_units[canonical] = unit
    return unit


def _save_match(context, match):
    group, x, y, _, order, choice, reason = (
        match[key] for key in ("group", "x", "y", "unit", "order", "choice", "reason")
    )
    unit = _persist_pair_unit(context, (group, x, y))
    outcome = (
        "tie"
        if choice == "tie"
        else ("x" if (choice == "A") == (order[0] == x) else "y")
    )
    session = context["session"]
    label = {
        "record_id": f"duel-{session['id']}-{session['cursor'] + 1:06d}",
        "unit_id": unit["id"],
        "a_item_id": order[0],
        "b_item_id": order[1],
        "order_shown": order,
        "choice": choice,
        "confidence": "high",
        "session_id": session["id"],
        "rater_id": "human",
        "rater_kind": "human",
        "label_source": "duel",
        "timestamp": datetime.now(UTC).isoformat(),
        "duration_ms": 0,
    }
    if reason:
        label["reason"] = reason[0]
    append_label_batch(context["args"].dataset, [label])
    session["labels"].append({"group": group, "x": x, "y": y, "outcome": outcome})
    session["cursor"] += 1
    session["paused"] = False
    session["pending"] = None
    _write_session(context["session_path"], session)
    return outcome


def _progress(count, state) -> None:
    uncertainty = {
        f"Group {index}": list(intervals.values())
        for index, intervals in enumerate(state["groups"].values(), start=1)
    }
    confidence = {
        f"Group {index}": status
        for index, status in enumerate(state["groups_status"].values(), start=1)
    }
    print(
        f"Progress: {count} matches | uncertainty by group: {uncertainty} "
        f"| ranking confidence: {confidence}"
    )
    if state["stop"]:
        print(f"Early-stop reason: {state['reason']}")


def _pause(session, path) -> None:
    session["paused"] = True
    _write_session(path, session)
    print(f"Paused. Resume with --session {path.stem.removeprefix('duel-')}.")


def _write_session(path: Path, session: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(session, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[1:] if line.strip()]
