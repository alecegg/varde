"""Offline agreement driver for the VQS example baseline (I/O side).

Protocol decisions live in ``baseline_protocol``. This module holds the usage
ledger, the Codex and Claude Code adapters, the per-cell agreement run and the
command line. Tests use stub clients only; nothing here runs at import.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

sys.path.insert(0, str(Path(__file__).parent))
import baseline_protocol as bp

ROOT = Path(__file__).resolve().parents[4]
CORPUS = ROOT / "code/bench/quality-corpus"
BASELINE = CORPUS / "baseline"
PROBLEMS_DIR = BASELINE / "problems"
EXIT_LIMIT = 75
EXIT_CAP = 3
CLIENT_TIMEOUT_SECONDS = 900
SECRET_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY")
SOLUTION_NAMES = {
    "python": "solution.py",
    "typescript": "solution.ts",
    "csharp": "Solution.cs",
}
TEST_NAMES = {
    "python": "test_solution.py",
    "typescript": "solution.test.ts",
    "csharp": "Tests.cs",
}


class CapRefused(Exception):
    """A call would pass the call or token cap."""


class LimitStop(Exception):
    """A client reported a usage limit; resume after ``resume_after`` (epoch)."""

    def __init__(self, client: str, resume_after: float) -> None:
        super().__init__(f"{client} limit until {resume_after}")
        self.client = client
        self.resume_after = resume_after


class SecretBlocked(Exception):
    """Generated code matched the secret scan; nothing was written."""


@dataclass(frozen=True)
class Reply:
    text: str
    usage: Mapping[str, int] | None = None  # None = client did not report usage


class Client(Protocol):
    name: str

    def call(self, prompt: str) -> Reply: ...


# ---- adapters ---------------------------------------------------------------------

Runner = Callable[[list[str], str, dict[str, str]], tuple[int, str, str]]


def subprocess_runner(
    argv: list[str], stdin: str, env: dict[str, str]
) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory(prefix="baseline-client-") as cwd:
        done = subprocess.run(  # noqa: S603 - fixed argv from the adapters below.
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            cwd=cwd,
            timeout=CLIENT_TIMEOUT_SECONDS,
            check=False,
        )
    return done.returncode, done.stdout, done.stderr


def subscription_env(source: Mapping[str, str]) -> dict[str, str]:
    """Environment without API keys: subscription logins only."""
    return {k: v for k, v in source.items() if k not in SECRET_ENV}


def looks_like_limit(text: str) -> bool:
    lowered = text.lower()
    return any(
        word in lowered
        for word in ("usage limit", "rate limit", "limit reached", "quota")
    )


def limit_resume_after(now: float) -> float:
    """The CLIs give no machine-readable reset time; wait an hour (unverified)."""
    return now + 3600


class ClaudeClient:
    name = "sonnet"
    model = "claude-sonnet-5-5"

    def __init__(
        self, runner: Runner = subprocess_runner, clock: Callable[[], float] = time.time
    ) -> None:
        self.runner, self.clock = runner, clock

    def call(self, prompt: str) -> Reply:
        argv = [
            "claude",
            "-p",
            "--model",
            self.model,
            "--output-format",
            "json",
            "--tools",
            "",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--setting-sources",
            "",
        ]
        code, out, err = self.runner(argv, prompt, subscription_env(os.environ))
        payload = _json_or_none(out)
        failed = code != 0 or payload is None or payload.get("is_error")
        text = payload.get("result", "") if payload else ""
        if failed or payload is None:
            if looks_like_limit(f"{out} {err} {text}"):
                raise LimitStop(self.name, limit_resume_after(self.clock()))
            raise RuntimeError(
                f"claude call failed (exit {code}): {(err or text)[:300]}"
            )
        usage = payload.get("usage")
        return Reply(text, usage if isinstance(usage, dict) else None)


class CodexClient:
    name = "luna"
    model = "gpt-6-luna"

    def __init__(
        self, runner: Runner = subprocess_runner, clock: Callable[[], float] = time.time
    ) -> None:
        self.runner, self.clock = runner, clock

    def call(self, prompt: str) -> Reply:
        argv = [
            "codex",
            "exec",
            "-m",
            self.model,
            "-s",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            "-",
        ]
        code, out, err = self.runner(argv, prompt, subscription_env(os.environ))
        text, usage = parse_codex_events(out)
        if code != 0 or text is None:
            if looks_like_limit(f"{out} {err}"):
                raise LimitStop(self.name, limit_resume_after(self.clock()))
            raise RuntimeError(f"codex call failed (exit {code}): {err[:300]}")
        return Reply(text, usage)


def _json_or_none(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def parse_codex_events(stdout: str) -> tuple[str | None, dict[str, int] | None]:
    """Last agent message and the last ``turn.completed`` usage from ``--json`` lines.

    Event names follow the codex exec JSONL stream; unverified live, so a
    missing usage simply makes the call an estimate.
    """
    text: str | None = None
    usage: dict[str, int] | None = None
    for raw in stdout.splitlines():
        event = _json_or_none(raw)
        if event is None:
            continue
        item = event.get("item") or {}
        if (
            event.get("type") == "item.completed"
            and item.get("type") == "agent_message"
        ):
            text = item.get("text", text)
        if event.get("type") == "turn.completed" and isinstance(
            event.get("usage"), dict
        ):
            reported = event["usage"]
            usage = {
                "input_tokens": int(reported.get("input_tokens", 0)),
                "output_tokens": int(reported.get("output_tokens", 0)),
            }
    return text, usage


# ---- ledger -----------------------------------------------------------------------


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text().splitlines()
            if line.strip()
        ]

    def append(self, line: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(json.dumps(line, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


# ---- problem texts and test runner -------------------------------------------------


def load_problem_text(
    problem: str, language: str, problems: Path = PROBLEMS_DIR, corpus: Path = CORPUS
) -> bp.ProblemText:
    directory = problems / problem
    return bp.ProblemText(
        (directory / "prompt.txt").read_text(),
        (directory / "spec.md").read_text(),
        (directory / "api.md").read_text(),
        (corpus / "idiom" / f"{language}.md").read_text(),
    )


def load_lens(base: str, corpus: Path = CORPUS) -> str:
    return (corpus / "raters" / bp.LENS_FILES[base]).read_text()


def default_tester(cell: bp.Cell, code: str) -> Any:
    """Behaviour tests through the sandboxed runner; None without a toolchain."""
    sys.path.insert(0, str(ROOT / "code/src"))
    from varde_code.quality_score import baseline_tests as bt

    support = {}
    if cell.language == "csharp":
        support = {
            n: (PROBLEMS_DIR / "_support/csharp" / n).read_text()
            for n in ("Baseline.csproj", "Harness.cs")
        }
    with tempfile.TemporaryDirectory(prefix="baseline-solution-") as temp:
        (Path(temp) / SOLUTION_NAMES[cell.language]).write_text(code)
        test_file = (
            PROBLEMS_DIR / cell.problem / cell.language / TEST_NAMES[cell.language]
        )
        return bt.run_tests(cell.language, Path(temp), test_file, support)


def default_toolchain(language: str) -> bool:
    sys.path.insert(0, str(ROOT / "code/src"))
    from varde_code.quality_score import baseline_tests as bt

    return bt.toolchain_available(language)


def default_measurer(cell: bp.Cell, code: str) -> dict[str, Any]:
    import baseline_measure as bm

    with tempfile.TemporaryDirectory(prefix="baseline-measure-") as temp:
        (Path(temp) / SOLUTION_NAMES[cell.language]).write_text(code)
        measured = bm.report(
            bm.measure_directory(
                Path(temp), cell.language, bm.load_calibration(bm.DEFAULT_CALIBRATION)
            )
        )
    return {
        name: value.get("per_1k_micro", value) if isinstance(value, dict) else value
        for name, value in measured["metrics"].items()
    }


def default_scanner(snippets: list[str]) -> list[str]:
    from varde_dev.calibrate.panel.commands import scan_secrets

    return scan_secrets(snippets)


# ---- driver -----------------------------------------------------------------------


@dataclass
class Driver:
    ledger: Ledger
    clients: Mapping[str, Client]
    run_id: str
    state_dir: Path
    out_dir: Path
    texts: Callable[[bp.Cell], bp.ProblemText]
    lens: Callable[[str], str]
    tester: Callable[[bp.Cell, str], Any]
    measurer: Callable[[bp.Cell, str], dict[str, Any]]
    scanner: Callable[[list[str]], list[str]]
    toolchain: Callable[[str], bool] = lambda language: True
    clock: Callable[[], float] = time.time
    max_calls: int = bp.MAX_CALLS
    max_tokens: int = bp.MAX_TOKENS
    overhead: int = bp.DEFAULT_OVERHEAD_TOKENS
    calls_made: int = field(default=0, init=False)

    def _cache(self, key: str) -> Path:
        safe = key.replace("/", "__").replace(":", "__")
        return self.state_dir / self.run_id / f"{safe}.txt"

    def call(
        self, cell: bp.Cell, step: str, family: str, role: str, prompt: str
    ) -> str:
        """One counted model call, or the cached reply of a call done in this run."""
        key = f"{cell.key}:{step}"
        lines = self.ledger.read()
        cached = self._cache(key)
        if key in bp.done_keys(lines, self.run_id) and cached.exists():
            return cached.read_text()
        resume = bp.active_limits(lines, self.clock()).get(family)
        if resume is not None:
            raise LimitStop(family, resume)
        estimate = bp.estimate_tokens(
            len(prompt), bp.ROLE_CHARS.get(role, (0, 8000))[1], self.overhead
        )
        refusal = bp.check_cap(
            bp.ledger_totals(lines), estimate, self.max_calls, self.max_tokens
        )
        if refusal:
            raise CapRefused(refusal)
        base = {
            "run": self.run_id,
            "key": key,
            "client": family,
            "role": role,
            "cell": cell.key,
        }
        self.ledger.append(
            {
                **base,
                "kind": "intent",
                "prompt_chars": len(prompt),
                "est_tokens": estimate,
                "ts": self.clock(),
            }
        )
        try:
            reply = self.clients[family].call(prompt)
        except LimitStop as stop:
            self.ledger.append(
                {
                    **base,
                    "kind": "result",
                    "outcome": "limit",
                    "tokens": 0,
                    "estimated": False,
                    "output_chars": 0,
                    "ts": self.clock(),
                }
            )
            self.ledger.append(
                {
                    "kind": "limit",
                    "client": family,
                    "resume_after": stop.resume_after,
                    "ts": self.clock(),
                }
            )
            raise
        except Exception:
            self.ledger.append(
                {
                    **base,
                    "kind": "result",
                    "outcome": "error",
                    "tokens": estimate,
                    "estimated": True,
                    "output_chars": 0,
                    "ts": self.clock(),
                }
            )
            raise
        reported = reply.usage is not None
        tokens = (
            bp.billed_tokens(reply.usage)
            if reply.usage is not None
            else bp.estimate_tokens(len(prompt), len(reply.text), self.overhead)
        )
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(reply.text)
        self.ledger.append(
            {
                **base,
                "kind": "result",
                "outcome": "ok",
                "tokens": tokens,
                "estimated": not reported,
                "output_chars": len(reply.text),
                "ts": self.clock(),
            }
        )
        self.calls_made += 1
        return reply.text

    def write_version(
        self, directory: Path, cell: bp.Cell, code: str, provenance: Mapping[str, Any]
    ) -> None:
        """Secret-scan first; write the code and PROVENANCE.md only if clean."""
        found = self.scanner([code])
        if found:
            raise SecretBlocked(", ".join(found))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / SOLUTION_NAMES[cell.language]).write_text(code)
        rows = "\n".join(f"- {k}: {v}" for k, v in provenance.items())
        (directory / "PROVENANCE.md").write_text(
            f"# Provenance\n\nGenerated code, repository license applies.\n\n{rows}\n"
        )


def _passes(result: Any) -> bool:
    return result is not None and result.ok


def _output(result: Any) -> str:
    return result.output_tail if result is not None else ""


def run_cell(d: Driver, index: int, cell: bp.Cell) -> dict[str, Any]:
    """Agreement protocol for one cell; returns its summary entry."""
    summary: dict[str, Any] = {
        "problem": cell.problem,
        "language": cell.language,
        "agreed": False,
        "tests_passed": False,
        "status": "",
        "calls": 0,
    }
    if not d.toolchain(cell.language):
        return {**summary, "status": "toolchain_missing"}
    before = d.calls_made
    try:
        _agree(d, index, cell, summary)
    except SecretBlocked as blocked:
        summary |= {"agreed": False, "status": f"secret_blocked: {blocked}"}
    summary["calls"] = d.calls_made - before
    return summary


def _write_and_repair(
    d: Driver, index: int, cell: bp.Cell, text: bp.ProblemText, repairs: list[int]
) -> dict[str, str]:
    families = bp.writer_families(index)
    passing: dict[str, str] = {}
    for base in bp.BASES:
        prompt = bp.writer_prompt(text, cell.language, base, d.lens(base))
        code = bp.extract_code(
            d.call(cell, f"write-{base}", families[base], "write", prompt)
        )
        result = d.tester(cell, code) if code else None
        while code and not _passes(result) and repairs[0] < bp.MAX_REPAIRS:
            repairs[0] += 1
            reply = d.call(
                cell,
                f"repair-{repairs[0]}",
                families[base],
                "repair",
                bp.repair_prompt(cell.language, code, _output(result)),
            )
            code = bp.extract_code(reply) or code
            result = d.tester(cell, code)
        if code and _passes(result):
            passing[base] = code
    return passing


def _fix_merged(
    d: Driver, cell: bp.Cell, family: str, merged: str, result: Any
) -> tuple[str, Any]:
    reply = d.call(
        cell,
        "fix",
        family,
        "fix",
        bp.fix_prompt(cell.language, merged, _output(result)),
    )
    fixed = bp.extract_code(reply) or merged
    return fixed, d.tester(cell, fixed)


def _negotiate(
    d: Driver,
    index: int,
    cell: bp.Cell,
    passing: dict[str, str],
    metrics: dict[str, Any],
) -> tuple[str, dict[str, str]]:
    """One conflicts call by the judge, then one case call per party school."""
    language, families = cell.language, bp.writer_families(index)
    conflicts = d.call(
        cell,
        "conflicts",
        bp.judge_family(index),
        "conflicts",
        bp.conflicts_prompt(language, passing, metrics),
    )
    parties = bp.conflict_parties(bp.parse_conflicts(conflicts))
    cases = {
        base: d.call(
            cell,
            f"case-{base}",
            families[base],
            "case",
            bp.case_prompt(base, d.lens(base), language, passing, metrics, conflicts),
        )
        for base in parties
        if base in passing
    }
    return conflicts, cases


def _agree(d: Driver, index: int, cell: bp.Cell, summary: dict[str, Any]) -> None:
    text = d.texts(cell)
    passing = _write_and_repair(d, index, cell, text, [0])
    if not passing:
        summary["status"] = "writers_failed"
        return
    metrics = {base: d.measurer(cell, code) for base, code in passing.items()}
    judge = bp.judge_family(index)
    conflicts, cases = _negotiate(d, index, cell, passing, metrics)
    reply = d.call(
        cell,
        "ruling",
        judge,
        "ruling",
        bp.ruling_prompt(cell.language, passing, metrics, conflicts, cases),
    )
    rulings, final = bp.split_ruling(reply)
    if final is None or not rulings:
        summary["status"] = "no_ruling"
        return
    final, passed = _test_with_one_fix(d, cell, judge, final)
    summary |= {"tests_passed": passed, "rulings": rulings, "agreed": passed}
    summary["status"] = "judge_ruled" if passed else "tests_failed"
    _record_version(d, cell, final, summary, judge)


def _test_with_one_fix(
    d: Driver, cell: bp.Cell, family: str, code: str
) -> tuple[str, bool]:
    """Test the code; on failure make the cell's one fix call."""
    result = d.tester(cell, code)
    if not _passes(result):
        code, result = _fix_merged(d, cell, family, code, result)
    return code, _passes(result)


