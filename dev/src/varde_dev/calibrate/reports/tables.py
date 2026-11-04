"""Build canonical per-pair panel and agreement tables."""

from collections.abc import Mapping, Sequence

from varde_dev.calibrate.reports import (
    accuracy,
    cluster_bootstrap_interval,
    cohens_kappa,
    panel_label,
    wilson_interval,
)
from varde_dev.calibrate.reports.config import (
    DEFAULT_BOOTSTRAP_REPLICATES,
    DEFAULT_BOOTSTRAP_SEED,
    DEFAULT_OVER_SPLIT_CATEGORY,
)


def build_report(
    labels: Sequence[Mapping[str, object]],
    units: Sequence[Mapping[str, object]],
    items: Sequence[Mapping[str, object]],
    *,
    by: Sequence[str] = ("category", "language", "lens"),
    over_split_category: str = DEFAULT_OVER_SPLIT_CATEGORY,
    bootstrap: Mapping[str, int] = {
        "seed": DEFAULT_BOOTSTRAP_SEED,
        "replicates": DEFAULT_BOOTSTRAP_REPLICATES,
    },
) -> dict[str, object]:
    dimensions = ("category", "language", "lens", "variant")
    if set(by) - set(dimensions):
        raise ValueError("--by accepts category, language, lens, and variant")
    item_by_id = {str(item["id"]): item for item in items}
    pairs = _pairs(units, item_by_id)
    position_bias: dict[str, dict[str, int]] = {}
    for label in labels:
        unit_id = str(label.get("unit_id", ""))
        pair = pairs.get(unit_id)
        if pair is None or _skip(label):
            continue
        choice = str(label.get("verdict", label.get("choice", "split")))
        item_id = _chosen_item_id(label, item_by_id)
        vote = _vote(label, item_id, pair["item_ids"])
        lens = str(label.get("lens", label.get("rater_id", "unknown")))
        pair["votes"].append(
            {
                "lens": lens,
                "rater_id": str(label.get("rater_id", "unknown")),
                "vote": vote,
                "item_id": item_id,
                "choice": choice,
                "confidence": label.get("confidence"),
                "timestamp": str(label.get("timestamp", "")),
            }
        )
        counts = position_bias.setdefault(lens, {"A": 0, "B": 0, "tie": 0, "split": 0})
        counts[choice] = counts.get(choice, 0) + 1

    panel_rows = []
    for pair in pairs.values():
        votes = _latest_votes(pair["votes"])
        pair["votes"] = votes
        cls, pref, dissent, margin = (
            "unlabelled",
            None,
            [],
            {"A": 0, "B": 0, "difference": 0},
        )
        if len(votes) == 3:
            verdicts = [str(row["vote"]) for row in votes]
            cls, dissent_values = panel_label(verdicts)
            a_count, b_count = verdicts.count("A"), verdicts.count("B")
            pref = (
                "A"
                if cls in {"unanimous", "decisive"} and a_count > b_count
                else "B"
                if cls in {"unanimous", "decisive"}
                else None
            )
            dissent_lenses = _dissent_lenses(votes, dissent_values)
            dissent = [
                {
                    "lens": row["lens"],
                    "vote": row["vote"],
                    "confidence": row["confidence"],
                }
                for row in votes
                if row["lens"] in dissent_lenses
            ]
            margin = {"A": a_count, "B": b_count, "difference": abs(a_count - b_count)}
        pair.update({"panel_class": cls, "panel_preference": pref, "dissent": dissent})
        panel_rows.append(
            {
                key: pair[key]
                for key in ("unit_id", "task_id", "language", "category", "variant")
            }
            | {
                "panel_class": cls,
                "labelled": cls in {"unanimous", "decisive"},
                "panel_preference": pref,
                "vote_vector": [
                    {
                        "lens": row["lens"],
                        "vote": row["vote"],
                        "item_id": row["item_id"],
                    }
                    for row in votes
                ],
                "dissent": dissent,
                "margin": margin,
            }
        )

    comparisons = _pairwise(pairs)
    return {
        "agreement": {
            "n_pairs": len(comparisons),
            "accuracy": accuracy(
                [a for a, _ in comparisons], [b for _, b in comparisons]
            )
            if comparisons
            else None,
            "kappa": cohens_kappa(
                [a for a, _ in comparisons], [b for _, b in comparisons]
            )
            if comparisons
            else None,
        },
        "position_bias": position_bias,
        "accuracy_tables": {
            dimension: _accuracy_table(
                pairs,
                dimension,
                over_split_category,
                bootstrap["seed"],
                bootstrap["replicates"],
            )
            for dimension in ("lens", "category", "variant")
        },
        "labelled_rates": _labelled_rates(
            pairs,
            tuple(dict.fromkeys((*by, "category", "language", "variant"))),
        ),
        "dissent_rates": _dissent_rates(pairs, over_split_category),
        "panel": panel_rows,
        "over_split": [
            {
                "unit_id": pair["unit_id"],
                "variant": pair["variant"],
                "lens": vote["lens"],
                "vote": vote["vote"],
                "item_id": vote["item_id"],
            }
            for pair in pairs.values()
            if pair["category"] == over_split_category
            for vote in pair["votes"]
        ],
        "disagreement": [
            row
            for row in panel_rows
            if len({vote["vote"] for vote in row["vote_vector"]}) > 1
        ],
    }


