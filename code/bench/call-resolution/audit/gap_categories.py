"""Classify missed call-resolution sites into ranked gap categories.

A site is *missed* when its ground truth is an in-repo target, its call class
counts toward recall, and the measured edge is not that target. The pure part of
this module turns one site's evidence into a category name and ranks categories
by recall gain. ``evidence.py``-style gathering lives in ``gather_evidence``
below the pure section and is the only code that reads repositories.

Categories (``existing-facts`` can be fixed in ``quality_resolve`` with facts
that exist today; ``needs-new-facts`` needs a facts-contract change):

- module-level-call: the call has no enclosing function, so no edge is exported.
- site-not-extracted: the facts hold no call site at the labeled line.
- wrong-target: resolved, but to another function (a precision error).
- owner: ambiguous candidates, or a receiver naming the owning type.
- overload: ambiguous between same-name functions of one owner and arity.
- inheritance: the method lives on a base type of the caller's owner.
- static-import: unqualified call bound by ``using static``.
- export-star: the import reaches the target through ``export * from``.
- __all__: the import reaches the target through a package re-export.
- package: the import reaches the target through a barrel or package module.
- unresolved-import: the name is imported but its module is not resolved
  (includes JavaScript files, which have no import hook of their own).
- closure: the target is declared inside another function.
- anonymous-target: the target is an unnamed function (arrow, expression).
- namespace: C# call to a type in the same or an imported namespace.
- variable-receiver: member call on a variable whose type is not known.
- arity: the only candidate has a different parameter count than the call.
- other: none of the above.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

EXISTING = "existing-facts"
NEW = "needs-new-facts"

# category -> (tag, fix owner)
CATEGORIES: dict[str, tuple[str, str]] = {
    "module-level-call": (EXISTING, "audit adapter / facts consumer"),
    "site-not-extracted": (EXISTING, "facts extractor (quality_pass/langs)"),
    "wrong-target": (EXISTING, "quality_resolve core"),
    "owner": (EXISTING, "quality_resolve core"),
    "overload": (NEW, "facts (parameter types) + quality_resolve core"),
    "inheritance": (NEW, "facts (type base lists) + quality_resolve core"),
    "static-import": (NEW, "facts (import static flag) + csharp module"),
    "export-star": (NEW, "facts (export * from) + typescript module"),
    "__all__": (EXISTING, "python module"),
    "package": (EXISTING, "language module + core"),
    "unresolved-import": (EXISTING, "language import hook"),
    "closure": (EXISTING, "quality_resolve core (local pass owner filter)"),
    "anonymous-target": (EXISTING, "facts extractor (function names)"),
    "namespace": (EXISTING, "csharp module + core"),
    "variable-receiver": (EXISTING, "quality_resolve core (type inference bound, D14)"),
    "arity": (EXISTING, "quality_resolve core"),
    "other": (EXISTING, "to be triaged"),
}
EXCLUDED_RECALL_CLASSES = {"dynamic", "higher_order"}
SENTINELS = {"external", "unknown"}
SELF_RECEIVERS = {"self", "this", "cls", "base", "super", "super()"}


# --- pure section -----------------------------------------------------------


def is_missed(record: Mapping[str, object]) -> bool:
    """Return whether the record counts against recall and was not hit."""
    truth = record.get("ground_truth")
    if not isinstance(truth, str) or truth in SENTINELS:
        return False
    if record.get("call_class") in EXCLUDED_RECALL_CLASSES:
        return False
    hit = (
        record.get("measured_status") == "resolved"
        and record.get("measured_edge") == truth
    )
    return not hit


def target_owner(target_id: str) -> str:
    """Return the owner part of a ground-truth id's qualified name."""
    qualified = (
        target_id.partition("::")[2].rpartition("@")[0] or target_id.partition("::")[2]
    )
    qualified = qualified.split("(", 1)[0]
    return qualified.rpartition(".")[0]


def classify_miss(ev: Mapping[str, object]) -> str:
    """Return the gap category of one missed site from its evidence."""
    status = ev.get("status")
    if status == "resolved":
        return "wrong-target"
    if not ev.get("has_edge") and not ev.get("caller_present", True):
        return "module-level-call"
    if not ev.get("has_edge") and not ev.get("call_site_found", True):
        return "site-not-extracted"
    if status == "ambiguous":
        return "overload" if ev.get("target_candidates", 0) > 1 else "owner"
    return _classify_unresolved(ev)


