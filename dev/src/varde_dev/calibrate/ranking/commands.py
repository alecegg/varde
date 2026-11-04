"""Command line reporting for calibration rankings."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Never

from varde_dev.calibrate.ranking.core import compare_raters, rank_labels
from varde_dev.calibrate.ranking.plan import plan_next
from varde_dev.calibrate.ranking.sources import labels_for_rater
from varde_dev.calibrate.reports.dataset import read_dataset_files


def _raise(error: Exception) -> Never:
    raise error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m varde_dev.calibrate rank")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--rater")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--compare", nargs=2, metavar=("ID1", "ID2"))
    parser.add_argument("--plan-next", action="store_true")
    parser.add_argument("-k", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--budget", type=int)
    parser.add_argument("--lens", type=Path, action="append", default=[])
    parser.add_argument("--lens-count", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        data = read_dataset_files(args.dataset)
        if args.compare:
            left_labels = labels_for_rater(
                args.dataset,
                args.compare[0],
                data["labels"],
                data["units"],
                data["items"],
            )
            right_labels = labels_for_rater(
                args.dataset,
                args.compare[1],
                data["labels"],
                data["units"],
                data["items"],
            )
            left = rank_labels(
                left_labels, data["units"], data["items"], args.compare[0]
            )
            right = rank_labels(
                right_labels, data["units"], data["items"], args.compare[1]
            )
            result = compare_raters(left, right)
        elif args.plan_next:
            if args.rater is None:
                _raise(ValueError("--plan-next requires --rater"))
            lens_count = _lens_count(args)
            labels = labels_for_rater(
                args.dataset,
                args.rater,
                data["labels"],
                data["units"],
                data["items"],
            )
            result = plan_next(
                labels,
                data["units"],
                data["items"],
                args.rater,
                settings={
                    "k": args.k,
                    "repeats": args.repeats,
                    "lens_count": lens_count,
                },
            )
        else:
            if args.rater is None:
                _raise(ValueError("ranking requires --rater"))
            rule = {"budget": args.budget} if args.budget is not None else None
            labels = labels_for_rater(
                args.dataset,
                args.rater,
                data["labels"],
                data["units"],
                data["items"],
            )
            result = rank_labels(
                labels, data["units"], data["items"], args.rater, rule=rule
            )
        print(
            json.dumps(result, sort_keys=True, separators=(",", ":"))
            if args.json
            else _format(result)
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"calibrate rank: {error}", file=sys.stderr)
        return 1
    else:
        return 0


def _lens_count(args: argparse.Namespace) -> int:
    if args.lens_count is not None and args.lens:
        raise ValueError("use either --lens files or --lens-count")
    count = args.lens_count if args.lens_count is not None else len(args.lens) or 1
    if count < 1:
        raise ValueError("lens count must be positive")
    return count


def _format(result: dict[str, object]) -> str:
    if "pairs" in result:
        pairs = ", ".join("/".join(pair) for pair in result["pairs"])
        return (
            f"Next pairs: {pairs}\nProjected remaining calls: "
            f"{result['projected_remaining_calls']}"
        )
    if "groups" in result:
        lines = []
        for group in result["groups"]:
            lines.append(
                f"{group['group_id']}: Kendall tau {group['kendall_tau']:.2f}; "
                f"top {group['top_agreement']}; bottom {group['bottom_agreement']}"
            )
            lines.extend(
                f"  disagreement: {', '.join(row['items'])}"
                for row in group["disagreements"]
            )
        return "\n".join(lines)
    lines = [f"Ranking for {result['rater_id']}:"]
    for row in result["items"]:
        interval = row["rank_interval"]
        lines.append(
            f"{row['group_id']} #{row['rank']} {row['item_id']}: rating "
            f"{row['rating']:.4f}, SE {row['standard_error']}, rank interval "
            f"{interval[0]}–{interval[1]}"
        )
    lines.append(f"Contested labels excluded: {result['contested_count']}")
    lines.append(f"Unresolved labels: {result['unresolved_count']}")
    lines.append(f"Stop state: {result['stop_state']['reason'] or 'open'}")
    return "\n".join(lines)
