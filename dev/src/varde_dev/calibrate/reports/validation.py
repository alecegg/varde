"""Recompute a per-language validation record from stored labels and scores."""

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from varde_dev.calibrate.reports import (
    accuracy,
    cluster_bootstrap_interval,
    cohens_kappa,
    wilson_interval,
)
from varde_dev.calibrate.reports.config import (
    DEFAULT_CATEGORY_B,
    DEFAULT_HELD_OUT_SPLITS,
    DEFAULT_SKIPPED_CHOICES,
    THRESHOLDS,
)


def read_scores(path: str | Path) -> list[dict[str, object]]:
    rows = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise TypeError(f"score row {line_number} must be a JSON object")
        rows.append(row)
    return rows


def validation_record(
    *,
    dataset: Mapping[str, object],
    language: str,
    rater_id: str,
    scores: Sequence[dict[str, object]],
    previous: Mapping[str, object] | None = None,
    options: Mapping[str, object] | None = None,
) -> dict[str, object]:
    settings: dict[str, object] = {
        **THRESHOLDS,
        "category_b": DEFAULT_CATEGORY_B,
        "held_out_splits": DEFAULT_HELD_OUT_SPLITS,
        "skipped_choices": DEFAULT_SKIPPED_CHOICES,
    }
    settings.update(options or {})
    labels, item_by_id, manifest = _dataset_records(dataset)
    selected = _selected_labels(labels, item_by_id, language, rater_id, settings)
    pairs, category_units, held_out_units = _score_pairs(
        selected, item_by_id, scores, settings
    )
    if not pairs:
        raise ValueError(
            f"no matching non-tie labels and scores for {language}/{rater_id}"
        )
    statistics = _agreement_statistics(pairs, selected, item_by_id, scores, settings)
    timestamps = [
        str(label.get("timestamp", ""))[:10]
        for rows in selected.values()
        for label in rows
        if label.get("timestamp")
    ]
    return _validation_record_data(
        {
            "labels": labels,
            "manifest": manifest,
            "scores": scores,
            "selected": selected,
            "pairs": pairs,
            "category_units": category_units,
            "held_out_units": held_out_units,
            "statistics": statistics,
            "previous": previous,
            "language": language,
            "rater_id": rater_id,
            "settings": settings,
            "date": max(timestamps, default=""),
        }
    )


def _dataset_records(dataset: Mapping[str, object]):
    labels, items, manifest = dataset["labels"], dataset["items"], dataset["manifest"]
    if (
        not isinstance(labels, Sequence)
        or not isinstance(items, Sequence)
        or not isinstance(manifest, Mapping)
    ):
        raise TypeError("dataset reader returned invalid report data")
    return labels, {str(item["id"]): item for item in items}, manifest


def _selected_labels(labels, items, language, rater_id, settings):
    digests = {
        str(item.get("content_sha256")): item_id
        for item_id, item in items.items()
        if item.get("content_sha256")
    }
    selected: dict[str, list[dict[str, object]]] = defaultdict(list)
    for label in labels:
        if (
            label.get("rater_id") != rater_id
            or str(label.get("choice", "")).lower() in settings["skipped_choices"]
        ):
            continue
        item_id = _label_a_item(label, digests)
        if items.get(item_id, {}).get("language") == language:
            selected[str(label["unit_id"])].append(label)
    return selected


def _score_pairs(selected, items, scores, settings):
    digests = {
        str(item.get("content_sha256")): item_id
        for item_id, item in items.items()
        if item.get("content_sha256")
    }
    latest = {
        unit_id: max(rows, key=lambda row: str(row.get("timestamp", "")))
        for unit_id, rows in selected.items()
    }
    scores_by_unit = {str(row["unit_id"]): row for row in scores}
    pairs, category_units, held_out_units = [], set(), set()
    for unit_id, label in sorted(latest.items()):
        row = scores_by_unit.get(unit_id)
        if label.get("choice") == "tie" or row is None:
            continue
        item_a, item_b = _label_a_item(label, digests), _label_b_item(label, digests)
        scores_by_item = row.get("scores")
        if (
            not isinstance(scores_by_item, Mapping)
            or item_a not in scores_by_item
            or item_b not in scores_by_item
        ):
            raise ValueError(
                f"score row {unit_id} must map both labelled item ids to scores"
            )
        score_a, score_b = scores_by_item[item_a], scores_by_item[item_b]
        if not isinstance(score_a, (int, float)) or not isinstance(
            score_b, (int, float)
        ):
            raise TypeError(f"scores for {unit_id} must be numeric")
        actual = item_a if label["choice"] == "A" else item_b
        predicted = (
            item_a if score_a > score_b else item_b if score_b > score_a else "tie"
        )
        pairs.append((actual, predicted, unit_id, str(row.get("task_id", unit_id))))
        metadata = items[item_a].get("metadata", {})
        if (
            isinstance(metadata, Mapping)
            and metadata.get("category") == settings["category_b"]
        ):
            category_units.add(unit_id)
        if row.get("split") in settings["held_out_splits"]:
            held_out_units.add(unit_id)
    return pairs, category_units, held_out_units


def _agreement_statistics(pairs, selected, items, scores, settings):
    actual, predicted = [row[0] for row in pairs], [row[1] for row in pairs]
    successes = sum(a == b for a, b in zip(actual, predicted, strict=True))
    wilson = wilson_interval(successes, len(pairs))
    clusters: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for a, p, _, task in pairs:
        clusters[task].append((a, p))
    bootstrap = cluster_bootstrap_interval(
        [clusters[key] for key in sorted(clusters)],
        accuracy,
        seed=int(settings["bootstrap_seed"]),
        replicates=int(settings["bootstrap_replicates"]),
    )
    repeated = _repeat_results(selected, items)
    return {
        "accuracy": accuracy(actual, predicted),
        "kappa": cohens_kappa(actual, predicted),
        "wilson": wilson,
        "bootstrap": bootstrap,
        "category_accuracy": _category_accuracy(
            pairs, items, selected, scores, settings
        ),
        "consistency": sum(repeated) / len(repeated) if repeated else None,
        "repeat_count": len(repeated),
    }


