"""Package the agreed baseline data into the ``varde-code`` package data.

    uv run python baseline_package.py --check    # fail on any hash drift
    uv run python baseline_package.py --write    # copy sources, rebuild corpus.json

No model call. Sources: ``code/bench/quality-corpus/baseline/{problems,agreed}/**``
(without ``reference-stub``, ``README.md``, ``toolchains.toml``), the shipped
``calibration/cal-1.toml``, and ``corpus.json`` ({language: {measure: sorted
values}}), derived from the verified-corpus dev-split functions that
``region_presets`` uses for the default region. The packaged ``corpus.json``
feeds the q50/q99 clamp of the baseline page. When the corpus cache is absent,
``--check`` verifies that ``corpus.json`` parses but cannot rebuild it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO = HERE.parents[3]
BASELINE = REPO / "code/bench/quality-corpus/baseline"
QUALITY = REPO / "code/src/varde_code/quality_score"
CAL_SOURCE = QUALITY / "calibration/cal-1.toml"
DATA = QUALITY / "baseline_data"
TREES = ("problems", "agreed")
SKIPPED_NAMES = {"reference-stub", "README.md", "toolchains.toml", "__pycache__"}
CORPUS_NAME = "corpus.json"


def source_files(baseline: Path = BASELINE, cal: Path = CAL_SOURCE) -> dict[str, Path]:
    """Packaged relative path -> source file, for everything except corpus.json."""
    found = {"cal-1.toml": cal}
    for tree in TREES:
        for path in sorted((baseline / tree).rglob("*")):
            relative = path.relative_to(baseline)
            if path.is_file() and not SKIPPED_NAMES & set(relative.parts):
                found[relative.as_posix()] = path
    return found


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_text(corpus: Mapping[str, Mapping[str, list[int]]]) -> str:
    sorted_corpus = {
        language: {m: sorted(values) for m, values in sorted(measures.items())}
        for language, measures in sorted(corpus.items())
    }
    return json.dumps(sorted_corpus, separators=(",", ":")) + "\n"


def drift(sources: Mapping[str, Path], data: Path) -> list[str]:
    """Problems between the sources and the packaged tree (corpus.json excluded)."""
    problems = []
    for relative, source in sources.items():
        packaged = data / relative
        if not packaged.is_file():
            problems.append(f"missing {relative}")
        elif sha256(packaged) != sha256(source):
            problems.append(f"differs {relative}")
    for packaged in sorted(p for p in data.rglob("*") if p.is_file()):
        relative = packaged.relative_to(data).as_posix()
        if relative not in sources and relative != CORPUS_NAME:
            problems.append(f"no source for {relative}")
    return problems


def corpus_problems(data: Path, rebuilt: str | None) -> list[str]:
    path = data / CORPUS_NAME
    if not path.is_file():
        return [f"missing {CORPUS_NAME}"]
    if rebuilt is None:
        try:
            json.loads(path.read_text())
        except ValueError:
            return [f"{CORPUS_NAME} is not valid JSON"]
        return []
    return [] if path.read_text() == rebuilt else [f"differs {CORPUS_NAME} (rebuild)"]


def build_corpus(cache: Path) -> str | None:
    """Rebuild corpus.json from the verified-corpus cache; None if no cache."""
    if not cache.is_dir():
        return None
    import region_presets as rp

    corpus = {
        language: rp.corpus_inputs(language, cache, rp.PER_REPO).corpus
        for language in rp.LANGUAGES
    }
    return corpus_text(corpus)


def write(sources: Mapping[str, Path], data: Path, corpus: str) -> None:
    if data.exists():
        shutil.rmtree(data)
    for relative, source in sources.items():
        target = data / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (data / CORPUS_NAME).write_text(corpus)


def main(argv: list[str] | None = None) -> int:
    import region_presets as rp

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--cache", type=Path, default=rp.USER_CACHE)
    args = parser.parse_args(argv)
    sources = source_files()
    rebuilt = build_corpus(args.cache)
    if args.write:
        if rebuilt is None:
            print(f"no corpus cache at {args.cache}", file=sys.stderr)
            return 1
        write(sources, DATA, rebuilt)
        print(f"wrote {len(sources) + 1} files to {DATA}")
        return 0
    problems = drift(sources, DATA) + corpus_problems(DATA, rebuilt)
    for problem in problems:
        print(f"check FAIL: {problem}", file=sys.stderr)
    note = "" if rebuilt is not None else " (corpus not rebuilt: no cache)"
    print(f"check: {'FAIL' if problems else 'ok'} {len(sources) + 1} files{note}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
