"""Convert stored judgments into deterministic per-group rankings."""

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from itertools import combinations
from statistics import NormalDist

from varde_dev.calibrate.rating import fit, stop_state
from varde_dev.calibrate.reports import panel_label

SKIPPED = {"skip", "skipped", "abstain"}


def _latest_by_unit(
    labels: Sequence[Mapping[str, object]], rater_id: str
) -> list[Mapping[str, object]]:
    by_unit: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for label in labels:
        if label.get("rater_id") != rater_id:
            continue
        if str(label.get("choice", "")).lower() in SKIPPED:
            continue
        by_unit[str(label.get("unit_id", ""))].append(label)
    return [
        max(
            rows,
            key=lambda row: (
                str(row.get("timestamp", "")),
                json.dumps(row, sort_keys=True, separators=(",", ":")),
            ),
        )
        for _, rows in sorted(by_unit.items())
    ]


def _choice_item(
    label: Mapping[str, object],
    pair_items: tuple[str, str],
    item_map: Mapping[str, Mapping[str, object]],
) -> str | None:
    choice = str(label.get("choice", label.get("verdict", "")))
    if choice in pair_items:
        return choice
    if choice not in {"A", "B"}:
        return None
    order = label.get("order_shown")
    if isinstance(order, list) and len(order) == 2:
        return str(order[0] if choice == "A" else order[1])
    field = "a_item_id" if choice == "A" else "b_item_id"
    if label.get(field) is not None:
        return str(label[field])
    digest_field = "a_sha256" if choice == "A" else "b_sha256"
    digest = label.get(digest_field)
    if digest is None:
        return None
    return next(
        (
            item_id
            for item_id, item in sorted(item_map.items())
            if item.get("content_sha256") == digest
        ),
        None,
    )


def _canonical_votes(
    votes: object, pair_items: tuple[str, str]
) -> tuple[list[str], list[str]] | None:
    if not isinstance(votes, list):
        return None
    verdicts = []
    item_ids = []
    for vote in votes:
        if isinstance(vote, Mapping):
            item_id = vote.get("item_id")
            if item_id is not None:
                item_id = str(item_id)
                if item_id not in pair_items:
                    return None
                verdict = "A" if item_id == pair_items[0] else "B"
            else:
                verdict = str(vote.get("vote", "split"))
        else:
            verdict = str(vote)
        if verdict not in {"A", "B", "tie", "split"}:
            return None
        verdicts.append(verdict)
        item_ids.append(
            pair_items[0] if verdict == "A" else pair_items[1] if verdict == "B" else ""
        )
    return verdicts, item_ids


def _matches(
    labels: Sequence[Mapping[str, object]],
    units: Sequence[Mapping[str, object]],
    items: Sequence[Mapping[str, object]],
    rater_id: str,
) -> tuple[list[tuple[str, str, str, str]], int, int]:
    item_map = {str(item["id"]): item for item in items}
    unit_map = {str(unit["id"]): unit for unit in units}
    matches = []
    contested = unresolved = 0
    for label in _latest_by_unit(labels, rater_id):
        unit = unit_map.get(str(label.get("unit_id", "")))
        refs = unit.get("item_ids") if unit else None
        if not isinstance(refs, list) or len(refs) != 2:
            unresolved += 1
            continue
        pair_items = (str(refs[0]), str(refs[1]))
        group = str(unit.get("pair_group_id", ""))
        vote_data = _canonical_votes(label.get("votes"), pair_items)
        if vote_data is not None:
            verdicts, _ = vote_data
            if len(verdicts) != 3:
                unresolved += 1
                continue
            panel_class, _ = panel_label(verdicts)
            if panel_class == "contested":
                contested += 1
                continue
            if panel_class == "panel-tie":
                matches.append((group, pair_items[0], pair_items[1], "tie"))
                continue
            winner = "A" if verdicts.count("A") > verdicts.count("B") else "B"
            chosen = pair_items[0] if winner == "A" else pair_items[1]
        else:
            choice = str(label.get("choice", label.get("verdict", "")))
            if choice.lower() in SKIPPED:
                continue
            if choice.lower() in {"contested", "split", "inconsistent"}:
                contested += 1
                continue
            if choice.lower() == "tie":
                matches.append((group, pair_items[0], pair_items[1], "tie"))
                continue
            chosen = _choice_item(label, pair_items, item_map)
        if chosen is None or chosen not in item_map or chosen not in pair_items:
            unresolved += 1
            continue
        other = pair_items[1] if chosen == pair_items[0] else pair_items[0]
        matches.append((group, chosen, other, "x"))
    return sorted(matches), contested, unresolved