def _classify_unresolved(ev: Mapping[str, object]) -> str:
    """Return the first category whose rule matches; rules are ordered by cause."""
    receiver = _root(ev.get("receiver"))
    for category, matches in _RULES:
        if matches(ev, receiver):
            return category
    return "other"


def _is_import_unresolved(ev: Mapping[str, object], _receiver: str) -> bool:
    return bool(ev.get("imported") and not ev.get("import_module_resolved"))


def _is_variable_receiver(ev: Mapping[str, object], receiver: str) -> bool:
    return bool((receiver and receiver not in SELF_RECEIVERS) or ev.get("dotted"))


def _is_csharp_namespace_call(ev: Mapping[str, object], receiver: str) -> bool:
    unqualified = not receiver and not ev.get("dotted")
    return ev.get("language") == "csharp" and unqualified and not ev.get("same_file")


def _root(receiver: object) -> str:
    if not isinstance(receiver, str):
        return ""
    return re.split(r"[.\[(]", receiver.strip(), maxsplit=1)[0]


def _is_inherited(ev: Mapping[str, object], receiver: str) -> bool:
    owner = ev.get("target_owner")
    caller_owner = ev.get("caller_owner")
    if not owner or not caller_owner or _last(owner) == _last(caller_owner):
        return False
    implicit_or_self = not receiver or receiver in SELF_RECEIVERS
    return implicit_or_self and ev.get("call_class") != "constructor"


def _is_inherited_by_file(ev: Mapping[str, object], receiver: str) -> bool:
    """Self/this call whose target sits in another file (no owner in the id)."""
    return (
        receiver in SELF_RECEIVERS
        and not ev.get("same_file")
        and not ev.get("target_owner")
        and not ev.get("imported")
    )


def _last(qualified: object) -> str:
    return re.split(r"[.:]+", str(qualified))[-1]


def _receiver_names_owner(ev: Mapping[str, object], receiver: str) -> bool:
    owner = ev.get("target_owner")
    return bool(owner and receiver and receiver == _last(owner))


def _is_arity_mismatch(ev: Mapping[str, object]) -> bool:
    arity = ev.get("arity")
    counts = ev.get("target_param_counts")
    return isinstance(arity, int) and bool(counts) and arity not in counts


_RULES = (
    (
        "unresolved-import",
        lambda ev, _r: bool(ev.get("imported") and ev.get("hook_missing")),
    ),
    ("anonymous-target", lambda ev, _r: bool(ev.get("target_anonymous"))),
    ("closure", lambda ev, _r: bool(ev.get("target_nested"))),
    (
        "inheritance",
        lambda ev, r: _is_inherited(ev, r) or _is_inherited_by_file(ev, r),
    ),
    ("static-import", lambda ev, _r: bool(ev.get("static_import"))),
    ("export-star", lambda ev, _r: ev.get("reexport") == "star"),
    ("__all__", lambda ev, _r: ev.get("reexport") == "all"),
    ("package", lambda ev, _r: ev.get("reexport") == "named"),
    ("unresolved-import", _is_import_unresolved),
    ("arity", lambda ev, _r: _is_arity_mismatch(ev)),
    ("owner", _receiver_names_owner),
    ("namespace", _is_csharp_namespace_call),
    ("variable-receiver", _is_variable_receiver),
)


def classify_all(
    evidence: Iterable[Mapping[str, object]],
) -> dict[str, Counter[str]]:
    """Count missed sites per language and category."""
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for ev in evidence:
        counts[str(ev["language"])][classify_miss(ev)] += 1
    return counts


def gain_by_category(
    all_records: Sequence[Mapping[str, object]],
    missed: Sequence[tuple[Mapping[str, object], str]],
) -> dict[str, float]:
    """Recall gain per category for one language, from all records and the misses."""
    in_repo = Counter(
        str(r["call_class"])
        for r in all_records
        if isinstance(r.get("ground_truth"), str)
        and r["ground_truth"] not in SENTINELS
        and r["call_class"] not in EXCLUDED_RECALL_CLASSES
    )
    classes = len(in_repo)
    gains: Counter[str] = Counter()
    for record, category in missed:
        gains[category] += 1 / (in_repo[str(record["call_class"])] * classes)
    return dict(gains)


def rank_categories(
    counts: Mapping[str, int], gains: Mapping[str, float]
) -> list[tuple[str, int, float]]:
    """Return (category, missed sites, recall gain) ordered by gain, then count."""
    rows = [(name, count, gains.get(name, 0.0)) for name, count in counts.items()]
    return sorted(rows, key=lambda row: (-row[2], -row[1], row[0]))


