"""Validate the baseline example problems against the restricted split."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "baseline"
PROBLEMS = ROOT / "problems"
LOCK = Path(__file__).resolve().parent / "splits.lock"
LANGUAGES = ("python", "typescript", "csharp")
THEME_STEMS = ("retry", "ship", "price", "order", "queue", "inventory")
MAX_CASES = 8
TEST_TIMEOUT_SECONDS = 240


def restricted_ids(lock: Path) -> list[str]:
    """Read only the ids assigned to the restricted split from the lock file."""
    assignments = json.loads(lock.read_text())["assignments"]
    return sorted(i for i, split in assignments.items() if split == "test-restricted")


def problem_ids(problems: Path = PROBLEMS) -> list[str]:
    return sorted(
        p.name for p in problems.iterdir() if p.is_dir() and not p.name.startswith("_")
    )


def normalize(text: str) -> str:
    return re.sub(r"[\s_]+", "-", text.lower())


def restricted_in_text(text: str, restricted: list[str]) -> list[str]:
    flat = normalize(text)
    return [r for r in restricted if r in flat]


def id_collisions(ids: list[str], restricted: list[str]) -> list[str]:
    return [f"problem id {i} is a test-restricted id" for i in ids if i in restricted]


def theme_overlaps(prompts: dict[str, str], restricted: list[str]) -> list[str]:
    """List restricted ids sharing a theme stem with a problem (main judges)."""
    found = []
    for problem, prompt in sorted(prompts.items()):
        text = normalize(f"{problem} {prompt}")
        for stem in THEME_STEMS:
            if stem not in text:
                continue
            found.extend(
                f"{problem} ~ {r} (word {stem})" for r in restricted if stem in r
            )
    return found


def spec_cases(spec: str) -> list[int]:
    return [int(m) for m in re.findall(r"^(\d+)\. ", spec, re.MULTILINE)]


def check_text(problem: str, directory: Path, restricted: list[str]) -> list[str]:
    errors = []
    prompt = (
        (directory / "prompt.txt").read_text().strip()
        if (directory / "prompt.txt").exists()
        else ""
    )
    if not prompt or "\n" in prompt or prompt.count(". ") or not prompt.endswith("."):
        errors.append(f"{problem}: prompt.txt must be one sentence")
    spec_path = directory / "spec.md"
    cases = spec_cases(spec_path.read_text()) if spec_path.exists() else []
    if not cases or cases != list(range(1, len(cases) + 1)) or len(cases) > MAX_CASES:
        errors.append(
            f"{problem}: spec.md needs numbered cases 1..N with N <= {MAX_CASES}"
        )
    if not (directory / "api.md").exists():
        errors.append(f"{problem}: api.md is missing")
    for name in ("prompt.txt", "spec.md", "api.md"):
        path = directory / name
        hits = restricted_in_text(path.read_text(), restricted) if path.exists() else []
        errors.extend(f"{problem}/{name} mentions restricted id {h}" for h in hits)
    return errors


def check_files(
    problem: str, directory: Path, language: str, toolchain: dict
) -> list[str]:
    needed = [
        directory / language / toolchain["test"],
        directory / language / "reference-stub" / toolchain["solution"],
    ]
    return [f"{problem}/{language}: missing {p.name}" for p in needed if not p.exists()]


def csharp_framework_version(env: dict[str, str]) -> str:
    out = subprocess.run(
        ["dotnet", "--version"],  # noqa: S607 - fixed toolchain command.
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return out.stdout.strip().split(".")[0] or "8"


def scrubbed_env(home: Path) -> dict[str, str]:
    keep = {k: v for k, v in os.environ.items() if k in ("PATH", "DOTNET_ROOT", "LANG")}
    return keep | {
        "HOME": str(home),
        "DOTNET_CLI_HOME": str(home),
        "DOTNET_NOLOGO": "1",
        "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    }


def stage_workspace(
    root: Path, solution: Path, test: Path, toolchain: dict, tfm: str | None
) -> None:
    shutil.copy(solution, root / toolchain["solution"])
    shutil.copy(test, root / toolchain["test"])
    for name in toolchain.get("support", []):
        text = (PROBLEMS / "_support" / "csharp" / name).read_text()
        (root / name).write_text(text.replace("{tfm}", tfm or "8"))


def run_tests(
    language: str, solution: Path, test: Path, toolchains: dict
) -> tuple[bool, str]:
    """Run one test file against one solution file with the recorded command."""
    toolchain = toolchains[language]
    missing = [t for t in toolchain["tools"] if shutil.which(t) is None]
    if missing:
        return False, f"missing toolchain {missing}: {toolchain['requires']}"
    with tempfile.TemporaryDirectory(prefix="baseline-problems-") as temp:
        root = Path(temp)
        env = scrubbed_env(root / "home")
        tfm = csharp_framework_version(env) if language == "csharp" else None
        stage_workspace(root, solution, test, toolchain, tfm)
        try:
            done = subprocess.run(  # noqa: S603 - command comes from toolchains.toml.
                toolchain["command"],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=TEST_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "timed out"
        return done.returncode == 0, (done.stdout + done.stderr)[-1500:]


def check_stub_runs(
    problem: str, directory: Path, language: str, toolchains: dict
) -> list[str]:
    toolchain = toolchains[language]
    solution = directory / language / "reference-stub" / toolchain["solution"]
    test = directory / language / toolchain["test"]
    ok, output = run_tests(language, solution, test, toolchains)
    return (
        []
        if ok
        else [f"{problem}/{language}: tests fail against the reference stub\n{output}"]
    )


def check_layout(
    expected_problems: int,
    languages: list[str],
    restricted: list[str],
    problems: Path = PROBLEMS,
    run: bool = True,
) -> list[str]:
    ids = problem_ids(problems)
    errors = id_collisions(ids, restricted)
    if len(ids) != expected_problems:
        errors.append(f"expected {expected_problems} problems, found {len(ids)}")
    toolchains = tomllib.loads((problems / "toolchains.toml").read_text())
    for problem in ids:
        directory = problems / problem
        errors.extend(check_text(problem, directory, restricted))
        for language in languages:
            file_errors = check_files(
                problem, directory, language, toolchains[language]
            )
            errors.extend(file_errors)
            if run and not file_errors:
                errors.extend(check_stub_runs(problem, directory, language, toolchains))
    return errors


def restricted_path_references(root: Path, restricted: list[str]) -> list[str]:
    """Baseline input paths (relative to root) that name a restricted id."""
    refs = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        refs.extend(
            f"{relative} references restricted id {h}"
            for h in restricted_in_text(relative, restricted)
        )
    return refs


def prompts_of(problems: Path = PROBLEMS) -> dict[str, str]:
    return {
        p: (problems / p / "prompt.txt").read_text().strip()
        for p in problem_ids(problems)
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-restricted", action="store_true")
    parser.add_argument("--problems", type=int, default=4)
    parser.add_argument("--languages", default=",".join(LANGUAGES))
    parser.add_argument("--splits-lock", type=Path, default=LOCK)
    args = parser.parse_args(argv)
    if not (args.check or args.check_restricted):
        parser.error("choose --check or --check-restricted")
    restricted = restricted_ids(args.splits_lock)
    errors = []
    if args.check:
        errors += check_layout(args.problems, args.languages.split(","), restricted)
        for line in theme_overlaps(prompts_of(), restricted):
            print(f"theme overlap for main to judge: {line}")
    if args.check_restricted:
        errors += restricted_path_references(ROOT, restricted)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
