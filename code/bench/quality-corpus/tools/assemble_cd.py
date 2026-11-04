"""Select and assemble offline category (c) and (d) pairs."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LANGUAGES = ("python", "typescript", "java", "csharp", "go", "rust", "cpp")
EXTENSIONS = {
    "python": ".py",
    "typescript": ".ts",
    "java": ".java",
    "csharp": ".cs",
    "go": ".go",
    "rust": ".rs",
    "cpp": ".h",
}
PERMISSIVE = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "MPL-2.0",
    "EPL-1.0",
    "EPL-2.0",
}
TARGET_C = 6
TARGET_D = 4
HELD_OUT = (
    "reorder-and-rename",
    "inline-all-locals",
    "add-dead-branches",
    "wrap-in-class",
    "loops-to-recursion",
)


def load_mined(directory: Path, language: str) -> list[dict[str, Any]]:
    records = []
    for path in sorted((directory / language).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                if record.get("language") == language:
                    records.append(record)
    return records


def license_allowed(record: dict[str, Any]) -> bool:
    license_name = record.get("license", "")
    return license_name in PERMISSIVE


def select_mined(
    records: list[dict[str, Any]], limit: int = TARGET_C
) -> list[dict[str, Any]]:
    """Choose eligible records in stable, repository-diverse order."""
    candidates = sorted(
        (
            r
            for r in records
            if license_allowed(r)
            and r.get("changed_functions")
            and r.get("intent_evidence", {}).get("message")
            and len(r.get("changed_files", [])) <= 5
            and len(r.get("changed_functions", [])) <= 6
        ),
        key=lambda r: (r.get("repo", ""), r.get("child_sha", "")),
    )
    chosen: list[dict[str, Any]] = []
    seen_repos: set[str] = set()
    seen_files: set[str] = set()
    for require_new_repo in (True, False):
        for record in candidates:
            repo = record.get("repo", "")
            files = set(record.get("changed_files", []))
            if record in chosen or (require_new_repo and repo in seen_repos):
                continue
            if seen_files.intersection(files):
                continue
            chosen.append(record)
            seen_repos.add(repo)
            seen_files.update(files)
            if len(chosen) == limit:
                return chosen
    return chosen


def opaque_id(language: str, category: str, identity: str) -> str:
    return hashlib.sha256(f"{language}\0{category}\0{identity}".encode()).hexdigest()[
        :24
    ]


def provenance_c(
    record: dict[str, Any], language: str, files: dict[str, list[str]]
) -> dict[str, Any]:
    return {
        "category": "c",
        "language": language,
        "repo": record["repo"],
        "pair_group_id": record["pair_group_id"],
        "upstream_url": repository_url(record["repo"]),
        "license": record["license"],
        "parent_sha": record["parent_sha"],
        "child_sha": record["child_sha"],
        "pin_sha": record["pin_sha"],
        "changed_files": record["changed_files"],
        "changed_functions": record["changed_functions"],
        "intent": record["intent_evidence"],
        "label_source": "developer-intent",
        "behaviour_equivalent": False,
        "file_licenses": files,
    }


def repository_url(name: str) -> str:
    manifest = tomllib.loads((ROOT / "corpus" / "manifest.toml").read_text())
    return next(
        repo["url"] for repo in manifest["repositories"] if repo["name"] == name
    )


def extract_python(source: str, names: set[str]) -> list[str]:
    tree = ast.parse(source)
    return [
        ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]


def extract_changed(source: str, language: str, names: list[str]) -> str:
    """Extract matching function/method nodes, retaining only their source text."""
    if language == "python":
        return "\n\n".join(filter(None, extract_python(source, set(names))))
    from varde_code.parse import parse_source

    parsed = parse_source(language, source)
    wanted = set(names)
    nodes = []
    type_names = {
        "typescript": {"function_declaration", "method_definition"},
        "java": {"method_declaration", "constructor_declaration"},
        "csharp": {"method_declaration", "constructor_declaration"},
        "go": {"function_declaration", "method_declaration"},
        "rust": {"function_item"},
        "cpp": {"function_definition"},
    }

    def visit(node: Any) -> None:
        if node.type in type_names[language]:
            name_node = node.child_by_field_name("name")
            if name_node is None and language == "cpp":
                decl = node.child_by_field_name("declarator")
                while decl is not None:
                    name_node = decl.child_by_field_name("declarator")
                    if name_node is not None and name_node.type == "identifier":
                        break
                    decl = name_node
            if (
                name_node is not None
                and name_node.text.decode(errors="replace") in wanted
            ):
                nodes.append(node)
        for child in node.named_children:
            visit(child)

    visit(parsed.root)
    data = source.encode()
    return "\n\n".join(
        data[n.start_byte : n.end_byte].decode(errors="replace") for n in nodes
    )


def source_at(repo: Path, sha: str, filename: str) -> str:
    result = subprocess.run(  # noqa: S603 - Reads a pinned source revision using controlled git arguments.
        ["git", "-C", str(repo), "show", f"{sha}:{filename}"],  # noqa: S607 - Uses the system git executable from PATH.
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"cannot read {sha}:{filename} from {repo}")
    return result.stdout.decode("utf-8", errors="replace")


def changed_sources(
    record: dict[str, Any], repo: Path, language: str
) -> tuple[str, str]:
    before_parts, after_parts = [], []
    for filename in record["changed_files"]:
        before = source_at(repo, record["parent_sha"], filename)
        after = source_at(repo, record["child_sha"], filename)
        before_functions = extract_changed(
            before, language, record["changed_functions"]
        )
        after_functions = extract_changed(after, language, record["changed_functions"])
        header = license_header(before) or spdx_header(language, record["license"])
        before_parts.append(
            f"{header}\n\n{before_functions}" if header else before_functions
        )
        after_parts.append(
            f"{header}\n\n{after_functions}" if header else after_functions
        )
    before, after = (
        "\n\n".join(filter(None, before_parts)),
        "\n\n".join(filter(None, after_parts)),
    )
    if not before or not after:
        raise ValueError(
            f"could not extract changed functions from {record['child_sha']}"
        )
    return before, after


def spdx_header(language: str, license_name: str) -> str:
    prefix = "#" if language == "python" else "//"
    return f"{prefix} SPDX-License-Identifier: {license_name}"


def license_header(source: str) -> str:
    """Keep leading copyright/license comments with each extracted side."""
    lines = source.splitlines()
    header = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith(("#", "//", "/*", "*", "<!--")):
            header.append(line)
            continue
        break
    text = "\n".join(header).strip()
    return text if re.search(r"copyright|license|SPDX", text, re.IGNORECASE) else ""


def split_for(task_id: str, lock_path: Path) -> str:
    from splits import assignments

    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    mapping = payload.get("assignments", {})
    if task_id in mapping:
        return mapping[task_id]
    return assignments([task_id])[task_id]


def item_record(
    language: str, category: str, item_id: str, metadata: dict[str, Any], split: str
) -> dict[str, Any]:
    return {
        "id": item_id,
        "category": category,
        "language": language,
        "left": f"a{EXTENSIONS[language]}",
        "right": f"b{EXTENSIONS[language]}",
        "split": split,
        **metadata,
    }


def place_item(
    item_dir: Path,
    split: str,
    item_id: str,
    output: Path,
    repo_root: Path,
    restricted: Path,
) -> Path:
    """Use place_item.py's destination/marker contract without its CLI side effects."""
    import place_item as place_module
    from place_item import place

    original_root = place_module.restricted_root
    place_module.restricted_root = lambda: restricted
    try:
        return place(item_dir, split, item_id, output, repo_root=repo_root)
    finally:
        place_module.restricted_root = original_root