def rank_labels(
    labels: Sequence[Mapping[str, object]],
    units: Sequence[Mapping[str, object]],
    items: Sequence[Mapping[str, object]],
    rater_id: str,
    *,
    rule: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Fit ratings, intervals, and stop state from one rater's stored labels."""
    matches, contested, unresolved = _matches(labels, units, items, rater_id)
    ranked_items = [
        (str(item.get("pair_group_id", "")), str(item["id"])) for item in items
    ]
    ratings = fit(matches, ranked_items)
    groups = {
        group: sorted(item for owner, item in ranked_items if owner == group)
        for group in sorted({group for group, _ in ranked_items})
    }
    stopping = stop_state(ratings, matches, groups, dict(rule or {}))
    order = {
        group: sorted(members, key=lambda item: (-float(ratings[item]["rating"]), item))
        for group, members in groups.items()
    }
    rank_intervals = _rank_intervals(
        order, ratings, float((rule or {}).get("confidence", 0.9))
    )
    rows = [
        {
            "group_id": group,
            "item_id": item,
            **ratings[item],
            "rank": position,
            "rank_interval": rank_intervals[group][item],
        }
        for group, members in order.items()
        for position, item in enumerate(members, 1)
    ]
    return {
        "rater_id": rater_id,
        "items": rows,
        "contested_count": contested,
        "unresolved_count": unresolved,
        "excluded_count": contested + unresolved,
        "stop_state": stopping,
        "matches": matches,
    }


def _rank_intervals(order, ratings, confidence):
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    intervals = {}
    for group, members in order.items():
        for item in members:
            error = ratings[item]["standard_error"]
            if not isinstance(error, (float, int)):
                interval = [1, len(members)]
            else:
                rating = float(ratings[item]["rating"])
                margin = z * float(error)
                better = sum(
                    float(ratings[other]["rating"])
                    - z * float(ratings[other]["standard_error"])
                    > rating + margin
                    for other in members
                    if isinstance(ratings[other]["standard_error"], (float, int))
                )
                worse = sum(
                    float(ratings[other]["rating"])
                    + z * float(ratings[other]["standard_error"])
                    < rating - margin
                    for other in members
                    if isinstance(ratings[other]["standard_error"], (float, int))
                )
                interval = [better + 1, len(members) - worse]
            intervals.setdefault(group, {})[item] = interval
    return intervals


def compare_raters(
    left: Mapping[str, object], right: Mapping[str, object]
) -> dict[str, object]:
    """Compare rank order, extreme items, and the most discordant pairs."""
    left_rows = left["items"]
    right_rows = right["items"]
    summaries = []
    for group in sorted(
        {str(row["group_id"]) for row in left_rows}
        & {str(row["group_id"]) for row in right_rows}
    ):
        lmap = {
            str(row["item_id"]): int(row["rank"])
            for row in left_rows
            if row["group_id"] == group
        }
        rmap = {
            str(row["item_id"]): int(row["rank"])
            for row in right_rows
            if row["group_id"] == group
        }
        common = sorted(lmap.keys() & rmap.keys())
        discordant = []
        concordant = 0
        for a, b in combinations(common, 2):
            same = (lmap[a] - lmap[b]) * (rmap[a] - rmap[b]) > 0
            concordant += same
            if not same:
                discordant.append(
                    {
                        "items": [a, b],
                        "rank_distance": abs(lmap[a] - lmap[b])
                        + abs(rmap[a] - rmap[b]),
                    }
                )
        count = len(common) * (len(common) - 1) // 2
        tau = 1.0 if count == 0 else (concordant - len(discordant)) / count
        lorder = sorted(common, key=lmap.get)
        rorder = sorted(common, key=rmap.get)
        discordant.sort(key=lambda row: (-row["rank_distance"], row["items"]))
        summaries.append(
            {
                "group_id": group,
                "kendall_tau": round(tau, 8),
                "top_agreement": bool(common and lorder[0] == rorder[0]),
                "bottom_agreement": bool(common and lorder[-1] == rorder[-1]),
                "disagreements": discordant,
            }
        )
    return {
        "left_rater": left["rater_id"],
        "right_rater": right["rater_id"],
        "groups": summaries,
    }