def _pairs(
    units: Sequence[Mapping[str, object]], items: Mapping[str, Mapping[str, object]]
) -> dict[str, dict[str, object]]:
    result = {}
    for unit in units:
        refs = unit.get("item_ids", [])
        if (
            not isinstance(refs, list)
            or len(refs) != 2
            or any(str(ref) not in items for ref in refs)
        ):
            continue
        first = items[str(refs[0])]
        metadata = first.get("metadata", {})
        metadata = metadata if isinstance(metadata, Mapping) else {}
        unit_id = str(unit["id"])
        result[unit_id] = {
            "unit_id": unit_id,
            "task_id": str(unit.get("task_id", unit.get("pair_group_id", unit_id))),
            "item_ids": refs,
            "language": str(first.get("language", "unknown")),
            "category": str(metadata.get("category", "unknown")),
            "variant": str(metadata.get("variant", "unknown")),
            "votes": [],
            "panel_class": "unlabelled",
            "panel_preference": None,
            "dissent": [],
        }
    return result


def _chosen_item_id(
    label: Mapping[str, object], items: Mapping[str, Mapping[str, object]]
) -> str | None:
    choice = str(label.get("verdict", label.get("choice", "split")))
    if choice in {"tie", "split", "inconsistent", "skip", "skipped", "abstain"}:
        return None
    order = label.get("order_shown")
    if isinstance(order, list) and len(order) == 2:
        return str(order[0] if choice == "A" else order[1])
    key = "a_item_id" if choice == "A" else "b_item_id"
    if label.get(key) is not None:
        return str(label[key])
    digest = str(label.get("a_sha256" if choice == "A" else "b_sha256", ""))
    return next(
        (
            item_id
            for item_id, item in items.items()
            if item.get("content_sha256") == digest
        ),
        None,
    )


def _vote(
    label: Mapping[str, object], item_id: str | None, item_ids: Sequence[object]
) -> str:
    choice = str(label.get("verdict", label.get("choice", "split")))
    if choice == "tie":
        return "tie"
    if choice in {"split", "inconsistent"} or item_id is None:
        return "split"
    if item_id == str(item_ids[0]):
        return "A"
    if item_id == str(item_ids[1]):
        return "B"
    raise ValueError(f"label item does not belong to pair {label.get('unit_id')}")


def _skip(label: Mapping[str, object]) -> bool:
    return str(label.get("choice", "")).lower() in {"skip", "skipped", "abstain"}


