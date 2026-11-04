"""Task tier registry and consistency checks for category (b) items."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from place_item import restricted_root

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "taskbank" / "tiers.json"
BANK = ROOT / "taskbank" / "bank.json"


def _registry(path: Path = REGISTRY) -> dict:
    return json.loads(path.read_text())


def tier_of(task_id: str) -> str:
    tiers = _registry()["tiers"]
    for tier, task_ids in tiers.items():
        if task_id in task_ids:
            return tier
    raise KeyError(task_id)


def padded_is_evidence(task_id: str) -> bool:
    registry = _registry()
    tier = tier_of(task_id)
    return registry["padded_evidence"][tier]


def rich_tasks() -> list[str]:
    return list(_registry()["tiers"]["rich"])


def _tier_overlap_problems(small: set[str], rich: set[str]) -> list[str]:
    overlap = small & rich
    if not overlap:
        return []
    return [f"task ids occur in both tiers: {sorted(overlap)}"]


def _bank_coverage_problems(
    bank_ids: set[str], small: set[str], rich: set[str]
) -> list[str]:
    tier_ids = small | rich
    problems = []
    missing = bank_ids - tier_ids
    extra = tier_ids - bank_ids - rich
    if missing:
        problems.append(f"bank ids missing from tiers: {sorted(missing)}")
    if extra:
        problems.append(f"unknown tier ids: {sorted(extra)}")
    problems.extend(
        f"bank id is not in exactly one tier: {task_id}"
        for task_id in sorted(bank_ids & tier_ids)
        if task_id not in small and task_id not in rich
    )
    return problems


def _rich_item_presence_problems(
    rich: set[str], bank_ids: set[str], repo_item_ids: set[str]
) -> list[str]:
    return [
        f"rich task is absent from bank and repo items: {task_id}"
        for task_id in sorted(rich - bank_ids - repo_item_ids)
    ]


def _repo_item_id_problems(repo_item_ids: list[str], tier_ids: set[str]) -> list[str]:
    return [
        f"unknown repo item task id: {task_id}"
        for task_id in sorted(
            task_id for task_id in repo_item_ids if task_id not in tier_ids
        )
    ]


def _profile_problems(
    entries: list[tuple[Path, str, bool, bool, str | None, str]], rich: set[str]
) -> list[str]:
    problems = []
    for (
        directory,
        task_id,
        is_profile_file,
        profile_exists,
        profile,
        subject,
    ) in entries:
        if task_id in rich:
            if not is_profile_file:
                problems.append(
                    f"rich {subject}task lacks spec-profile.toml: {directory}"
                )
            elif profile != "layered":
                problems.append(
                    f"rich {subject}task profile is not layered: {directory}"
                )
        elif profile_exists:
            problems.append(f"small {subject}task has spec-profile.toml: {directory}")
    return problems


def _restricted_other_category_ids(
    directories: list[Path], languages: set[str], tier_ids: set[str], bank_ids: set[str]
) -> list[str]:
    other_category = []
    for directory in directories:
        suffix = next(
            (f"-{lang}" for lang in languages if directory.name.endswith(f"-{lang}")),
            None,
        )
        if suffix is None:
            continue
        task_id = directory.name[: -len(suffix)]
        if task_id not in tier_ids and task_id not in bank_ids:
            other_category.append(task_id)
    return other_category


def check(
    items: Path = ROOT / "items",
    bank: Path = BANK,
    store: Path | None = None,
    registry_path: Path = REGISTRY,
) -> list[str]:
    registry = json.loads(registry_path.read_text())
    tier_groups = registry["tiers"]
    small = set(tier_groups.get("small", []))
    rich = set(tier_groups.get("rich", []))
    bank_ids = {task["id"] for task in json.loads(bank.read_text())["tasks"]}
    tier_ids = small | rich
    item_dirs = sorted(path for path in items.glob("*/b/*") if path.is_dir())
    repo_task_ids = {item_dir.name for item_dir in item_dirs}
    errors = _tier_overlap_problems(small, rich)
    errors.extend(_bank_coverage_problems(bank_ids, small, rich))
    errors.extend(_rich_item_presence_problems(rich, bank_ids, repo_task_ids))
    errors.extend(
        _repo_item_id_problems([item_dir.name for item_dir in item_dirs], tier_ids)
    )
    repo_profiles = []
    for item_dir in item_dirs:
        task_id = item_dir.name
        if task_id not in tier_ids:
            continue
        profile_path = item_dir / "spec-profile.toml"
        is_profile_file = profile_path.is_file()
        profile_exists = profile_path.exists()
        profile = (
            tomllib.loads(profile_path.read_text()).get("profile")
            if is_profile_file
            else None
        )
        repo_profiles.append(
            (item_dir, task_id, is_profile_file, profile_exists, profile, "")
        )
    errors.extend(_profile_problems(repo_profiles, rich))

    restricted = store if store is not None else restricted_root()
    if not restricted.is_dir():
        print(f"note: restricted store absent, skipped: {restricted}")
    else:
        languages = set(json.loads(bank.read_text())["languages"])
        restricted_dirs = sorted(
            path for path in restricted.rglob("*") if path.is_dir()
        )
        restricted_profiles = []
        for directory in restricted_dirs:
            name = directory.name
            suffix = next(
                (f"-{lang}" for lang in languages if name.endswith(f"-{lang}")), None
            )
            if suffix is None:
                continue
            task_id = name[: -len(suffix)]
            if task_id not in tier_ids:
                continue
            profile_path = directory / "spec-profile.toml"
            is_profile_file = profile_path.is_file()
            profile_exists = profile_path.exists()
            profile = (
                tomllib.loads(profile_path.read_text()).get("profile")
                if is_profile_file
                else None
            )
            restricted_profiles.append(
                (
                    directory,
                    task_id,
                    is_profile_file,
                    profile_exists,
                    profile,
                    "restricted ",
                )
            )
        errors.extend(_profile_problems(restricted_profiles, rich))
        other_category = _restricted_other_category_ids(
            restricted_dirs, languages, tier_ids, bank_ids
        )
        if other_category:
            examples = ", ".join(sorted(set(other_category))[:5])
            print(
                f"note: {len(other_category)} restricted dirs belong to "
                "other categories" + (f" (e.g. {examples})" if examples else "")
            )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--items", type=Path, default=ROOT / "items")
    parser.add_argument("--bank", type=Path, default=BANK)
    parser.add_argument("--store", type=Path)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    args = parser.parse_args(argv)
    if not args.check:
        parser.error("--check is required")
    errors = check(args.items, args.bank, args.store, args.registry)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("task tiers are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
