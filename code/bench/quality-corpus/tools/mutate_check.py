"""Check that a hand-written mutant spec is killed by an item's behaviour test.

Each mutant is a textual patch. A killed mutant makes the shared behaviour test
fail; a survivor still passes, so the test does not constrain that behaviour.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from behaviour_runner import available_commands, workspace_commands
from item_spec_languages import EXTENSIONS

KILLED = "killed"
SURVIVED = "survived"
BROKEN = "broken"
UNAPPLIED = "unapplied"
EQUIVALENT = "equivalent"
STATUSES = (KILLED, SURVIVED, BROKEN, UNAPPLIED, EQUIVALENT)
LANGUAGE_BY_SUFFIX = {suffix: name for name, suffix in EXTENSIONS.items()}
LANGUAGE_BY_SUFFIX[".cc"] = "cpp"


class SpecError(Exception):
    """The item, variant, or mutants spec cannot be used."""


@dataclass(frozen=True)
class Mutant:
    """One textual patch and, when deliberate, why it cannot change behaviour."""

    id: str
    description: str
    find: str
    replace: str
    equivalent: bool = False
    reason: str = ""
    allow_broken: bool = False


@dataclass(frozen=True)
class Result:
    """The outcome of one mutant."""

    id: str
    description: str
    status: str
    detail: str = ""
    allowed: bool = False


@dataclass(frozen=True)
class Run:
    """Everything a mutant needs to build and run the shared behaviour test."""

    item: Path
    variant: Path
    test: Path
    tools: list[str]
    language: str
    run_table: dict
    random_only: bool
    timeout: float


def mutant_from(entry: object, index: int) -> Mutant:
    """Validate one spec table into a mutant."""
    if not isinstance(entry, dict):
        raise SpecError(f"mutant {index} is not a table")
    fields: dict[str, str] = {}
    for name in ("id", "description", "find", "replace"):
        value = entry.get(name)
        if not isinstance(value, str) or not value:
            raise SpecError(f"mutant {index} needs a non-empty {name} string")
        fields[name] = value
    equivalent = entry.get("equivalent", False)
    allow_broken = entry.get("allow_broken", False)
    reason = entry.get("reason", "")
    if not isinstance(equivalent, bool) or not isinstance(allow_broken, bool):
        raise SpecError(
            f"mutant {fields['id']}: equivalent and allow_broken are booleans"
        )
    if not isinstance(reason, str):
        raise SpecError(f"mutant {fields['id']}: reason must be a string")
    if equivalent and not reason:
        raise SpecError(f"mutant {fields['id']}: an equivalent mutant needs a reason")
    return Mutant(
        **fields, equivalent=equivalent, reason=reason, allow_broken=allow_broken
    )


def load_mutants(path: Path) -> tuple[list[Mutant], dict]:
    """Read the mutant tables and the optional [run] table from a spec."""
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise SpecError(f"cannot read mutants spec {path}: {error}") from error
    entries = data.get("mutants")
    if not isinstance(entries, list) or not entries:
        raise SpecError("spec needs a [[mutants]] array with at least one entry")
    mutants = [mutant_from(entry, index) for index, entry in enumerate(entries)]
    ids = [mutant.id for mutant in mutants]
    if len(set(ids)) != len(ids):
        raise SpecError("mutant ids must be unique")
    return mutants, data.get("run", {})


def patched(text: str, mutant: Mutant) -> str | None:
    """Return the variant text with the mutant applied, or None if find is not
    unique.
    """
    return (
        text.replace(mutant.find, mutant.replace)
        if text.count(mutant.find) == 1
        else None
    )


def run_entry(run: Run) -> dict:
    """Return this language's [run] table, the random-loop-alone switch."""
    entry = run.run_table.get(run.language)
    if not isinstance(entry, dict):
        raise SpecError(
            f"spec declares no [run] {run.language} entry for --random-only"
        )
    return entry


def substitute(words: list[str], values: dict[str, str]) -> list[str]:
    """Replace {root}, {solution}, and {test} placeholders in a command."""
    for name, value in values.items():
        words = [word.replace(name, value) for word in words]
    return words


def random_only_for(
    run: Run, paths: dict[str, str]
) -> tuple[list[str] | None, dict[str, str]]:
    """Return the test command override and extra environment for a random-only run."""
    entry = run_entry(run)
    name = entry.get("env")
    words = entry.get("command")
    if isinstance(name, str) and words is None:
        return None, {name: "1"}
    if words is not None:
        if not isinstance(words, list) or not all(
            isinstance(word, str) for word in words
        ):
            raise SpecError("a [run] command must be a list of words")
        return substitute(words, paths), {}
    raise SpecError("a [run] entry needs an env name or a command list")


def last_line(result: subprocess.CompletedProcess) -> str:
    lines = (result.stderr or result.stdout).strip().splitlines()
    return lines[-1] if lines else f"exit {result.returncode}"


def executed(
    build: list[list[str]],
    command: list[str],
    work: Path,
    env: dict[str, str] | None,
    mutant: Mutant,
    timeout: float,
) -> Result:
    """Build the mutant, then run the behaviour test.

    A failed build means the mutant does not compile, so its kill would say
    nothing about the test; a failed test run has the same result either way.
    """
    build_failure = first_failure(build, work, env, timeout)
    if build_failure:
        return Result(
            mutant.id,
            mutant.description,
            BROKEN,
            build_failure,
            mutant.allow_broken,
        )
    test_failure = first_failure([command], work, env, timeout)
    status = KILLED if test_failure else SURVIVED
    return Result(mutant.id, mutant.description, status, test_failure or "")