# --- evidence gathering (reads repositories) --------------------------------

_TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".d.ts")


def resolve_module(
    language: str, call_file: str, module: str, files: set[str]
) -> str | None:
    """Return the repo file a module specifier names, or None."""
    if language == "python":
        return _resolve_python(call_file, module, files)
    if language == "typescript":
        return _resolve_typescript(call_file, module, files)
    return None


def _resolve_python(call_file: str, module: str, files: set[str]) -> str | None:
    dots = len(module) - len(module.lstrip("."))
    parts = [p for p in module.lstrip(".").split(".") if p]
    bases: list[list[str]] = []
    if dots:
        base = call_file.split("/")[:-1]
        bases.append(base[: len(base) - (dots - 1)] if dots > 1 else base)
    else:
        bases.extend(_source_roots(call_file))
    for base in bases:
        stem = "/".join([*base, *parts])
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            if candidate in files:
                return candidate
    return None


def _source_roots(call_file: str) -> list[list[str]]:
    segments = call_file.split("/")[:-1]
    return [segments[:depth] for depth in range(len(segments) + 1)]


def _resolve_typescript(call_file: str, module: str, files: set[str]) -> str | None:
    if not module.startswith("."):
        return None
    stem = _normalize("/".join([*call_file.split("/")[:-1], module]))
    trimmed = re.sub(r"\.(c|m)?jsx?$", "", stem)
    for base in dict.fromkeys((stem, trimmed)):
        for suffix in ("", *_TS_EXTENSIONS):
            if f"{base}{suffix}" in files:
                return f"{base}{suffix}"
        for suffix in _TS_EXTENSIONS:
            if f"{base}/index{suffix}" in files:
                return f"{base}/index{suffix}"
    return None


def _normalize(path: str) -> str:
    out: list[str] = []
    for part in path.split("/"):
        if part == "..":
            if out:
                out.pop()
        elif part not in ("", "."):
            out.append(part)
    return "/".join(out)


def reexport_kind(language: str, via_text: str, name: str) -> str | None:
    """Classify how the file an import resolves to forwards ``name``."""
    if language == "python":
        if re.search(rf"__all__[^\n]*['\"]{re.escape(name)}['\"]", via_text) or (
            "__all__" in via_text
            and re.search(rf"['\"]{re.escape(name)}['\"]", via_text)
        ):
            return "all"
        return "named"
    if re.search(r"export\s*\*\s*(as\s+\w+\s*)?from", via_text):
        return "star"
    return "named"


def gather_evidence(
    record: Mapping[str, object],
    *,
    repo_root: Path,
    files: set[str],
    facts_of,
    edge_of,
) -> dict[str, object]:
    """Collect the evidence ``classify_miss`` needs for one missed record."""
    language = str(record["language"])
    call_file = str(record["file"])
    name = str(record.get("call_name") or "")
    line = int(record["line"])
    truth = str(record["ground_truth"])
    target_file = truth.partition("::")[0]
    facts = facts_of(call_file)
    site = next(
        (
            s
            for s in facts.get("call_sites", ())
            if s.get("line") == line and s.get("name") == name
        ),
        None,
    )
    edge = edge_of(call_file, line, name)
    caller = site.get("caller") if site else None
    caller_record = next(
        (f for f in facts.get("functions", ()) if f.get("id") == caller), None
    )
    ev: dict[str, object] = {
        "language": language,
        "call_class": record["call_class"],
        "status": record["measured_status"],
        "has_edge": edge is not None,
        "call_site_found": site is not None,
        "caller_present": bool(caller) if site else True,
        "receiver": (site or {}).get("receiver_text"),
        "arity": (site or {}).get("arity"),
        "same_file": call_file == target_file,
        "target_owner": target_owner(truth),
        "caller_owner": (caller_record or {}).get("owner"),
        "dotted": _is_dotted_call(repo_root / call_file, line, name),
        "file_language": _language_of(call_file),
        "hook_missing": _hook_missing(call_file),
        "edge_kind": (edge or {}).get("kind"),
        "edge_pass": (edge or {}).get("pass"),
    }
    ev.update(
        _import_evidence((language, call_file, name), ev, facts, files, repo_root)
    )
    ev.update(_target_evidence(language, target_file, truth, facts_of))
    return ev


