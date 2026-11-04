"""Load rankings from store labels or the panel runner's public run files."""

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from varde_dev.calibrate.panel.logic import opaque_pair_id


def labels_for_rater(
    dataset: Path,
    rater_id: str,
    labels: Sequence[Mapping[str, object]],
    units: Sequence[Mapping[str, object]],
    items: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Resolve a rater from stored labels or panel `runs/` artifacts."""
    stored = [dict(label) for label in labels if label.get("rater_id") == rater_id]
    if rater_id == "panel" and stored:
        return stored
    if rater_id == "panel":
        panel_labels = _stored_panel_labels(labels, units, items)
        if panel_labels:
            return panel_labels
    unit_by_opaque = {
        opaque_pair_id(str(unit["id"])): unit
        for unit in units
        if isinstance(unit.get("item_ids"), list)
    }
    run_rows = _read_run_rows(dataset / "runs")
    matches = [
        row
        for row in run_rows
        if row.get("lens") == rater_id or row.get("run_id") == rater_id
    ]
    if rater_id == "panel":
        matches = run_rows
    if not matches:
        if stored:
            return stored
        raise ValueError(f"no labels found for rater {rater_id!r}")
    latest: dict[tuple[str, str], tuple[str, dict[str, object]]] = {}
    for row in matches:
        unit = unit_by_opaque.get(str(row.get("pair_id", "")))
        if unit is None:
            continue
        run_id = str(row["run_id"])
        manifest_path = dataset / "runs" / f"{run_id}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        verdicts = manifest.get("verdicts", {})
        verdict = (
            verdicts.get(str(row["pair_id"])) if isinstance(verdicts, Mapping) else None
        )
        if not isinstance(verdict, Mapping):
            continue
        choice = str(verdict.get("choice", "inconsistent"))
        unit_id = str(unit["id"])
        lens = str(row.get("lens", ""))
        key = (unit_id, lens)
        label = {
            "unit_id": unit_id,
            "rater_id": "panel" if rater_id == "panel" else rater_id,
            "choice": choice,
            "timestamp": str(row.get("timestamp", "")),
            "a_item_id": str(unit["item_ids"][0]),
            "b_item_id": str(unit["item_ids"][1]),
        }
        if rater_id == "panel":
            label["lens"] = lens
        current = latest.get(key)
        if current is None or label["timestamp"] > current[0]:
            latest[key] = (str(label["timestamp"]), label)
    if rater_id == "panel":
        by_unit: dict[str, list[dict[str, object]]] = defaultdict(list)
        for (unit_id, _), (_, label) in latest.items():
            by_unit[unit_id].append(label)
        panel_labels = []
        for unit_id, votes in sorted(by_unit.items()):
            votes.sort(key=lambda row: str(row["lens"]))
            panel_labels.append(
                {
                    "unit_id": unit_id,
                    "rater_id": "panel",
                    "timestamp": max(str(row["timestamp"]) for row in votes),
                    "votes": [_canonical_vote(row["choice"]) for row in votes],
                }
            )
        if panel_labels:
            return panel_labels
    resolved = [label for _, label in latest.values()]
    if not resolved:
        if stored:
            return stored
        raise ValueError(f"no labels found for rater {rater_id!r}")
    return [*stored, *resolved]


def _stored_panel_labels(labels, units, items):
    item_map = {str(item["id"]): item for item in items}
    unit_map = {str(unit["id"]): unit for unit in units}
    latest: dict[tuple[str, str], Mapping[str, object]] = {}
    for label in labels:
        if (
            label.get("rater_kind") != "llm-lens"
            and label.get("label_source") != "panel"
        ):
            continue
        if str(label.get("choice", "")).lower() in {"skip", "skipped", "abstain"}:
            continue
        unit_id = str(label.get("unit_id", ""))
        lens_id = str(label.get("lens", label.get("rater_id", "")))
        key = (unit_id, lens_id)
        current = latest.get(key)
        current_key = (
            (
                str(current.get("timestamp", "")),
                json.dumps(current, sort_keys=True, separators=(",", ":")),
            )
            if current is not None
            else None
        )
        label_key = (
            str(label.get("timestamp", "")),
            json.dumps(label, sort_keys=True, separators=(",", ":")),
        )
        if current_key is None or label_key > current_key:
            latest[key] = label
    by_unit: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (unit_id, lens_id), label in latest.items():
        unit = unit_map.get(unit_id)
        refs = unit.get("item_ids") if unit else None
        if not isinstance(refs, list) or len(refs) != 2:
            continue
        pair = (str(refs[0]), str(refs[1]))
        choice = str(label.get("choice", ""))
        if choice == "tie":
            vote = "tie"
        elif choice in {"A", "B"}:
            order = label.get("order_shown")
            chosen = None
            if isinstance(order, list) and len(order) == 2:
                chosen = str(order[0] if choice == "A" else order[1])
            else:
                key_name = "a_item_id" if choice == "A" else "b_item_id"
                chosen = str(label[key_name]) if label.get(key_name) else None
                if chosen is None:
                    digest_field = "a_sha256" if choice == "A" else "b_sha256"
                    digest = label.get(digest_field)
                    chosen = next(
                        (
                            item_id
                            for item_id, item in sorted(item_map.items())
                            if item.get("content_sha256") == digest
                        ),
                        None,
                    )
            vote = "A" if chosen == pair[0] else "B" if chosen == pair[1] else "split"
        else:
            vote = "split"
        by_unit[unit_id].append((lens_id, vote))
    return [
        {
            "unit_id": unit_id,
            "rater_id": "panel",
            "votes": [vote for _, vote in sorted(votes)],
            "timestamp": max(
                str(row.get("timestamp", ""))
                for row in labels
                if str(row.get("unit_id", "")) == unit_id
            ),
        }
        for unit_id, votes in sorted(by_unit.items())
    ]


def _canonical_vote(choice: object) -> str:
    return {"inconsistent": "split"}.get(str(choice), str(choice))


def _read_run_rows(run_directory: Path) -> list[dict[str, Any]]:
    if not run_directory.is_dir():
        return []
    rows = []
    for path in sorted(run_directory.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                if isinstance(record, dict):
                    rows.append(record)
    return rows