def first_failure(
    commands: list[list[str]], work: Path, env: dict[str, str] | None, timeout: float
) -> str:
    """Return the output of the first failing command, or an empty string."""
    for command in commands:
        try:
            result = subprocess.run(  # noqa: S603 - Runs the configured compiler against generated mutation input.
                command,
                cwd=work,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return f"timed out after {timeout:g}s"
        if result.returncode:
            return last_line(result)
    return ""


def isolated_copy(run: Run, mutated: str, root: Path) -> Path:
    """Copy the item without its other versions and add the mutant as solution<ext>."""
    siblings = [
        path.name
        for path in run.item.iterdir()
        if path.suffix == run.variant.suffix and path.name != run.test.name
    ]
    work = root / "item"
    shutil.copytree(run.item, work, ignore=shutil.ignore_patterns(*siblings))
    (work / f"solution{run.variant.suffix}").write_text(mutated)
    return work


def run_mutant(run: Run, text: str, mutant: Mutant) -> Result:
    """Apply one mutant to a copy of the item and run the behaviour test against it."""
    mutated = patched(text, mutant)
    if mutated is None:
        detail = "find text does not occur exactly once"
        return Result(mutant.id, mutant.description, UNAPPLIED, detail)
    if mutant.equivalent:
        return Result(mutant.id, mutant.description, EQUIVALENT, mutant.reason)
    with tempfile.TemporaryDirectory(prefix="varde-mutate-") as temp:
        work = isolated_copy(run, mutated, Path(temp))
        solution = work / f"solution{run.variant.suffix}"
        test = work / run.test.name
        build, command = workspace_commands(work, solution, test, run.tools)
        env = None
        if run.random_only:
            paths = {
                "{root}": str(work),
                "{solution}": str(solution),
                "{test}": str(test),
            }
            override, extra = random_only_for(run, paths)
            command = override or command
            env = {**os.environ, **extra}
        return executed(build, command, work, env, mutant, run.timeout)


def prepare(args: argparse.Namespace) -> tuple[Run, list[Mutant]]:
    """Validate the item, variant, spec, and random-only switch up front."""
    if not args.item.is_dir():
        raise SpecError(f"item directory does not exist: {args.item}")
    tests = list(args.item.glob("behaviour_test.*"))
    if len(tests) != 1:
        raise SpecError(f"{args.item} needs exactly one behaviour_test.* file")
    variant = args.variant if args.variant.is_absolute() else args.item / args.variant
    if not variant.is_file():
        raise SpecError(f"variant does not exist: {variant}")
    tools = available_commands(variant.suffix)
    if tools is None:
        raise SpecError(f"missing toolchain for {variant.suffix}")
    language = LANGUAGE_BY_SUFFIX.get(variant.suffix)
    if language is None:
        raise SpecError(f"no corpus language maps to {variant.suffix}")
    mutants, run_table = load_mutants(args.mutants)
    run = Run(
        item=args.item,
        variant=variant,
        test=tests[0],
        tools=tools,
        language=language,
        run_table=run_table,
        random_only=args.random_only,
        timeout=args.timeout,
    )
    if run.random_only:
        run_entry(run)
    return run, mutants


def report(results: list[Result], as_json: bool) -> int:
    """Print the counts, survivors, and broken mutants; fail on any unrestrained
    mutant.
    """
    counts = {
        status: sum(result.status == status for result in results)
        for status in STATUSES
    }
    broken = [result for result in results if result.status == BROKEN]
    failed = [
        result
        for result in results
        if result.status in {SURVIVED, UNAPPLIED}
        or (result.status == BROKEN and not result.allowed)
    ]
    if as_json:
        payload = {
            "status": "failed" if failed else "passed",
            "mutants": len(results),
            **counts,
            "survivors": [
                {"id": result.id, "description": result.description}
                for result in results
                if result.status == SURVIVED
            ],
            "broken_mutants": [
                {"id": result.id, "detail": result.detail, "allowed": result.allowed}
                for result in broken
            ],
            "unapplied_mutants": [
                {"id": result.id, "detail": result.detail}
                for result in results
                if result.status == UNAPPLIED
            ],
        }
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"{len(results)} mutants: {counts[KILLED]} killed, "
            f"{counts[SURVIVED]} survived,"
            f" {counts[BROKEN]} broken, {counts[UNAPPLIED]} unapplied,"
            f" {counts[EQUIVALENT]} equivalent"
        )
        for result in results:
            if result.status == SURVIVED:
                print(f"survived {result.id}: {result.description}")
            elif result.status == BROKEN:
                print(f"broken {result.id} (allowed={result.allowed}): {result.detail}")
            elif result.status == UNAPPLIED:
                print(f"unapplied {result.id}: {result.detail}")
    return 1 if failed else 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", type=Path, required=True, help="item directory")
    parser.add_argument(
        "--variant",
        type=Path,
        required=True,
        help="version file to mutate, relative to the item",
    )
    parser.add_argument("--mutants", type=Path, required=True, help="mutants spec TOML")
    parser.add_argument(
        "--random-only",
        action="store_true",
        help="use the spec's [run] random-loop switch",
    )
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    parser.add_argument(
        "--jobs", type=int, default=4, help="mutants to run at once (default 4)"
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="seconds per mutant (default 60)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run, mutants = prepare(args)
    except SpecError as error:
        print(f"mutate_check: {error}", file=sys.stderr)
        return 2
    text = run.variant.read_text()
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(lambda mutant: run_mutant(run, text, mutant), mutants))
    return report(results, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