def _record_version(
    d: Driver, cell: bp.Cell, merged: str, summary: dict[str, Any], judge: str
) -> None:
    text = d.texts(cell)
    directory = d.out_dir / "agreed" / cell.problem / cell.language
    summary["dir"] = str(directory.relative_to(d.out_dir))
    d.write_version(
        directory,
        cell,
        merged,
        {
            "generator": f"judge {judge}",
            "clients": "codex gpt-6-luna, claude-sonnet-5-5",
            "lens_bases": ", ".join(bp.BASES),
            "idiom_notes_sha256": bp.sha256(text.idiom),
            "lens_sha256": ", ".join(
                f"{base}={bp.sha256(d.lens(base))}" for base in bp.BASES
            ),
            "prompt_sha256": bp.sha256(text.prompt),
            "agreed": summary["agreed"],
            "status": summary["status"],
        },
    )


def run_probe(d: Driver, family: str) -> dict[str, Any]:
    """One tiny call that records the per-call overhead for the client."""
    cell = bp.Cell("probe", "none")
    before = len(d.ledger.read())
    prompt = "Reply with the single word ok."
    d.call(cell, f"probe-{family}", family, "probe", prompt)
    result = next(
        line for line in reversed(d.ledger.read()[before:]) if line["kind"] == "result"
    )
    overhead = max(
        0, result["tokens"] - bp.estimate_tokens(len(prompt), result["output_chars"], 0)
    )
    line = {
        "kind": "probe",
        "client": family,
        "overhead_tokens": overhead,
        "estimated": result["estimated"],
        "ts": d.clock(),
    }
    d.ledger.append(line)
    return line


