"""Command-level output evaluation and calibration orchestration."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_core.skill_relations import (
    RelationError,
    closure,
)
from varde_core.skill_relations import (
    parse as parse_skill_relations,
)

from ..process import RunRequest, run_with_timeout
from . import (
    Config,
    EvalOutcome,
    OutputHarness,
    RunRecord,
    adapter,
    assertions,
    grade,
    paired,
)
from . import calibrate as mutations


@dataclass(frozen=True)
class OutputRequest:
    skill_dir: Path
    harness: OutputHarness = OutputHarness.CODEX
    model: str | None = None
    judge_model: str | None = None
    runs: int = 1
    iteration: int = 1
    workspace: Path | None = None
    eval_ids: tuple[str, ...] = ()
    timeout_seconds: int = 300
    sandbox_dir: Path | None = None
    no_baseline: bool = False


@dataclass
class OutputReport:
    iteration_dir: Path
    records: list[RunRecord]
    benchmark: dict[str, Any]
    excluded_ids: list[str]


@dataclass(frozen=True)
class HarnessCall:
    harness: str
    model: str | None
    prompt: str
    cwd: Path
    timeout_seconds: int
    env: dict[str, str]
    judge: bool = False
    extra_args: tuple[str, ...] = ()


Runner = Callable[[HarnessCall], tuple[dict[str, Any], int, int]]


def run_output(request: OutputRequest, *, runner: Runner | None = None) -> OutputReport:
    """Run selected evals through an injectable transcript runner."""
    skill_dir, evals = _validate_request(request, runner)
    workspace = request.workspace or Path(f"{skill_dir}-workspace")
    iteration_dir = workspace / f"iteration-{request.iteration}"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    cases, excluded_ids = _exclude_environment_limited(evals)
    cases = [
        case for case in cases if not request.eval_ids or case["id"] in request.eval_ids
    ]
    records = []
    configs = (
        (Config.WITH_SKILL,)
        if request.no_baseline
        else (Config.WITH_SKILL, Config.WITHOUT_SKILL)
    )
    for case in cases:
        _validate_case_files(skill_dir, case)
        for config in configs:
            records.extend(
                _execute(
                    request,
                    skill_dir,
                    case,
                    config,
                    run_number,
                    iteration_dir,
                    runner,
                )
                for run_number in range(1, request.runs + 1)
            )
    benchmark = _benchmark(skill_dir, request.iteration, request, records)
    benchmark["excluded_ids"] = excluded_ids
    (iteration_dir / "benchmark.json").write_text(
        json.dumps(benchmark, indent=2) + "\n"
    )
    return OutputReport(iteration_dir, records, benchmark, excluded_ids)


def _exclude_environment_limited(evals: list[dict[str, Any]]):
    included = []
    excluded_ids = []
    for item in evals:
        if _is_environment_limited(item):
            excluded_ids.append(item["id"])
        else:
            included.append(item)
    return included, excluded_ids


def _is_environment_limited(item: dict[str, Any]) -> bool:
    value = item.get("environment_limited", False)
    if not isinstance(value, bool):
        raise ValueError(f"eval {item['id']} environment_limited must be a boolean")
    return value


def calibrate(
    skill_dir: Path, harness: OutputHarness, *, runner: Runner | None = None
) -> dict[str, Any]:
    """Apply declared mutations in isolated copies and check fail/pass sensitivity."""
    source = skill_dir.resolve(strict=True)
    if not (source / "SKILL.md").is_file():
        raise ValueError(f"no SKILL.md in {source}")
    mutation_path = source / "evals/mutations.json"
    try:
        mutation_data = json.loads(mutation_path.read_text())
    except OSError as error:
        reason = (
            "No such file or directory (os error 2)"
            if isinstance(error, FileNotFoundError)
            else str(error)
        )
        raise ValueError(f"cannot read {mutation_path}: {reason}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid {mutation_path}: {error}") from error
    declared = (
        mutation_data.get("mutations") if isinstance(mutation_data, dict) else None
    )
    if not isinstance(declared, list) or not declared:
        raise ValueError("mutation list must not be empty")
    if not any(
        isinstance(item, dict) and item.get("negative") is True for item in declared
    ):
        raise ValueError("mutation list must include at least one negative mutation")
    for item in declared:
        _validate_mutation(item)
    results = []
    with tempfile.TemporaryDirectory(prefix="varde-learn-calibrate-") as temp:
        root = Path(temp)
        for item in declared:
            copy = root / f"mutation-{len(results)}"
            mutations.copy_skill(source, copy)
            mutations.apply_mutation(
                copy, item["file"], item["remove"], item.get("replace_with", "")
            )
            report = run_output(
                OutputRequest(
                    copy,
                    harness,
                    workspace=root / f"run-{len(results)}",
                    eval_ids=tuple(item["evals"]),
                    no_baseline=True,
                ),
                runner=runner,
            )
            expected_pass = item.get("negative", False)
            passed = all(
                _record_passes(record)
                if expected_pass
                else _record_fails_assertions(record)
                for record in report.records
            )
            results.append(
                {
                    "mutation": item["id"],
                    "negative": expected_pass,
                    "evals": item["evals"],
                    "passed": passed,
                }
            )
        restored = root / "restored"
        mutations.copy_skill(source, restored)
        ids = tuple(
            dict.fromkeys(eval_id for item in declared for eval_id in item["evals"])
        )
        restored_report = run_output(
            OutputRequest(
                restored,
                harness,
                workspace=root / "restored-run",
                eval_ids=ids,
                no_baseline=True,
            ),
            runner=runner,
        )
        restored_passed = bool(restored_report.records) and all(
            _record_passes(record) for record in restored_report.records
        )
    return {
        "passed": all(item["passed"] for item in results) and restored_passed,
        "mutations": results,
        "restored_passed": restored_passed,
    }


def _validate_request(request: OutputRequest, runner: Runner | None):
    if request.runs <= 0:
        raise ValueError("--runs must be a positive integer")
    if request.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be a positive integer")
    if runner is None and shutil.which(request.harness.value) is None:
        raise ValueError(f"{request.harness.value} CLI is required")
    if not request.skill_dir.is_dir():
        raise ValueError(f"skill dir not found: {request.skill_dir}")
    skill_dir = request.skill_dir.resolve(strict=True)
    if not (skill_dir / "SKILL.md").is_file():
        raise ValueError(f"no SKILL.md in {skill_dir}")
    if request.sandbox_dir is not None:
        if not request.sandbox_dir.is_dir():
            raise ValueError(f"sandbox dir not found: {request.sandbox_dir}")
        if (request.sandbox_dir / ".git").is_file():
            raise ValueError(
                "--sandbox-dir must be a standalone clone or directory, not a linked "
                "worktree"
            )
    path = skill_dir / "evals/evals.json"
    if not path.is_file():
        raise ValueError(f"no eval set at {path}")
    try:
        data = json.loads(path.read_text())
    except OSError as error:
        raise ValueError(f"no eval set at {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {path}") from error
    evals = data.get("evals") if isinstance(data, dict) else None
    if not isinstance(evals, list):
        raise ValueError(f"invalid JSON in {path}")
    if not evals:
        raise ValueError("no evals in " + str(path))
    skills = data.get("skills")
    if skills is not None and not isinstance(skills, list):
        raise ValueError(f"suite skills in {path} must be an array of strings")
    if isinstance(skills, list):
        for index, item in enumerate(skills):
            if not isinstance(item, str):
                raise ValueError(
                    f"suite skills in {path}: skills[{index}] must be a string"
                )
    else:
        skills = _default_suite_skills(skill_dir)
    ids = set()
    for index, item in enumerate(evals):
        if not isinstance(item, dict) or not isinstance(item.get("prompt"), str):
            raise ValueError(
                "eval "
                f"{item.get('id', index + 1) if isinstance(item, dict) else index + 1} "
                "is missing a prompt"
            )
        identifier = str(item.get("id", index + 1))
        if (
            not identifier
            or identifier in {".", ".."}
            or "/" in identifier
            or "\\" in identifier
            or any(ord(char) < 32 for char in identifier)
        ):
            raise ValueError(f"invalid eval id: {identifier!r}")
        if identifier in ids:
            raise ValueError(f"duplicate eval id: {identifier}")
        ids.add(identifier)
        _is_environment_limited(item)
        item["id"] = identifier
        item.setdefault("expected_output", "")
        item["skills"] = skills
        item.setdefault("files", [])
        item.setdefault("env", {})
        item.setdefault("assertions", [])
        item.setdefault("assert", [])
        _validate_case_env(item["env"], identifier)
    for eval_id in request.eval_ids:
        if eval_id not in ids:
            raise ValueError(f"evaluation not found: {eval_id}")
    return skill_dir, evals


def _default_suite_skills(skill_dir: Path) -> list[str]:
    skill_root = skill_dir.parent
    cause = None

    def requires_of(name: str):
        nonlocal cause
        path = skill_root / name / "SKILL.md"
        try:
            text = path.read_text()
        except OSError as error:
            cause = (
                f"could not read SKILL.md for skill `{name}` under {skill_root}: "
                f"{error}"
            )
            return None
        if not text.startswith("---\n"):
            cause = (
                f"invalid frontmatter for skill `{name}` under {skill_root}: "
                "missing `---` delimiters"
            )
            return None
        frontmatter = text[4:].split("\n---", 1)
        if len(frontmatter) != 2:
            cause = (
                f"invalid frontmatter for skill `{name}` under {skill_root}: "
                "missing `---` delimiters"
            )
            return None
        try:
            return parse_skill_relations(frontmatter[0]).requires
        except RelationError as error:
            cause = (
                f"invalid frontmatter for skill `{name}` under {skill_root}: {error}"
            )
            return None

    try:
        return closure([skill_dir.name], requires_of)
    except RelationError as error:
        raise ValueError(cause or f"failed to resolve suite skills: {error}") from error


def _validate_case_files(skill_dir: Path, case: dict[str, Any]) -> None:
    for key, label in (
        ("setup_script", "setup_script not found"),
        ("verification_script", "verification_script not found"),
    ):
        _validate_skill_path(skill_dir, case.get(key), label)
    for file in case["files"]:
        _validate_skill_path(
            skill_dir, file, f"input file not found for eval {case['id']}"
        )


def _validate_case_env(value: Any, eval_id: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(
            f"eval {eval_id} env must be a string map with valid environment keys "
            "and no EVAL_* keys or NUL values"
        )
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not key
            or not (key[0].isalpha() or key[0] == "_")
            or any(not (char.isalnum() or char == "_") for char in key)
            or key.startswith("EVAL_")
            or not isinstance(item, str)
            or "\0" in item
        ):
            raise ValueError(
                f"eval {eval_id} env must be a string map with valid environment "
                "keys and no EVAL_* keys or NUL values"
            )


def _validate_skill_path(skill_dir: Path, relative: str | None, label: str) -> None:
    if not relative:
        return
    path = Path(relative)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"{label} must stay inside the skill directory: {relative}")
    target = skill_dir / path
    if not target.is_file():
        raise ValueError(f"{label}: {target}")


def _execute(request, skill_dir, case, config, run_number, iteration_dir, runner):
    run_dir = iteration_dir / f"eval-{case['id']}" / config.value / f"run-{run_number}"
    run_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="varde-learn-output-sbox-") as sandbox_name:
        sandbox = Path(sandbox_name)
        if request.sandbox_dir:
            shutil.copytree(
                request.sandbox_dir, sandbox, dirs_exist_ok=True, symlinks=True
            )
        skill_sandbox = None
        if config is Config.WITH_SKILL:
            skill_sandbox = sandbox / ".skill-under-evaluation"
            shutil.copytree(skill_dir, skill_sandbox)
            shutil.rmtree(skill_sandbox / "evals", ignore_errors=True)
        for relative in case["files"]:
            target = sandbox / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_dir / relative, target)
        prompt = case["prompt"]
        if skill_sandbox:
            prompt = (
                f"Evaluate only the skill snapshot at {skill_sandbox}/SKILL.md.\n"
                f"Read it directly. Resolve every relative path from {skill_sandbox}.\n"
                "Do not invoke or read an installed skill sharing its name.\n"
                + (
                    f"Skills available for this suite (names only): "
                    f"{', '.join(case['skills'])}.\n"
                    if case["skills"]
                    else ""
                )
                + f"Then handle this request:\n\n{prompt}"
            )
        env = {
            key: value.replace("{sandbox}", str(sandbox))
            for key, value in case["env"].items()
        }
        before = assertions.snapshot(sandbox)
        extra_args = ()
        if request.harness is OutputHarness.CLAUDE:
            extra_args = ("--permission-mode", "auto")
            if skill_sandbox:
                extra_args += ("--add-dir", str(skill_sandbox))
        call = HarnessCall(
            request.harness.value,
            request.model,
            prompt,
            sandbox,
            request.timeout_seconds,
            env,
            extra_args=extra_args,
        )
        raw_value, exit_code, elapsed_ms = (runner or _invoke)(call)
        outcome = EvalOutcome.COMPLETED if exit_code == 0 else EvalOutcome.FAILED
        (run_dir / "raw.json").write_text(json.dumps(raw_value, indent=2) + "\n")
        transcript = raw_value.get("result", "")
        if not isinstance(transcript, str):
            transcript = ""
        raw_assertions = assertions.verify(case["assert"], sandbox, transcript, before)
        deterministic = [
            {
                "assertion": item["kind"],
                "verdict": "PASS" if item["passed"] else "FAIL",
                "evidence": item["evidence"],
            }
            for item in raw_assertions
        ]
        declared = list(case["assertions"])
        judged = []
        if (declared or case["expected_output"]) and outcome is EvalOutcome.COMPLETED:
            judge_prompt = _judge_prompt(case, transcript)
            judge_value, judge_code, _ = (runner or _invoke)(
                HarnessCall(
                    request.harness.value,
                    request.judge_model or request.model,
                    judge_prompt,
                    sandbox,
                    request.timeout_seconds,
                    env,
                    judge=True,
                )
            )
            judged = (
                grade.parse_judge_results(judge_value.get("result", ""))
                if judge_code == 0
                else []
            )
            if case["expected_output"]:
                declared.append("expected output")
                judged.append(
                    {
                        "assertion": "expected output",
                        "verdict": "PASS"
                        if case["expected_output"] in transcript
                        else "FAIL",
                        "evidence": "expected output found"
                        if case["expected_output"] in transcript
                        else "expected output not found",
                    }
                )
        combined = grade.grade_results(
            [*declared, *[item["assertion"] for item in deterministic]],
            deterministic,
            judged,
            outcome.value,
        )
        record_transcript = transcript
        (run_dir / "transcript.txt").write_text(record_transcript)
        outputs = run_dir / "outputs"
        outputs.mkdir(exist_ok=True)
        (outputs / "transcript.txt").write_text(record_transcript)
        measured, tokens = _tokens(raw_value)
        (run_dir / "timing.json").write_text(
            json.dumps(
                {
                    "harness": request.harness.value,
                    "model": request.model,
                    "duration_ms": raw_value.get("duration_ms", elapsed_ms),
                    "tokens": tokens if measured else None,
                    "outcome": outcome.value,
                    "exit_code": exit_code,
                    "timeout_seconds": request.timeout_seconds,
                },
                indent=2,
            )
            + "\n"
        )
        total = combined["total"]
        passed = combined["passed"]
        raw_cost = raw_value.get("total_cost_usd")
        return RunRecord(
            case["id"],
            config,
            run_number,
            run_dir,
            outcome,
            "completed",
            total,
            passed,
            passed / total if total else None,
            int(raw_value.get("duration_ms", elapsed_ms)),
            tokens if measured else None,
            raw_cost if isinstance(raw_cost, (int, float)) else None,
            False,
            [item["evidence"] for item in combined["results"]],
            {},
            0,
        )


def _invoke(call: HarnessCall):
    args = adapter.args(call.harness, call.model, call.prompt, call.cwd, call.judge)
    args.extend(call.extra_args)
    with tempfile.TemporaryDirectory(prefix="varde-learn-output-run-") as temp:
        root = Path(temp)
        stdout, stderr = root / "stdout", root / "stderr"
        result = run_with_timeout(
            RunRequest(
                call.harness,
                args,
                call.cwd,
                call.env,
                call.prompt.encode() if call.harness == "codex" else b"",
                stdout,
                stderr,
                call.timeout_seconds,
            )
        )
        if result.timed_out:
            return {"result": ""}, 142, int(call.timeout_seconds * 1000)
        exit_result = result.result
        if exit_result is None:
            raise TypeError("completed process has no exit result")
        if exit_result.code != 0:
            return {"result": ""}, exit_result.code, 0
        raw = root / "raw.json"
        value, _ = adapter.read_raw(call.harness, stdout, raw)
        return value, 0, int(value.get("duration_ms", 0))


def _judge_prompt(case, transcript):
    assertions_text = "\n".join(f"- {item}" for item in case["assertions"])
    return (
        'Return only JSON: {"results":[{"assertion":string,"verdict":"PASS"|'
        '"FAIL","evidence":string}]}\n'
        f"Evaluate these assertions:\n{assertions_text}\nExpected output: "
        f"{case['expected_output']}\nTranscript:\n{transcript}"
    )


def _tokens(value):
    usage = value.get("usage")
    keys = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    numbers = [
        usage[key]
        for key in keys
        if isinstance(usage, dict) and type(usage.get(key)) is int and usage[key] >= 0
    ]
    return bool(numbers), sum(numbers)


def _benchmark(skill_dir, iteration, request, records):
    serialized = [
        {
            "eval_id": record.eval_id,
            "config": record.config.value,
            "run": record.run,
            "outcome": record.outcome.value,
            "total_assertions": record.total_assertions,
            "passed_assertions": record.passed_assertions,
            "pass_rate": record.pass_rate,
            "duration_ms": record.duration_ms,
            "measured_tokens": record.measured_tokens,
            "cost_usd": record.cost_usd,
            "blocked": record.blocked,
            "assertions": record.assertions,
            "cost": record.cost,
        }
        for record in records
    ]
    return {
        "skill": str(skill_dir),
        "iteration": iteration,
        "harness": request.harness.value,
        "model": request.model
        or ("gpt-6-luna" if request.harness is OutputHarness.CODEX else None),
        "judge_model": request.judge_model
        or request.model
        or ("gpt-6-luna" if request.harness is OutputHarness.CODEX else None),
        "result": paired.summarize(serialized),
        "records": serialized,
    }


def _record_passes(record):
    return (
        record.outcome is EvalOutcome.COMPLETED
        and record.total_assertions > 0
        and record.passed_assertions == record.total_assertions
    )


def _record_fails_assertions(record):
    return (
        record.outcome is EvalOutcome.COMPLETED
        and record.total_assertions > 0
        and record.passed_assertions < record.total_assertions
    )


def _validate_mutation(item):
    if (
        not isinstance(item, dict)
        or not isinstance(item.get("id"), str)
        or not item["id"].strip()
        or not isinstance(item.get("evals"), list)
        or not item["evals"]
    ):
        raise ValueError(
            f"mutation must have an id and evals: "
            f"{item.get('id', '') if isinstance(item, dict) else ''}"
        )
    relative = Path(item.get("file", ""))
    if (
        not item.get("file")
        or relative.is_absolute()
        or any(part in {".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"invalid mutation file path: {item.get('file', '')}")
    if not isinstance(item.get("remove"), str):
        raise ValueError(f"mutation {item['id']} must specify remove text")