def _latest_votes(votes: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    latest = {}
    for vote in sorted(
        votes, key=lambda row: (str(row["timestamp"]), str(row["rater_id"]))
    ):
        latest[str(vote["lens"])] = vote
    return [latest[key] for key in sorted(latest)]


def _dissent_lenses(
    votes: Sequence[Mapping[str, object]], values: Sequence[str]
) -> set[str]:
    remaining = list(values)
    lenses = set()
    for row in votes:
        if row["vote"] in remaining:
            lenses.add(str(row["lens"]))
            remaining.remove(str(row["vote"]))
    return lenses


def _pairwise(pairs: Mapping[str, Mapping[str, object]]) -> list[tuple[str, str]]:
    results = []
    for pair in pairs.values():
        votes = pair["votes"]
        for index, left in enumerate(votes):
            results.extend(
                (str(left["vote"]), str(right["vote"]))
                for right in votes[index + 1 :]
                if left["vote"] in {"A", "B"} and right["vote"] in {"A", "B"}
            )
    return results


def _accuracy_table(
    pairs: Mapping[str, Mapping[str, object]],
    dimension: str,
    over_split_category: str,
    seed: int,
    replicates: int,
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    for pair in pairs.values():
        if pair["panel_class"] not in {"unanimous", "decisive"} or (
            dimension == "variant" and pair["category"] != over_split_category
        ):
            continue
        for vote in pair["votes"]:
            if vote["vote"] in {"A", "B"}:
                group_value = (
                    str(vote["lens"]) if dimension == "lens" else str(pair[dimension])
                )
                grouped.setdefault((str(vote["lens"]), group_value), []).append(
                    (
                        str(pair["panel_preference"]),
                        str(vote["vote"]),
                        str(pair["task_id"]),
                    )
                )
    rows = []
    for (lens, value), observations in sorted(grouped.items()):
        actual = [row[0] for row in observations]
        predicted = [row[1] for row in observations]
        successes = sum(a == p for a, p in zip(actual, predicted, strict=True))
        task_clusters: dict[str, list[tuple[str, str]]] = {}
        for a, p, task in observations:
            task_clusters.setdefault(task, []).append((a, p))
        bootstrap = cluster_bootstrap_interval(
            [task_clusters[key] for key in sorted(task_clusters)],
            accuracy,
            seed=seed,
            replicates=replicates,
        )
        row: dict[str, object] = {
            "lens": lens,
            dimension: value,
            "n": len(observations),
            "accuracy": successes / len(observations),
            "wilson_95": list(wilson_interval(successes, len(observations))),
            "cluster_bootstrap_95": list(bootstrap),
            "clusters": len(task_clusters),
        }
        rows.append(row)
    return rows


def _labelled_rates(
    pairs: Mapping[str, Mapping[str, object]], dimensions: Sequence[str]
) -> dict[str, list[dict[str, object]]]:
    result = {}
    for dimension in dimensions:
        if dimension == "lens":
            lens_groups: dict[str, list[Mapping[str, object]]] = {}
            for pair in pairs.values():
                for vote in pair["votes"]:
                    lens_groups.setdefault(str(vote["lens"]), []).append(pair)
            result[dimension] = [
                {
                    "lens": key,
                    "total": len(rows),
                    "labelled": sum(
                        row["panel_class"] in {"unanimous", "decisive"} for row in rows
                    ),
                    "labelled_rate": sum(
                        row["panel_class"] in {"unanimous", "decisive"} for row in rows
                    )
                    / len(rows),
                    "panel_tie": sum(row["panel_class"] == "panel-tie" for row in rows),
                    "contested": sum(row["panel_class"] == "contested" for row in rows),
                    "unlabelled": sum(
                        row["panel_class"] == "unlabelled" for row in rows
                    ),
                }
                for key, rows in sorted(lens_groups.items())
            ]
            continue
        grouped: dict[str, list[Mapping[str, object]]] = {}
        for pair in pairs.values():
            grouped.setdefault(str(pair[dimension]), []).append(pair)
        result[dimension] = [
            {
                dimension: key,
                "total": len(rows),
                "labelled": sum(
                    row["panel_class"] in {"unanimous", "decisive"} for row in rows
                ),
                "labelled_rate": sum(
                    row["panel_class"] in {"unanimous", "decisive"} for row in rows
                )
                / len(rows),
                "panel_tie": sum(row["panel_class"] == "panel-tie" for row in rows),
                "contested": sum(row["panel_class"] == "contested" for row in rows),
                "unlabelled": sum(row["panel_class"] == "unlabelled" for row in rows),
            }
            for key, rows in sorted(grouped.items())
        ]
    return result


def _dissent_rates(
    pairs: Mapping[str, Mapping[str, object]], over_split_category: str
) -> list[dict[str, object]]:
    target = [
        pair for pair in pairs.values() if pair["category"] == over_split_category
    ]
    variants = sorted({str(pair["variant"]) for pair in target})
    rows = []
    for variant in variants:
        variant_pairs = [pair for pair in target if pair["variant"] == variant]
        decisive = sum(pair["panel_class"] == "decisive" for pair in variant_pairs)
        rates: dict[str, int] = {}
        for pair in variant_pairs:
            for vote in pair["dissent"]:
                rates[str(vote["lens"])] = rates.get(str(vote["lens"]), 0) + 1
            for vote in pair["votes"]:
                rates.setdefault(str(vote["lens"]), 0)
        rows.extend(
            {
                "variant": variant,
                "lens": lens,
                "dissent": count,
                "decisive": decisive,
                "dissent_rate": count / decisive if decisive else None,
            }
            for lens, count in sorted(rates.items())
        )
    return rows