# ---- command line -----------------------------------------------------------------


def dry_run(args: argparse.Namespace) -> int:
    cells = bp.parse_cells(args.cells)
    plan = bp.planned_calls(len(cells))
    lines = Ledger(Path(args.ledger)).read()
    measured = bp.measured_overhead(lines)
    overhead = measured if measured is not None else bp.DEFAULT_OVERHEAD_TOKENS
    tokens = bp.projected_tokens(len(cells), overhead)
    print(
        f"planned calls: {plan['total']} (agreement {plan['agreement']}"
        f" + probes {plan['probes']});"
        f" typical {plan['typical_total']} at {len(bp.TYPICAL_CELL_ROLES)} per cell"
    )
    source = "measured" if measured is not None else "unmeasured default"
    print(f"per-call overhead: {overhead} tokens ({source})")
    if args.token_estimate:
        print(
            f"projected tokens: typical {tokens['typical']},"
            f" worst case {tokens['worst_case']} (cap {args.max_tokens})"
        )
    if args.max_planned_calls is not None and plan["total"] > args.max_planned_calls:
        print(f"refused: planned calls {plan['total']} exceed {args.max_planned_calls}")
        return 1
    if args.token_estimate and tokens["typical"] > args.max_tokens:
        print(
            f"refused: typical projection {tokens['typical']} exceeds"
            f" {args.max_tokens}; re-cap decision needed"
        )
        return 1
    return 0


