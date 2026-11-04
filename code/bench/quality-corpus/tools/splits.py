"""Stable cross-language task splits; 10% of tasks are reserved for regression."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

LOCK = Path(__file__).resolve().parent / "splits.lock"


def assignments(tasks: list[str]) -> dict[str, str]:
    result = {}
    for task in sorted(set(tasks)):
        bucket = (
            int.from_bytes(
                hashlib.blake2b(task.encode(), digest_size=8).digest(), "big"
            )
            % 10
        )
        result[task] = (
            "regression" if bucket == 0 else "dev" if bucket < 5 else "test-restricted"
        )
    return result


def lock_hash(mapping: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def assign(task_id: str, tasks: list[str] | None = None) -> str:
    if tasks is not None:
        return assignments(tasks)[task_id]
    if not LOCK.exists():
        raise FileNotFoundError(
            f"split lock is missing: {LOCK}; run splits.py --write-lock <tasks.json>"
        )
    payload = json.loads(LOCK.read_text())
    mapping = payload["assignments"]
    if payload.get("sha256") != lock_hash(mapping):
        raise ValueError(f"split lock hash mismatch: {LOCK}")
    return mapping[task_id]


def write_lock(tasks: list[str], path: Path = LOCK) -> str:
    mapping = assignments(tasks)
    digest = lock_hash(mapping)
    path.write_text(
        json.dumps({"assignments": mapping, "sha256": digest}, indent=2) + "\n"
    )
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write-lock", type=Path, nargs="?", const=LOCK)
    group.add_argument("--check-lock", type=Path, nargs="?", const=LOCK)
    parser.add_argument("--tasks", type=Path)
    args = parser.parse_args()
    try:
        if args.write_lock:
            if args.tasks is None:
                parser.error("--tasks <json-file> is required with --write-lock")
            tasks = json.loads(args.tasks.read_text())
            print(write_lock(tasks, args.write_lock))
            return 0
        payload = json.loads(args.check_lock.read_text())
        if payload.get("sha256") != lock_hash(payload["assignments"]):
            print("split lock hash mismatch")
            return 1
        print("split lock: ok")
    except FileNotFoundError as error:
        print(error)
        return 2
    else:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