@dataclass(frozen=True)
class PairOutput:
    language: str
    category: str
    item_id: str
    left: str
    right: str
    metadata: dict[str, Any]
    split: str


def write_and_place(paths: AssemblyPaths, output: PairOutput) -> None:
    pair = item_record(
        output.language,
        output.category,
        output.item_id,
        output.metadata,
        output.split,
    )
    with tempfile.TemporaryDirectory(prefix="varde-cd-item-") as temporary:
        item = Path(temporary) / output.item_id
        item.mkdir()
        (item / f"a{EXTENSIONS[output.language]}").write_text(
            output.left, encoding="utf-8"
        )
        (item / f"b{EXTENSIONS[output.language]}").write_text(
            output.right, encoding="utf-8"
        )
        (item / "pair.json").write_text(
            json.dumps(pair, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        place_item(
            item,
            output.split,
            output.item_id,
            paths.output / output.language / output.category,
            REPO_ROOT,
            paths.restricted,
        )


@dataclass(frozen=True)
class AssemblyPaths:
    mined: Path
    mutation_inputs: Path
    mutation_outputs: Path
    output: Path
    splits: Path
    repo_cache: Path
    restricted: Path
    dry_run: bool


def assemble_language(language: str, paths: AssemblyPaths) -> tuple[int, int, int]:
    records = select_mined(load_mined(paths.mined, language), limit=10000)
    selected_d = select_mutation_outputs(paths.mutation_outputs / language)
    c_count = len(records)
    d_count = len(selected_d)
    if paths.dry_run:
        return (
            min(c_count, TARGET_C),
            d_count,
            int(c_count < TARGET_C or d_count < TARGET_D),
        )
    prepared_c = []
    for record in records:
        if len(prepared_c) == TARGET_C:
            break
        repo_path = paths.repo_cache / record["repo"].replace("/", "__")
        try:
            left, right = changed_sources(record, repo_path, language)
        except OSError, RuntimeError, ValueError, subprocess.SubprocessError:
            continue
        prepared_c.append((record, left, right))
    c_count = len(prepared_c)
    if c_count < TARGET_C:
        return c_count, d_count, 1
    for record, left, right in prepared_c:
        pair_id = opaque_id(language, "c", record["pair_group_id"])
        licenses = {
            f"{record['repo']}:{path}": record["license"]
            for path in record["changed_files"]
        }
        split = split_for(pair_id, paths.splits)
        write_and_place(
            paths,
            PairOutput(
                language,
                "c",
                pair_id,
                left,
                right,
                provenance_c(record, language, licenses),
                split,
            ),
        )
    for data in selected_d:
        pair_id = data["id"]
        split = split_for(pair_id, paths.splits)
        metadata = {
            k: v for k, v in data.items() if k not in {"source", "mutant", "id"}
        }
        metadata.update({"behaviour_equivalent": False, "label_source": "construction"})
        header = spdx_header(language, data["license"])
        write_and_place(
            paths,
            PairOutput(
                language,
                "d",
                pair_id,
                f"{header}\n{data['source']}",
                f"{header}\n{data['mutant']}",
                metadata,
                split,
            ),
        )
    return c_count, d_count, int(c_count < TARGET_C or d_count < TARGET_D)


def select_mutation_outputs(directory: Path) -> list[dict[str, Any]]:
    """Choose at most four parse-valid outputs with distinct operators first."""
    outputs = []
    if not directory.is_dir():
        return outputs
    for record_path in sorted(directory.glob("*.json")):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("status") != "mutated" or record.get("validation") not in {
            "compile",
            "parse",
        }:
            continue
        record["source"] = (directory / record["source_file"]).read_text(
            encoding="utf-8"
        )
        record["mutant"] = (directory / record["mutant_file"]).read_text(
            encoding="utf-8"
        )
        outputs.append(record)
    outputs.sort(key=lambda record: (record["operator"], record["id"]))
    chosen = []
    used_operators: set[str] = set()
    used_inputs: set[str] = set()
    used_sources: set[str] = set()
    for unique_input, unique_operator in ((True, True), (True, False), (False, False)):
        for record in outputs:
            source_file = record["provenance"]["file"]
            source_digest = hashlib.sha256(record["source"].encode()).hexdigest()
            if record in chosen:
                continue
            if unique_input and (
                source_file in used_inputs or source_digest in used_sources
            ):
                continue
            if unique_operator and record["operator"] in used_operators:
                continue
            chosen.append(record)
            used_operators.add(record["operator"])
            used_inputs.add(source_file)
            used_sources.add(source_digest)
            if len(chosen) == TARGET_D:
                return chosen
    return chosen


def _wrapped_source(language: str, source: str) -> str:
    if language == "java":
        return f"class MutationFixture {{\n{source}\n}}\n"
    if language == "csharp":
        return f"class MutationFixture\n{{\n{source}\n}}\n"
    return source


def _parse_mutant(language: str, source: str) -> bool:
    if language == "python":
        try:
            ast.parse(source)
        except SyntaxError:
            return False
        return True
    from varde_code.parse import parse_source

    try:
        return not parse_source(language, source).has_error()
    except RuntimeError, OSError, ValueError:
        return False


def generate_mutations(
    language: str, input_root: Path, output_root: Path
) -> tuple[int, dict[str, int]]:
    """Run all held-out operators offline and persist
    parse/compile-validated outputs.
    """
    from importlib import import_module

    input_dir = input_root / language
    provenance_path = input_dir / "provenance.json"
    if not provenance_path.is_file():
        return 0, {"inputs_missing": 1}
    module = import_module(f"mutations.{language}")
    metadata = json.loads(provenance_path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {"valid": 0, "skipped": 0, "errors": 0}
    output_dir = output_root / language
    output_dir.mkdir(parents=True, exist_ok=True)
    for input_record in metadata.get("inputs", []):
        filename = input_record["file"]
        if input_record.get("license") not in PERMISSIVE:
            continue
        original = (input_dir / filename).read_text(encoding="utf-8")
        source = _wrapped_source(language, original)
        for operator in HELD_OUT:
            if operator not in module.OPERATORS:
                continue
            item_id = opaque_id(language, "d", f"{filename}:{operator}")
            try:
                mutation, validation = _run_operator(
                    module, language, operator, source, item_id
                )
            except RuntimeError, SyntaxError, ValueError:
                counts["errors"] += 1
                continue
            if mutation.skipped or mutation.source == source:
                counts["skipped"] += 1
                continue
            if not _parse_mutant(language, mutation.source):
                counts["errors"] += 1
                continue
            _write_mutant(
                output_dir,
                item_id,
                source,
                mutation,
                validation,
                input_record,
            )
            counts["valid"] += 1
    return counts["valid"], counts


def _run_operator(
    module: Any, language: str, operator: str, source: str, item_id: str
) -> tuple[Any, str]:
    """Keep compiler-valid results; retry parser-valid fragments with local
    compiler context absent.
    """
    try:
        result = module.mutate(operator, source, item_id)
    except (RuntimeError, SyntaxError, ValueError) as error:
        if "produced invalid" not in str(error):
            raise
    else:
        if not result.skipped and result.source != source:
            return result, "compile"
        if result.skipped and result.metadata.skip_reason != "input does not compile":
            raise ValueError(result.metadata.skip_reason or "operator skipped")
    validator_name = {
        "java": "_valid_java",
        "csharp": "_valid_csharp",
        "go": "_valid_go",
        "rust": "_valid_rust",
        "cpp": "_valid_cpp",
    }.get(language)
    if validator_name is None:
        raise ValueError(f"{operator} did not produce a compiler-valid result")
    operator_module = module.operators
    validator = getattr(operator_module, validator_name)
    setattr(
        operator_module,
        validator_name,
        lambda candidate: _parse_mutant(language, candidate),
    )
    try:
        result = module.mutate(operator, source, item_id)
    finally:
        setattr(operator_module, validator_name, validator)
    if (
        result.skipped
        or result.source == source
        or not _parse_mutant(language, result.source)
    ):
        raise ValueError(
            result.metadata.skip_reason
            or "operator did not produce a parse-valid mutation"
        )
    return result, "parse"


def _write_mutant(
    directory: Path,
    item_id: str,
    source: str,
    mutation: Any,
    validation: str,
    provenance: dict[str, Any],
) -> None:
    extension = Path(provenance["file"]).suffix
    source_name, mutant_name = f"{item_id}-a{extension}", f"{item_id}-b{extension}"
    (directory / source_name).write_text(source, encoding="utf-8")
    (directory / mutant_name).write_text(mutation.source, encoding="utf-8")
    record = {
        "id": item_id,
        "operator": mutation.metadata.operator,
        "expected_direction": mutation.metadata.expected_direction,
        "seed": mutation.metadata.seed,
        "status": mutation.metadata.status,
        "validation": validation,
        "source_file": source_name,
        "mutant_file": mutant_name,
        "license": provenance["license"],
        "provenance": provenance,
    }
    (directory / f"{item_id}.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--generate-mutations",
        action="store_true",
        help=(
            "run every held-out operator over the local mutation inputs, "
            "writing under --mutation-outputs"
        ),
    )
    parser.add_argument("--out", type=Path, default=ROOT / "items" / "_cd")
    parser.add_argument("--mined", type=Path, default=ROOT / "pairs" / "mined")
    parser.add_argument(
        "--mutation-inputs",
        type=Path,
        default=ROOT / "corpus" / "verified" / "mutation-inputs",
    )
    parser.add_argument(
        "--mutation-outputs",
        type=Path,
        default=Path(
            os.environ.get("VARDE_BENCH_CACHE", Path.home() / ".cache" / "varde-bench")
        )
        / "mutation-outputs",
    )
    parser.add_argument(
        "--repo-cache",
        type=Path,
        default=Path(
            os.environ.get("VARDE_BENCH_CACHE", Path.home() / ".cache" / "varde-bench")
        ),
    )
    parser.add_argument(
        "--restricted",
        type=Path,
        default=Path(
            os.environ.get(
                "VARDE_GOLDEN_RESTRICTED",
                "/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-17-quality-score-build/qs-golden-corpus/notes/restricted/golden",
            )
        ),
    )
    parser.add_argument("--splits", type=Path, default=ROOT / "tools" / "splits.lock")
    args = parser.parse_args(argv)
    languages = LANGUAGES if args.lang == "all" else (args.lang,)
    if any(language not in LANGUAGES for language in languages):
        parser.error(f"--lang must be one of {', '.join(LANGUAGES)} or all")
    if args.generate_mutations:
        print("language  valid  skipped  errors")
        for language in languages:
            valid, counts = generate_mutations(
                language, args.mutation_inputs, args.mutation_outputs
            )
            print(
                f"{language:<10} {valid:<6} {counts.get('skipped', 0):<8} "
                f"{counts.get('errors', 0)}"
            )
        return 0
    incomplete = []
    print("language  c  d")
    for language in languages:
        paths = AssemblyPaths(
            args.mined,
            args.mutation_inputs,
            args.mutation_outputs,
            args.out,
            args.splits,
            args.repo_cache,
            args.restricted,
            args.dry_run,
        )
        c_count, d_count, missing = assemble_language(language, paths)
        print(f"{language:<10} {c_count}  {d_count}")
        if missing:
            incomplete.append(language)
    if incomplete:
        print("languages lacking data: " + ", ".join(incomplete))
    return int(bool(incomplete))


if __name__ == "__main__":
    raise SystemExit(main())