def check_ledger(args: argparse.Namespace) -> int:
    lines = Ledger(Path(args.check_ledger)).read()
    totals = bp.ledger_totals(lines)
    late = bp.calls_after_limit(lines)
    print(
        f"calls {totals.calls} tokens {totals.tokens}"
        f" estimated calls {totals.estimated_calls}"
    )
    problems = []
    if totals.calls > args.max_calls:
        problems.append(f"calls {totals.calls} exceed {args.max_calls}")
    if totals.tokens > args.max_tokens:
        problems.append(f"tokens {totals.tokens} exceed {args.max_tokens}")
    problems += [f"call after recorded limit: {key}" for key in late]
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def check_agreed(args: argparse.Namespace) -> int:
    path = Path(args.check_agreed)
    entries = json.loads(path.read_text())
    problems = bp.check_agreement_entries(
        entries, args.min_per_language, args.min_total
    )
    root = Path(args.out_dir)
    for key, entry in entries.items():
        directory = entry.get("dir")
        if not directory:
            continue
        folder = root / directory
        if not (folder / "PROVENANCE.md").exists():
            problems.append(f"{key}: no PROVENANCE.md")
        problems += [
            f"{key}: secret scan {hit}"
            for hit in default_scanner(
                [
                    p.read_text()
                    for p in folder.glob("*")
                    if p.suffix in (".py", ".ts", ".cs")
                ]
            )
        ]
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def live_run(args: argparse.Namespace) -> int:
    run_id = args.run_id or uuid.uuid4().hex[:8]
    ledger = Ledger(Path(args.ledger))
    measured = bp.measured_overhead(ledger.read())
    d = Driver(
        ledger=ledger,
        clients={"luna": CodexClient(), "sonnet": ClaudeClient()},
        run_id=run_id,
        state_dir=Path(args.state_dir),
        out_dir=Path(args.out_dir),
        texts=lambda c: load_problem_text(c.problem, c.language),
        lens=load_lens,
        tester=default_tester,
        measurer=default_measurer,
        scanner=default_scanner,
        toolchain=default_toolchain,
        max_calls=args.max_calls,
        max_tokens=args.max_tokens,
        overhead=measured if measured is not None else bp.DEFAULT_OVERHEAD_TOKENS,
    )
    agreement_path = Path(args.agreement)
    summaries = (
        json.loads(agreement_path.read_text()) if agreement_path.exists() else {}
    )
    try:
        if args.probe:
            for family in d.clients:
                print(json.dumps(run_probe(d, family)))
            return 0
        for index, cell in enumerate(bp.all_cells()):
            if cell not in bp.parse_cells(args.cells):
                continue
            summaries[cell.key] = run_cell(d, index, cell)
            agreement_path.write_text(json.dumps(summaries, indent=2, sort_keys=True))
    except LimitStop as stop:
        print(
            f"limit: {stop.client} resume after {stop.resume_after};"
            f" resume with --run-id {run_id}"
        )
        return EXIT_LIMIT
    except CapRefused as refusal:
        print(f"cap refused, stop and report: {refusal}")
        return EXIT_CAP
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--cells", default="all")
    p.add_argument("--max-planned-calls", type=int)
    p.add_argument("--token-estimate", action="store_true")
    p.add_argument("--max-tokens", type=int, default=bp.MAX_TOKENS)
    p.add_argument("--max-calls", type=int, default=bp.MAX_CALLS)
    p.add_argument("--check-ledger")
    p.add_argument("--check-agreed")
    p.add_argument("--min-per-language", type=int, default=3)
    p.add_argument("--min-total", type=int, default=9)
    p.add_argument("--ledger", default="notes/usage-ledger.jsonl")
    p.add_argument("--state-dir", default="notes/run-state")
    p.add_argument("--agreement", default="notes/agreement.json")
    p.add_argument("--out-dir", default=str(BASELINE))
    p.add_argument("--run-id")
    p.add_argument("--probe", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run:
        return dry_run(args)
    if args.check_ledger:
        return check_ledger(args)
    if args.check_agreed:
        return check_agreed(args)
    return live_run(args)


if __name__ == "__main__":
    sys.exit(main())
