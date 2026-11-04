"""Derive per-language calibration thresholds from calibration-repo facts.

Input: a directory of facts JSONL files (the `varde code score --facts` format,
facts-1 or facts-2 with measures merged), one `<owner>__<repo>.jsonl` per
manifest repository. Only repositories whose manifest role is `calibration` are
read; a held-out, pairs, history, mutation-base or unknown name raises before
any file is opened. No labels, no model calls.

Quantiles are repo-balanced and token-weighted (design section 4, steps 4.1 and
4.2): each repository carries equal total weight, spread over its items in
proportion to their tokens, all in integer arithmetic. Output is one candidate
`cal-1` TOML: global strengths and limits copied from the installed (tuning)
calibration, per-language thresholds, S anchor densities, provisional X, Y,
cap and the Q5 bands `p65` and `p10`. Every language stays `report-only`; a
language whose resolver verdict is not PASS is marked `provisional = "resolver"`
and a language without facts keeps the placeholder values, marked as such.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[3]
for _path in (ROOT / "code/src", TOOLS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import calibration_gates  # noqa: E402, RUF100
import score_dataset  # noqa: E402, RUF100
from varde_code.quality_score import score_scope  # noqa: E402, RUF100
from varde_code.quality_score.calibration import load_calibration  # noqa: E402, RUF100
from varde_code.quality_score.costs import unique_functions  # noqa: E402, RUF100
from varde_code.quality_score.fixedpoint.arithmetic import MICRO, to_decimal  # noqa: E402, RUF100

CALIBRATION_ROLE = "calibration"
CANDIDATE_ID = "cal-1"
PLACEHOLDER = ROOT / "code/src/varde_code/quality_score/calibration/placeholder.toml"
MANIFEST = TOOLS.parent / "corpus/manifest.toml"
DEFAULT_LANGUAGES = "python,typescript,csharp"
WEIGHT_SCALE = 10**9
MIN_REPOS = 5
TAIL_FACTOR_NUM, TAIL_FACTOR_DEN = 3, 2
THRESHOLD_QUANTILES = {  # parameter -> (pool, numerator, denominator)
    "Plo": ("size", 25, 100),
    "t_frag": ("size", 50, 100),
    "Phi": ("size", 70, 100),
    "c0": ("cognitive", 70, 100),
    "dp0": ("depth", 85, 100),
    "k0": ("fan_out", 85, 100),
    "t0": ("tree_size", 85, 100),
}
FRAGMENTS_QUANTILE = (70, 100)
ANCHOR_QUANTILES = {
    "anchor_d10": 10,
    "anchor_d50": 50,
    "anchor_d90": 90,
    "anchor_d99": 99,
}
OUT_OF_SCOPE = ("java", "go", "rust", "cpp")

Record = Mapping[str, Any]
Pairs = list[tuple[int, int]]  # (value, tokens)


# ---- pure statistics --------------------------------------------------------


def weighted_quantile(
    items: Sequence[tuple[int, int]], numerator: int, denominator: int
) -> int:
    """Smallest value whose cumulative weight reaches numerator/denominator."""
    ordered = sorted(items)
    total = sum(weight for _, weight in ordered)
    running = 0
    for value, weight in ordered:
        running += weight
        if running * denominator >= numerator * total:
            return value
    return ordered[-1][0]


def balanced(repos: Iterable[Pairs]) -> list[tuple[int, int]]:
    """Give every repository the same total weight; weight items by tokens."""
    items: list[tuple[int, int]] = []
    for pairs in repos:
        total = sum(tokens for _, tokens in pairs)
        if total <= 0:
            continue
        items.extend((value, tokens * WEIGHT_SCALE // total) for value, tokens in pairs)
    return [(value, max(weight, 1)) for value, weight in items]


def lower_quantile(values: Sequence[int], numerator: int, denominator: int) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) * numerator // denominator]


def at_least(value: int, floor: int = 1) -> int:
    return max(value, floor)


# ---- facts pools ------------------------------------------------------------


def structure_measured(record: Record, function: Record) -> bool:
    return record.get("structure_confidence") != "low" and not function_is_unmeasured(
        function, record
    )


def function_is_unmeasured(function: Record, record: Record) -> bool:
    start, end = function.get("line"), function.get("end_line", function.get("line"))
    if start is None or end is None:
        return False
    return any(
        start <= region.get("end_line", -1) and end >= region.get("start_line", 1)
        for region in record.get("unmeasured_regions") or ()
    )


def repo_pools(records: Iterable[Record]) -> dict[str, Pairs]:
    """Per-metric (value, weight-in-tokens) pairs of one repository and language."""
    pools: dict[str, Pairs] = {
        name: [] for name in ("size", "cognitive", "depth", "fan_out", "tree_size")
    }
    for record in records:
        for function in unique_functions(list(record.get("functions") or ())):
            tokens = function.get("tokens") or 0
            if tokens <= 0:
                continue
            if not function.get("exempt_role"):
                pools["size"].append((tokens, tokens))
            pools["cognitive"].append((function.get("cognitive") or 0, tokens))
            if not structure_measured(record, function):
                continue
            for name in ("depth", "fan_out", "tree_size"):
                if function.get(name) is not None:
                    pools[name].append((function[name], tokens))
    return pools


def file_fragment_pairs(records: Iterable[Record], t_frag: int) -> Pairs:
    """(fragment count, file tokens) per file with a measured structure."""
    pairs = []
    for record in records:
        tokens = record.get("tokens") or 0
        if tokens <= 0 or record.get("structure_confidence") == "low":
            continue
        count = sum(
            1
            for function in unique_functions(list(record.get("functions") or ()))
            if function.get("fragment_scope") == "file"
            and (function.get("tokens") or 0) <= t_frag
            and not function.get("exempt_role")
            and not function_is_unmeasured(function, record)
        )
        pairs.append((count, tokens))
    return pairs


def derive_parameters(repos: Mapping[str, Sequence[Record]]) -> dict[str, int]:
    """Integer thresholds from the language's records, grouped by repository."""
    pools = [repo_pools(records) for _, records in sorted(repos.items())]
    values: dict[str, int] = {}
    for name, (pool, numerator, denominator) in THRESHOLD_QUANTILES.items():
        items = balanced(repo[pool] for repo in pools)
        if items:
            values[name] = weighted_quantile(items, numerator, denominator)
    if not {"Plo", "t_frag", "Phi"} <= values.keys():
        raise ValueError("no measurable function sizes in the calibration facts")
    values["Plo"] = at_least(values["Plo"])
    values["t_frag"] = at_least(values["t_frag"], values["Plo"])
    values["Phi"] = at_least(values["Phi"], values["t_frag"])
    fragments = balanced(
        file_fragment_pairs(records, values["t_frag"])
        for _, records in sorted(repos.items())
    )
    if fragments:
        values["cmin"] = at_least(weighted_quantile(fragments, *FRAGMENTS_QUANTILE))
    return values