def _repeat_results(selected, items):
    digests = {
        str(item.get("content_sha256")): item_id
        for item_id, item in items.items()
        if item.get("content_sha256")
    }
    results = []
    for rows in selected.values():
        if len(rows) > 1:
            choices = {
                _chosen_item(
                    row, _label_a_item(row, digests), _label_b_item(row, digests)
                )
                for row in rows
            }
            results.append(len(choices) == 1)
    return results


def _category_accuracy(pairs, items, selected, scores, settings):
    # Metadata is symmetric for a valid pair, so the label's first shown item
    # identifies it.
    digests = {
        str(item.get("content_sha256")): item_id
        for item_id, item in items.items()
        if item.get("content_sha256")
    }
    latest = {
        unit_id: max(rows, key=lambda row: str(row.get("timestamp", "")))
        for unit_id, rows in selected.items()
    }
    ids = set()
    for unit_id, label in latest.items():
        metadata = items[_label_a_item(label, digests)].get("metadata", {})
        if (
            isinstance(metadata, Mapping)
            and metadata.get("category") == settings["category_b"]
        ):
            ids.add(unit_id)
    subset = [row for row in pairs if row[2] in ids]
    return (
        accuracy([row[0] for row in subset], [row[1] for row in subset])
        if subset
        else None
    )


def _validation_record_data(data: dict[str, Any]):
    labels = data["labels"]
    manifest = data["manifest"]
    scores = data["scores"]
    selected = data["selected"]
    pairs = data["pairs"]
    category_units = data["category_units"]
    held_out_units = data["held_out_units"]
    stats = data["statistics"]
    previous = data["previous"]
    language = data["language"]
    rater_id = data["rater_id"]
    settings = data["settings"]
    if not scores:
        raise ValueError("scores file is empty")
    ids = {str(row.get("calibration_id", "")) for row in scores}
    if len(ids) != 1 or "" in ids:
        raise ValueError("scores must contain exactly one nonempty calibration_id")
    calibration_id = next(iter(ids))
    prior = previous.get("validated_against", {}) if previous else {}
    prior_id = prior.get("calibration") if isinstance(prior, Mapping) else None
    category_count = sum(row[2] in category_units for row in pairs)
    held_out_count = len(held_out_units & {row[2] for row in pairs})
    tests = {
        "accuracy": stats["accuracy"] >= settings["accuracy"],
        "wilson_lb": stats["wilson"][0] >= settings["wilson_lower_bound"],
        "bootstrap_lb": stats["bootstrap"][0] >= settings["bootstrap_lower_bound"],
        "kappa": stats["kappa"] >= settings["kappa"],
        "category_b_accuracy": stats["category_accuracy"] is not None
        and stats["category_accuracy"] >= settings["category_b_accuracy"],
        "self_consistency": stats["consistency"] is not None
        and stats["repeat_count"] >= settings["minimum_repeated_units"]
        and stats["consistency"] >= settings["self_consistency"],
    }
    validated = (
        all(tests.values())
        and len(pairs) >= settings["minimum_units"]
        and category_count >= settings["minimum_category_b_units"]
        and held_out_count >= settings["minimum_held_out_units"]
    )
    return {
        "language": language,
        "state": "human-validated" if validated else "report-only",
        "rater_id": rater_id,
        "rater_kind": next(
            (
                row.get("rater_kind")
                for row in labels
                if row.get("rater_id") == rater_id
            ),
            "human",
        ),
        "n_units": len(selected),
        "n_non_tie": len(pairs),
        "n_category_b": category_count,
        "n_held_out": held_out_count,
        "date": data["date"],
        "validated_against": {
            "formula": str(scores[0].get("formula", "unknown")),
            "calibration": calibration_id,
            "profile_sha256": str(scores[0].get("profile_sha256", "none")),
        },
        "thresholds": tests,
        "agreement": {
            "accuracy": stats["accuracy"],
            "kappa": stats["kappa"],
            "wilson_95": list(stats["wilson"]),
            "cluster_bootstrap_95": list(stats["bootstrap"]),
            "category_b_accuracy": stats["category_accuracy"],
            "self_consistency": stats["consistency"],
        },
        "stale": prior_id is not None and prior_id != calibration_id,
        "label_batches": [
            str(batch.get("sha256")) for batch in manifest.get("label_batches", [])
        ],
    }


def _label_a_item(label: Mapping[str, object], digests: Mapping[str, str]) -> str:
    order = label.get("order_shown")
    if isinstance(order, list) and len(order) == 2:
        return str(order[0])
    if label.get("a_item_id") is not None:
        return str(label["a_item_id"])
    return digests.get(str(label.get("a_sha256", "")), "")


def _label_b_item(label: Mapping[str, object], digests: Mapping[str, str]) -> str:
    order = label.get("order_shown")
    if isinstance(order, list) and len(order) == 2:
        return str(order[1])
    if label.get("b_item_id") is not None:
        return str(label["b_item_id"])
    return digests.get(str(label.get("b_sha256", "")), "")


def _chosen_item(label: Mapping[str, object], item_a: str, item_b: str) -> str:
    return (
        item_a
        if label.get("choice") == "A"
        else item_b
        if label.get("choice") == "B"
        else "tie"
    )