def _is_dotted_call(path: Path, line: int, name: str) -> bool:
    """Whether the call is written ``<expression>.name(``."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()[line - 1]
    except OSError, IndexError:
        return False
    return re.search(rf"\.\s*{re.escape(name)}\s*[<(]", text) is not None


def _language_of(path: str) -> str | None:
    from varde_code.parse import language_for_path

    return language_for_path(Path(path))


def _hook_missing(path: str) -> bool:
    import importlib.util

    language = _language_of(path)
    name = f"varde_code.quality_resolve.langs.{language}"
    return language is None or importlib.util.find_spec(name) is None


def _import_evidence(site, ev, facts, files, repo_root):
    language, call_file, name = site
    root = _root(ev.get("receiver")) or name
    word = re.compile(rf"\b{re.escape(root)}\b")
    bound = [s for s in facts.get("imports", ()) if word.search(s.get("text", ""))]
    out: dict[str, object] = {
        "imported": bool(bound),
        "import_module_resolved": False,
        "static_import": any("using static" in s.get("text", "") for s in bound),
    }
    for spec in bound:
        resolved = resolve_module(language, call_file, spec["module"], files)
        if resolved is None:
            continue
        out["import_module_resolved"] = True
        out["import_file"] = resolved
        via_text = (repo_root / resolved).read_text(encoding="utf-8", errors="replace")
        if resolved != call_file and not _file_defines(via_text, language, root):
            out["reexport"] = reexport_kind(language, via_text, root)
        break
    return out


def _file_defines(text: str, language: str, name: str) -> bool:
    pattern = (
        rf"^\s*(async\s+)?(def|class)\s+{re.escape(name)}\b"
        if language == "python"
        else rf"\b(function|class|const|let|var|interface|enum|type)\s+"
        rf"{re.escape(name)}\b"
    )
    return re.search(pattern, text, re.MULTILINE) is not None


def _declared_name(qualified: str) -> str:
    """Return the last name of a qualified id, without signature or generics."""
    head = qualified.rpartition("@")[0] or qualified
    head = head.split("(", 1)[0]
    head = re.sub(r"<[^<>]*>", "", re.sub(r"<[^<>]*>", "", head))
    return re.split(r"[.:]", head)[-1]


def _target_evidence(language, target_file, truth, facts_of):
    facts = facts_of(target_file)
    qualified = truth.partition("::")[2]
    line = qualified.rpartition("@")[2]
    declared = _declared_name(qualified)
    if declared == "<anonymous>":
        return {"target_anonymous": True}
    owner_last = _last(target_owner(truth).split("<", 1)[0])
    candidates = [
        f
        for f in facts.get("functions", ())
        if f.get("name") == declared
        and (
            f.get("line") == int(line)
            if line.isdigit()
            else _last(str(f.get("owner") or "")) == owner_last
        )
    ]
    if not candidates:
        return {}
    counts = sorted({_param_count(language, declared, f) for f in candidates})
    out: dict[str, object] = {
        "target_param_counts": counts,
        "target_candidates": len(candidates),
    }
    if len(candidates) == 1:
        out["target_nested"] = _is_nested(candidates[0], facts.get("functions", ()))
    return out


def _param_count(language, declared, function):
    params = function.get("params")
    if language == "python" and declared == "__init__" and isinstance(params, int):
        return params - 1
    return params


def _is_nested(function: Mapping[str, object], functions: Iterable[Mapping]) -> bool:
    line = function.get("line")
    return any(
        other is not function
        and isinstance(other.get("line"), int)
        and isinstance(other.get("end_line"), int)
        and other["line"] < line <= other["end_line"]
        for other in functions
    )


# --- driver ------------------------------------------------------------------

IN_SCOPE = ("python", "typescript", "csharp")


def _load_records(records_dir: Path, language: str) -> list[dict]:
    path = records_dir / f"{language}-progress-records.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _repo_files(repo_root: Path) -> set[str]:
    import subprocess

    listing = subprocess.run(  # noqa: S603 - fixed git argv, path from the caller
        ["git", "-C", str(repo_root), "ls-files"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return set(listing.splitlines())


def _facts_reader(repo_root: Path):
    from varde_code.parse import language_for_path
    from varde_code.quality_pass.facts import extract_facts
    from varde_code.quality_pass.pass_.extract import import_specs

    cache: dict[str, dict] = {}

    def facts_of(path: str) -> dict:
        if path not in cache:
            absolute = repo_root / path
            language = language_for_path(absolute)
            if language is None:
                cache[path] = {}
                return cache[path]
            try:
                raw = absolute.read_bytes()
                facts = extract_facts(raw, language, path)
                text = raw.decode("utf-8-sig", errors="replace")
                facts["imports"] = import_specs(str(absolute), text, language)
            except OSError, ValueError, RuntimeError:
                facts = {}
            cache[path] = facts
        return cache[path]

    return facts_of


def _edge_reader(edge_cache: Path, repo: str):
    stem = repo.replace("/", "__")
    path = next(edge_cache.glob(f"{stem}__*.jsonl"))
    by_site: dict[tuple[str, int, str], dict] = {}
    for line in path.read_text().splitlines():
        edge = json.loads(line)
        by_site[(edge["file"], edge["site_line"], edge["name"])] = edge
    return lambda file, line, name: by_site.get((file, line, name))


def _lazy_name_counts(files: set[str], facts_of):
    """Return a function giving how many functions each name has across the repo."""
    cached: dict[str, int] = {}

    def counts_of() -> dict[str, int]:
        if not cached:
            for path in sorted(files):
                if not path.endswith(".cs"):
                    continue
                for function in facts_of(path).get("functions", ()):
                    cached[function["name"]] = cached.get(function["name"], 0) + 1
            cached.setdefault("", 0)
        return cached

    return counts_of


def collect_evidence(
    language: str, records_dir: Path, repo_cache: Path, edge_cache: Path
):
    """Yield (record, evidence) for each missed site of a language."""
    records = _load_records(records_dir, language)
    for repo in sorted({r["repo"] for r in records}):
        root = repo_cache / repo.replace("/", "__")
        files, facts_of = _repo_files(root), _facts_reader(root)
        edge_of = _edge_reader(edge_cache, repo)
        counts_of = _lazy_name_counts(files, facts_of)
        for record in records:
            if record["repo"] != repo or not is_missed(record):
                continue
            ev = gather_evidence(
                record, repo_root=root, files=files, facts_of=facts_of, edge_of=edge_of
            )
            if language == "csharp" and classify_miss(ev) == "variable-receiver":
                counts = counts_of()
                ev["name_count_in_repo"] = counts.get(str(record.get("call_name")), 0)
            yield record, ev


def main(argv: list[str]) -> int:
    """Usage: gap_categories.py <records-dir> <repo-cache> <edge-cache> <out-dir>."""
    if len(argv) != 5:
        print(main.__doc__, file=sys.stderr)
        return 2
    records_dir, repo_cache, edge_cache, out_dir = (Path(a) for a in argv[1:])
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for language in IN_SCOPE:
        pairs = list(collect_evidence(language, records_dir, repo_cache, edge_cache))
        with (out_dir / f"{language}-evidence.jsonl").open("w") as stream:
            for record, ev in pairs:
                row = {"category": classify_miss(ev), "ev": ev, "site": _site(record)}
                stream.write(json.dumps(row, sort_keys=True) + "\n")
        lines.extend(_table(language, _load_records(records_dir, language), pairs))
    (out_dir / "baseline-tables.md").write_text("\n".join(lines) + "\n")
    return 0


def _site(record: Mapping[str, object]) -> dict:
    keys = ("repo", "file", "line", "call_name", "call_class", "ground_truth")
    return {key: record.get(key) for key in keys}


def _table(language, records, pairs) -> list[str]:
    missed = [(record, classify_miss(ev)) for record, ev in pairs]
    counts = Counter(category for _, category in missed)
    unique = sum(
        1
        for (_, category), (_, ev) in zip(missed, pairs, strict=True)
        if category == "variable-receiver" and ev.get("name_count_in_repo") == 1
    )
    gains = gain_by_category(records, missed)
    rows = [f"### {language}: {len(missed)} missed sites", ""]
    rows += [
        "| Rank | Category | Missed | Recall gain | Tag | Fix owner |",
        "| ---: | --- | ---: | ---: | --- | --- |",
    ]
    for rank, (name, count, gain) in enumerate(rank_categories(counts, gains), 1):
        tag, owner = CATEGORIES[name]
        rows.append(f"| {rank} | {name} | {count} | {gain:.4f} | {tag} | {owner} |")
    if language == "csharp":
        rows += [
            "",
            f"variable-receiver sites with a repo-unique method name: {unique}",
        ]
    return [*rows, ""]


if __name__ == "__main__":
    sys.exit(main(sys.argv))