# ---- scoring-dependent thresholds ------------------------------------------


def included_files(score: Any) -> list[Any]:
    return [
        file
        for file in score.files
        if not file.excluded and not file.not_applicable and file.tokens > 0
    ]


def strictly_increasing(values: Sequence[int]) -> list[int]:
    result: list[int] = []
    for value in values:
        result.append(max(value, result[-1] + 1) if result else value)
    return result


def anchor_densities(files_by_repo: Sequence[Sequence[Any]]) -> dict[str, int]:
    """S anchor densities: token-weighted, repo-balanced file-density quantiles."""
    items = balanced(
        [(file.density, file.tokens) for file in files] for files in files_by_repo
    )
    quantiles = [
        weighted_quantile(items, number, 100) for number in ANCHOR_QUANTILES.values()
    ]
    quantiles.append(quantiles[-1] * TAIL_FACTOR_NUM // TAIL_FACTOR_DEN)
    ordered = strictly_increasing(quantiles)
    return dict(zip([*ANCHOR_QUANTILES, "anchor_tail"], ordered, strict=True))


def score_bands(files_by_repo: Sequence[Sequence[Any]]) -> dict[str, int]:
    """Q5 bands: token-weighted, repo-balanced p65 and p10 of file scores (micro)."""
    items = balanced(
        [(file.score, file.tokens) for file in files] for files in files_by_repo
    )
    return {
        "p65": weighted_quantile(items, 65, 100),
        "p10": weighted_quantile(items, 10, 100),
    }


def repo_gate_values(files_by_repo: Sequence[Sequence[Any]]) -> dict[str, int]:
    """Provisional X (p25 of repo means), Y and cap (medians of repo min and max)."""
    means, minima, maxima = [], [], []
    for files in files_by_repo:
        if not files:
            continue
        tokens = sum(file.tokens for file in files)
        means.append(sum(file.tokens * file.gate_score for file in files) // tokens)
        minima.append(min(file.gate_score for file in files))
        maxima.append(
            max((fn.debt for file in files for fn in file.functions), default=0)
        )
    return {
        "X": lower_quantile(means, 25, 100),
        "Y": lower_quantile(minima, 50, 100),
        "cap": lower_quantile(maxima, 50, 100),
    }


def decimal_fields(values: Mapping[str, int]) -> dict[str, str]:
    return {name: to_decimal(value) for name, value in values.items()}


# ---- candidate assembly -----------------------------------------------------


def render_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, Mapping):
        raise TypeError("tables are rendered by render_table")
    if isinstance(value, list):
        return "[" + ", ".join(render_value(item) for item in value) + "]"
    return json.dumps(str(value))


def render_table(name: str, table: Mapping[str, Any]) -> str:
    lines = [f"[{name}]"]
    lines += [f"{key} = {render_value(value)}" for key, value in table.items()]
    return "\n".join(lines) + "\n"


def render_candidate(
    meta: Mapping[str, Any],
    global_table: Mapping[str, Any],
    languages: Mapping[str, Mapping[str, Any]],
    validations: Mapping[str, Mapping[str, Any]],
    limits: Mapping[str, Mapping[str, Any]],
) -> str:
    blocks = [render_table("calibration", meta), render_table("global", global_table)]
    blocks += [
        render_table(f"language.{name}", table) for name, table in languages.items()
    ]
    blocks += [
        render_table(f"language.{name}.validation", table)
        for name, table in validations.items()
    ]
    blocks += [
        render_table(f"limits.{group}", table) for group, table in limits.items()
    ]
    return "\n".join(blocks)


def load_text(text: str) -> Any:
    """Load calibration TOML text through the strict loader."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "candidate.toml"
        path.write_text(text, encoding="utf-8")
        return load_calibration(path)


def derived_language(
    base: Mapping[str, Any],
    repos: Mapping[str, Sequence[Record]],
    global_table: Mapping[str, Any],
    meta: Mapping[str, Any],
    limits: Mapping[str, Mapping[str, Any]],
    language: str,
) -> dict[str, Any]:
    """Language table with quantile thresholds, anchors, X, Y, cap and Q5 bands."""
    table = {**base, **derive_parameters(repos)}
    first = render_candidate(meta, global_table, {language: table}, {}, limits)
    calibration = load_text(first)
    scores = [
        score_scope(list(records), calibration) for _, records in sorted(repos.items())
    ]
    files_by_repo = [included_files(score) for score in scores]
    table.update(decimal_fields(anchor_densities(files_by_repo)))
    table.update(decimal_fields(repo_gate_values(files_by_repo)))
    return {
        "table": table,
        "bands": score_bands(files_by_repo),
        "repos": len(files_by_repo),
    }


# ---- inputs -----------------------------------------------------------------


def manifest_roles(manifest: Path) -> dict[str, str]:
    """Facts file stem -> manifest role (a repository has at most one role)."""
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    return {
        repo["name"].replace("/", "__"): (repo.get("roles") or ["roleless"])[0]
        for repo in data.get("repositories", [])
    }


def check_readable(facts_files: Sequence[Path], roles: Mapping[str, str]) -> None:
    """Raise before reading anything when a file is not a calibration repository."""
    for path in facts_files:
        role = roles.get(path.stem)
        if role is None:
            raise ValueError(
                f"{path.name}: not a manifest repository; refusing to read"
            )
        if role != CALIBRATION_ROLE:
            raise ValueError(
                f"{path.name}: role {role!r}, not {CALIBRATION_ROLE!r}; "
                "test-split and held-out repositories are never read"
            )


def read_records(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    ]
    if not all(
        isinstance(row, dict) and row.get("contract") in {"facts-1", "facts-2"}
        for row in rows
    ):
        raise ValueError(f"{path.name}: every line must be a facts-1 or facts-2 object")
    return rows


def load_facts(
    facts_dir: Path | None, manifest: Path
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], str]:
    """language -> repo -> records, plus a digest of the input files."""
    if facts_dir is None or not facts_dir.is_dir():
        return {}, "none"
    files = sorted(facts_dir.glob("*.jsonl"))
    check_readable(files, manifest_roles(manifest))
    digest = hashlib.sha256()
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for path in files:
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
        for record in read_records(path):
            result.setdefault(record.get("language", ""), {}).setdefault(
                path.stem, []
            ).append(record)
    return result, digest.hexdigest()


def resolver_ready(plan_dir: Path, language: str) -> bool:
    return calibration_gates.resolver_status(
        plan_dir.parent / "resolver", language
    ).ready


# ---- main -------------------------------------------------------------------


def validation_table(
    language: str, derived: Mapping[str, Any] | None, ready: bool, digest: str
) -> dict[str, Any]:
    table: dict[str, Any] = {"state": "report-only"}
    if not ready:
        table["provisional"] = "resolver"
    if derived is None:
        table["provenance"] = (
            "placeholder values copied; no calibration facts; not derived"
        )
        return table
    # Q5 bands are score points; calibration_targets compares them as numbers.
    table.update({name: value / MICRO for name, value in derived["bands"].items()})
    repos = derived["repos"]
    note = (
        ""
        if repos >= MIN_REPOS
        else f"; {repos} of {MIN_REPOS} calibration repos, untiered"
    )
    table["provenance"] = (
        f"derived from {repos} calibration repos (repo-balanced, token-weighted), "
        f"inputs sha256 {digest}; X, Y, cap provisional (calibration repos, "
        "not held-out); "
        f"S anchors recorded as anchor_* densities and not yet read by the scorer{note}"
    )
    return table


def build_candidate(
    facts: Mapping[str, Mapping[str, Sequence[Record]]],
    digest: str,
    languages: Sequence[str],
    plan_dir: Path,
    placeholder: Path = PLACEHOLDER,
) -> str:
    base = tomllib.loads(placeholder.read_text(encoding="utf-8"))
    meta = {
        "id": CANDIDATE_ID,
        "formula": base["calibration"]["formula"],
        "validated": False,
        "anchors": "quantile anchors per language (anchor_* keys); provisional",
    }
    tables: dict[str, dict[str, Any]] = {}
    validations: dict[str, dict[str, Any]] = {}
    for name, values in base["language"].items():
        row = {key: value for key, value in values.items() if key != "validation"}
        derived = None
        if name in languages and facts.get(name):
            derived = derived_language(
                row, facts[name], base["global"], meta, base["limits"], name
            )
            row = derived["table"]
        tables[name] = row
        if name in OUT_OF_SCOPE:
            validations[name] = {
                "state": "report-only",
                "provenance": "copied unchanged from placeholder",
            }
            continue
        if name in languages:
            validations[name] = validation_table(
                name, derived, resolver_ready(plan_dir, name), digest
            )
        else:
            validations[name] = values.get("validation", {"state": "report-only"})
    text = render_candidate(meta, base["global"], tables, validations, base["limits"])
    load_text(text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts-dir", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--plan-dir", type=Path, default=score_dataset.plan_dir())
    parser.add_argument("--languages", default=DEFAULT_LANGUAGES)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    languages = [name.strip() for name in args.languages.split(",") if name.strip()]
    facts, digest = load_facts(args.facts_dir, args.manifest)
    text = build_candidate(facts, digest, languages, args.plan_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    derived = sorted(name for name in languages if facts.get(name))
    print(f"wrote {args.out}; derived from facts: {', '.join(derived) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
