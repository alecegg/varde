"""Count golden quality corpus items across public and restricted locations."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
ITEMS = ROOT / "code" / "bench" / "quality-corpus" / "items"
LANGUAGES = ("python", "typescript", "java", "csharp", "go", "rust", "cpp")
VARIANTS = ("tiny", "sensible", "monolith", "padded", "sizematched", "namematched")
SUFFIX = {
    "python": ".py",
    "typescript": ".ts",
    "java": ".java",
    "csharp": ".cs",
    "go": ".go",
    "rust": ".rs",
    "cpp": ".cpp",
}
sys.path.insert(0, str(ROOT / "code" / "bench" / "quality-corpus" / "tools"))
from behaviour_runner import available_commands  # noqa: E402, RUF100 - tools path must be on sys.path first
from place_item import restricted_root  # noqa: E402, RUF100 - tools path must be on sys.path first


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except OSError, ValueError:
        return {}


def read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}


def valid_pair(directory: Path) -> bool:
    pair = read_json(directory / "pair.json")
    pairs = pair.get("pairs")
    if isinstance(pairs, list):
        return len(pairs) >= 5 and all(
            isinstance(item, dict)
            and item.get("pair_id")
            and (directory / str(item.get("left", ""))).is_file()
            and (directory / str(item.get("right", ""))).is_file()
            for item in pairs
        )
    left, right = pair.get("left"), pair.get("right")
    if left and right:
        return (
            isinstance(left, str)
            and isinstance(right, str)
            and (directory / left).is_file()
            and (directory / right).is_file()
        )
    return bool(
        pair.get("left_id")
        and pair.get("right_id")
        and pair.get("left_role")
        and pair.get("right_role")
    )


def item_dirs(root: Path):
    if root.is_dir():
        yield from (
            p
            for p in root.rglob("*")
            if p.is_dir()
            and ((p / "manifest.toml").is_file() or (p / "pair.json").is_file())
        )


def classify(
    directory: Path, manifest: dict, pair: dict
) -> tuple[str | None, str | None]:
    lang = manifest.get("language") or pair.get("language")
    if lang not in LANGUAGES:
        lang = next((name for name in LANGUAGES if name in directory.parts), None)
    if lang not in LANGUAGES:
        lang = next(
            (name for name in LANGUAGES if directory.name.endswith(f"-{name}")), None
        )
    cat = manifest.get("category") or pair.get("category")
    has_b_shape = (
        pair.get("task")
        and pair.get("language")
        and isinstance(pair.get("pairs"), list)
    )
    if cat is None and has_b_shape:
        variants = {
            path.stem
            for path in directory.iterdir()
            if path.is_file() and path.suffix == SUFFIX.get(lang)
        }
        if set(VARIANTS) <= variants:
            cat = "b"
    parts = set(directory.parts)
    if cat is None:
        if "_bprime" in parts:
            cat = "b'"
        elif "_cd" in parts:
            cat = next((part for part in ("c", "d") if part in parts), None)
        elif "b" in parts:
            cat = "b"
        elif directory.name.startswith("anchor-"):
            cat = "e"
        elif "misc" in parts or directory.name.startswith("structured-"):
            cat = "a"
    return lang, cat


def alt_good_versions(directory: Path, language: str, pair: dict) -> int:
    """Count exported alt-good versions declared against sensible, files present."""
    pairs = pair.get("pairs")
    if not isinstance(pairs, list):
        return 0
    suffix = SUFFIX.get(language, "")
    names = {
        entry.get("right")
        for entry in pairs
        if isinstance(entry, dict) and entry.get("right_role") == "alt-good"
    }
    return sum(
        1
        for name in names
        if isinstance(name, str)
        and name.endswith(suffix)
        and (directory / name).is_file()
    )


def add_item(
    directory: Path, lang: str, cat: str | None, pair: dict, state: dict
) -> None:
    task = pair.get("task", directory.name)
    if cat == "b":
        variants = {
            p.stem
            for p in directory.iterdir()
            if p.is_file() and p.suffix == SUFFIX[lang]
        }
        if not set(VARIANTS) <= variants or not valid_pair(directory):
            return
        tier = "rich" if task in state["rich"] else "small"
        state["tasks"][lang][tier].add(task)
        if tier == "rich":
            alts = alt_good_versions(directory, lang, pair)
            state["alts"][lang][task] = alts
            state["counts"][lang]["alt_good"] += alts
        if task in (state["small"] | state["rich"]) & state["idioms"]:
            state["idiom_tasks"][lang].add(task)
        return
    if cat in {"a", "e"} and valid_pair(directory):
        state["counts"][lang]["anchors" if cat == "e" else "a"] += 1
    elif cat in {"b'", "bprime"}:
        state["counts"][lang]["bprime"] += 1
    elif cat in {"c", "d"}:
        state["counts"][lang][cat] += 1


def scan(
    roots: list[Path], small_tasks: set[str], rich_tasks: set[str], idioms: set[str]
) -> dict:
    keys = (
        "a",
        "b_small",
        "b_rich",
        "bprime",
        "c",
        "d",
        "anchors",
        "idiom",
        "alt_good",
    )
    result = {lang: dict.fromkeys(keys, 0) for lang in LANGUAGES}
    b_tasks = {lang: {"small": set(), "rich": set()} for lang in LANGUAGES}
    idiom_tasks = {lang: set() for lang in LANGUAGES}
    alt_tasks = {lang: {} for lang in LANGUAGES}
    state = {
        "counts": result,
        "tasks": b_tasks,
        "idiom_tasks": idiom_tasks,
        "alts": alt_tasks,
        "small": small_tasks,
        "rich": rich_tasks,
        "idioms": idioms,
    }
    seen = set()
    for root in roots:
        for directory in item_dirs(root):
            pair = read_json(directory / "pair.json")
            lang, cat = classify(
                directory, read_toml(directory / "manifest.toml"), pair
            )
            if lang not in LANGUAGES or (lang, cat, str(directory.resolve())) in seen:
                continue
            seen.add((lang, cat, str(directory.resolve())))
            add_item(directory, lang, cat, pair, state)
    for lang in LANGUAGES:
        result[lang]["b_small"] = len(b_tasks[lang]["small"])
        result[lang]["b_rich"] = len(b_tasks[lang]["rich"])
        result[lang]["idiom"] = len(idiom_tasks[lang])
        result[lang]["alt_good"] = sum(alt_tasks[lang].values())
        result[lang]["alt_good_tasks"] = dict(sorted(alt_tasks[lang].items()))
    return result


def idiom_ids(path: Path) -> set[str]:
    try:
        bank = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return set()
    return {task["id"] for task in bank.get("tasks", []) if task.get("idiom_tags")}


def toolchain(language: str) -> bool:
    return available_commands(SUFFIX[language]) is not None


def gaps(counts: dict, bank: Path) -> dict[str, list[str]]:
    gaps_by_lang = {}
    for lang, row in counts.items():
        missing = []
        for category, actual, target in (
            ("a", row["a"], 6),
            ("b tasks", row["b_small"] + row["b_rich"], 6),
            ("b'", row["bprime"], 2),
            ("c", row["c"], 6),
            ("d", row["d"], 4),
            ("anchors", row["anchors"], 2),
            ("idiom-heavy tasks", row["idiom"], 2),
        ):
            if actual < target:
                missing.append(f"{category} {actual}/{target}")
        if not toolchain(lang):
            missing.append("toolchain missing")
        gaps_by_lang[lang] = missing
    return gaps_by_lang


def render_report(counts: dict, gap_map: dict[str, list[str]]) -> str:
    lines = [
        (
            "language | a | b-small | b-rich | b' | c | d | anchors | idiom-heavy"
            " | alt-good | gaps"
        ),
        "--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---",
    ]
    for lang, row in counts.items():
        gaps_text = ", ".join(gap_map[lang]) or "complete"
        lines.append(
            f"{lang} | {row['a']}/6 | {row['b_small']}/6 | {row['b_rich']}/4 | "
            f"{row['bprime']}/2 | {row['c']}/6 | {row['d']}/4 | "
            f"{row['anchors']}/2 | {row['idiom']} | {row.get('alt_good', 0)} | "
            f"{gaps_text}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--report", action="store_true")
    mode.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    tiers_path = ROOT / "code/bench/quality-corpus/taskbank/tiers.json"
    try:
        tiers = json.loads(tiers_path.read_text(encoding="utf-8"))
        small_tasks = set(tiers["tiers"]["small"])
        rich_tasks = set(tiers["tiers"]["rich"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"cannot read valid tier registry {tiers_path}: {error}", file=sys.stderr)
        return 2
    roots = [ITEMS, restricted_root()]
    bank = ROOT / "code/bench/quality-corpus/taskbank/bank.json"
    counts = scan(roots, small_tasks, rich_tasks, idiom_ids(bank))
    gap_map = gaps(counts, bank)
    if args.json:
        print(json.dumps({"counts": counts, "gaps": gap_map}, indent=2, sort_keys=True))
    else:
        print(render_report(counts, gap_map))
    return (
        0
        if all(not values for values in gap_map.values())
        else (1 if args.check else 0)
    )


if __name__ == "__main__":
    raise SystemExit(main())
