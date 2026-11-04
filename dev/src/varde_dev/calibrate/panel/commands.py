"""Run panel prompts with an explicitly opted-in, isolated client process."""

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC
from pathlib import Path
from typing import Any, Never

from varde_dev.calibrate.panel.logic import (
    RunLogRecord,
    assemble_prompt,
    build_call_specs,
    build_codex_command,
    check_hygiene,
    claude_code_command,
    client_identity,
    map_verdict,
    opaque_pair_id,
    parse_response,
    pi_command,
    run_log_record,
)
from varde_dev.calibrate.panel.window import load_current_window


def _raise(error: Exception) -> Never:
    raise error


MAX_SNIPPET_BYTES = 64 * 1024
_KNOWN_CREDENTIALS = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z_][A-Za-z0-9_]*(?:KEY|SECRET|PASSWORD|TOKEN))\b\s*[:=]\s*"
    r"(?:['\"])?([A-Za-z0-9_+/=-]{20,})"
)
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "string", "enum": ["A", "B", "tie"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["choice", "confidence"],
    "additionalProperties": False,
}


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], dt.datetime] | None = None,
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        default_repeats = {"development": 2, "acceptance": 3}[args.mode]
        args.repeats = default_repeats if args.repeats is None else args.repeats
        if args.repeats < default_repeats:
            _raise(
                ValueError(
                    f"{args.mode} mode requires at least {default_repeats} repeats "
                    "per order"
                )
            )
        return _run(args, clock or (lambda: dt.datetime.now(UTC)))
    except (
        OSError,
        ValueError,
        TypeError,
        NotImplementedError,
        tomllib.TOMLDecodeError,
    ) as error:
        print(f"calibrate rate: {error}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m varde_dev.calibrate rate")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--lens", type=Path, required=True)
    parser.add_argument("--idiom-notes", type=Path, required=True)
    parser.add_argument(
        "--client", choices=("codex", "pi", "claude-code"), default="codex"
    )
    parser.add_argument("--client-path", default="codex")
    parser.add_argument("--repeats", type=int)
    parser.add_argument(
        "--mode", choices=("acceptance", "development"), default="development"
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--window-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--abort-on-secret", action="store_true")
    return parser


def _run(args: argparse.Namespace, clock: Callable[[], dt.datetime]) -> int:
    lens_body = args.lens.read_text(encoding="utf-8")
    idiom_notes = args.idiom_notes.read_text(encoding="utf-8")
    pairs = _load_pairs(args.dataset)
    prompts: list[tuple[dict[str, str], str, str, int]] = []
    excluded: list[dict[str, object]] = []
    for pair in pairs:
        hygiene = check_hygiene(pair["a_code"], pair["b_code"], pair["task"])
        if hygiene["excluded"]:
            excluded.append(
                {"pair_id": pair["judge_pair_id"], "reasons": hygiene["reasons"]}
            )
            continue
        secret_hits = scan_secrets(
            (pair["a_code"], pair["b_code"], pair["task"], lens_body, idiom_notes)
        )
        if secret_hits:
            if args.abort_on_secret:
                raise ValueError(f"secret-like content found in pair {pair['pair_id']}")
            excluded.append(
                {"pair_id": pair["judge_pair_id"], "reasons": ["secret-like content"]}
            )
            continue
        _check_snippet_size(pair["a_code"])
        _check_snippet_size(pair["b_code"])
        prompts.extend(
            (
                pair,
                assemble_prompt(
                    lens_body,
                    idiom_notes,
                    pair["task"],
                    (pair["judge_pair_id"], pair["a_code"], pair["b_code"]),
                    call["order"],
                ),
                call["order"],
                call["repeat"],
            )
            for call in build_call_specs(args.repeats)
        )
    if not prompts and not excluded:
        raise ValueError("no eligible pair calls")
    if args.dry_run:
        _print_dry_run(prompts, excluded, args.client)
        return 0
    if not prompts:
        _write_exclusion_manifest(args, excluded, clock)
        return 0

    window = _require_live_window(args, len(prompts), clock)
    run_id = _validated_run_id(args.run_id or clock().strftime("rate-%Y%m%dT%H%M%SZ"))
    _ensure_run_id_available(args.dataset, run_id)
    adapter = client_identity(args.client)
    executable = _resolve_executable(args.client, args.client_path)
    statement = _data_sent_statement(prompts, adapter, lens_body, idiom_notes)
    print(json.dumps(statement, sort_keys=True), flush=True)
    _execute_run(
        {
            "args": args,
            "adapter": adapter,
            "lens_name": args.lens.stem,
            "run_id": run_id,
            "prompts": prompts,
            "excluded": excluded,
            "executable": executable,
            "lens_body": lens_body,
            "idiom_notes": idiom_notes,
            "statement": statement,
            "window": window,
            "clock": clock,
        }
    )
    return 0


def scan_secrets(snippets: Sequence[str]) -> list[str]:
    """Find recognizable credentials and high-entropy secret assignments."""
    findings: list[str] = []
    for snippet in snippets:
        findings.extend(
            name for name, pattern in _KNOWN_CREDENTIALS if pattern.search(snippet)
        )
        findings.extend(
            f"assignment:{match.group(1)}"
            for match in _SECRET_ASSIGNMENT.finditer(snippet)
            if _shannon_entropy(match.group(2)) >= 3.5
        )
    return findings


def _shannon_entropy(value: str) -> float:
    return -sum(
        (count / len(value)) * math.log2(count / len(value))
        for count in (value.count(char) for char in set(value))
    )


def _check_snippet_size(snippet: str) -> None:
    if len(snippet.encode("utf-8")) > MAX_SNIPPET_BYTES:
        raise ValueError(f"snippet exceeds {MAX_SNIPPET_BYTES} byte transfer limit")


def _require_live_window(
    args: argparse.Namespace,
    call_count: int,
    clock: Callable[[], dt.datetime],
) -> dict[str, Any]:
    if os.environ.get("VARDE_CALIBRATE_ALLOW_LIVE") != "1":
        raise ValueError("live rating requires VARDE_CALIBRATE_ALLOW_LIVE=1")
    if args.window_file is None:
        raise ValueError("live rating requires explicit --window-file")
    window = load_current_window(args.window_file, clock())
    if call_count > window["cap_per_hour"]:
        raise ValueError("planned call count exceeds usage window cap_per_hour")
    return window


def _resolve_executable(client: str, configured_path: str) -> Path:
    if client == "pi":
        pi_command()
    if client == "claude-code":
        claude_code_command()
    resolved = (
        shutil.which(configured_path)
        if not Path(configured_path).is_absolute()
        else configured_path
    )
    if resolved is None:
        raise ValueError(f"Codex executable not found: {configured_path}")
    path = Path(resolved).resolve()
    if not path.is_file():
        raise ValueError(f"Codex executable is not a file: {path}")
    return path


def _client_environment(executable: Path) -> dict[str, str]:
    environment = {"PATH": str(executable.parent), "LC_ALL": "C.UTF-8"}
    if "CODEX_HOME" in os.environ:
        environment["CODEX_HOME"] = os.environ["CODEX_HOME"]
    return environment


def _execute_run(context: Mapping[str, Any]) -> None:
    args = context["args"]
    prompts = context["prompts"]
    executable = context["executable"]
    run_id = context["run_id"]
    judgements: dict[str, list[dict[str, object]]] = {}
    run_directory = args.dataset / "runs"
    run_directory.mkdir(exist_ok=True)
    log_path = run_directory / f"{run_id}.jsonl"
    attempts = 0

    def before_attempt() -> None:
        nonlocal attempts
        window = _require_live_window(args, 1, context["clock"])
        if attempts >= window["cap_per_hour"]:
            raise ValueError("client attempt would exceed usage window cap_per_hour")
        attempts += 1
        context["window"] = window

    with tempfile.TemporaryDirectory(prefix="varde-panel-") as temporary:
        root = Path(temporary)
        work = root / "work"
        work.mkdir()
        schema = root / "response-schema.json"
        schema.write_text(json.dumps(_RESPONSE_SCHEMA), encoding="utf-8")
        context["client_version"] = _client_version(executable, work)
        with log_path.open("x", encoding="utf-8") as log_stream:
            for pair, prompt, spec_order, repeat in prompts:
                raw, parsed, usage = _invoke_with_retry(
                    executable, work, schema, root, prompt, before_attempt
                )
                result = parsed["parsed"] or {}
                judgements.setdefault(pair["judge_pair_id"], []).append(
                    {**result, "order": spec_order}
                )
                record = _make_log(
                    {
                        "run_id": run_id,
                        "pair": pair,
                        "prompt": prompt,
                        "order": spec_order,
                        "seed_index": repeat,
                        "raw": raw,
                        "parsed": parsed,
                        "usage": usage,
                        "timestamp": context["clock"](),
                        "lens_body": context["lens_body"],
                        "idiom_notes": context["idiom_notes"],
                        "lens_name": context["lens_name"],
                        "adapter": context["adapter"],
                        "client_version": context["client_version"],
                    }
                )
                log_stream.write(json.dumps(record, sort_keys=True) + "\n")
                log_stream.flush()
    results = {
        pair_id: map_verdict(calls, args.mode) for pair_id, calls in judgements.items()
    }
    manifest = {
        "run_id": run_id,
        "client": context["adapter"]["client_name"],
        "client_version": context["client_version"],
        "model_id": context["adapter"]["model_id"],
        "data_sent": context["statement"],
        "window": {
            "start": context["window"]["start"].isoformat(),
            "end": context["window"]["end"].isoformat(),
            "cap_per_hour": context["window"]["cap_per_hour"],
            "stop_rule": context["window"]["stop_rule"],
        },
        "excluded": context["excluded"],
        "verdicts": results,
    }
    (args.dataset / "runs" / f"{run_id}.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def _write_exclusion_manifest(
    args: argparse.Namespace,
    excluded: list[dict[str, object]],
    clock: Callable[[], dt.datetime],
) -> None:
    run_id = _validated_run_id(args.run_id or clock().strftime("rate-%Y%m%dT%H%M%SZ"))
    run_directory = args.dataset / "runs"
    run_directory.mkdir(exist_ok=True)
    manifest_path = run_directory / f"{run_id}.json"
    log_path = run_directory / f"{run_id}.jsonl"
    _ensure_run_id_available(args.dataset, run_id)
    manifest_path.write_text(
        json.dumps(
            {"run_id": run_id, "data_sent": None, "excluded": excluded},
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    log_path.write_text("", encoding="utf-8")


def _validated_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        raise ValueError(
            "run id must contain only letters, numbers, dot, underscore, or hyphen"
        )
    return run_id


def _ensure_run_id_available(dataset: Path, run_id: str) -> None:
    run_directory = dataset / "runs"
    if any(
        (run_directory / f"{run_id}.{suffix}").exists() for suffix in ("json", "jsonl")
    ):
        raise ValueError(f"run id already exists: {run_id}")


def _invoke_with_retry(
    executable: Path,
    work: Path,
    schema: Path,
    root: Path,
    prompt: str,
    before_attempt: Callable[[], None],
) -> tuple[str, dict[str, object], dict[str, object]]:
    response_raw = ""
    parsed: dict[str, object] = {"parsed": None, "parse_ok": False, "retry_count": 0}
    usage: dict[str, object] = {
        "tokens_in": None,
        "tokens_out": None,
        "request_id": None,
    }
    for attempt in range(2):
        output = root / f"response-{attempt}.json"
        command = build_codex_command(
            str(executable), str(work), str(schema), str(output)
        )
        before_attempt()
        completed = subprocess.run(  # noqa: S603 - Runs the selected local tool with explicit arguments.
            command,
            input=prompt,
            text=True,
            capture_output=True,
            cwd=work,
            env=_client_environment(executable),
            check=False,
        )
        if completed.returncode:
            raise ValueError(
                f"Codex client failed with exit code {completed.returncode}"
            )
        if re.search(
            r"rate limit|usage limit|quota|too many requests",
            completed.stderr,
            re.IGNORECASE,
        ):
            raise ValueError("client reported a usage limit; stopping this run")
        usage = _add_usage(usage, _event_usage(completed.stdout))
        response_raw = (
            output.read_text(encoding="utf-8") if output.exists() else completed.stdout
        )
        parsed = parse_response(response_raw, attempt)
        if parsed["parse_ok"]:
            break
    return response_raw, parsed, usage


def _client_version(executable: Path, working_directory: Path) -> str:
    result = subprocess.run(  # noqa: S603 - Runs the selected local tool with explicit arguments.
        [str(executable), "--version"],
        text=True,
        capture_output=True,
        cwd=working_directory,
        env=_client_environment(executable),
        check=False,
    )
    if result.returncode:
        raise ValueError(f"client --version failed with exit code {result.returncode}")
    return result.stdout.strip() or result.stderr.strip() or "not-reported"


def _event_usage(events: str) -> dict[str, object]:
    found: dict[str, object] = {
        "tokens_in": None,
        "tokens_out": None,
        "request_id": None,
    }
    keys = {
        "tokens_in": ("tokens_in", "input_tokens", "inputTokens"),
        "tokens_out": ("tokens_out", "output_tokens", "outputTokens"),
        "request_id": ("request_id", "requestId"),
    }
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        records = _nested_mappings(event)
        for target, aliases in keys.items():
            value = next(
                (record[key] for record in records for key in aliases if key in record),
                None,
            )
            if isinstance(value, int) and not isinstance(value, bool):
                found[target] = (found[target] or 0) + value
            elif value is not None:
                found[target] = value
    return found


def _add_usage(
    previous: Mapping[str, object], current: Mapping[str, object]
) -> dict[str, object]:
    combined: dict[str, object] = {}
    for key in ("tokens_in", "tokens_out"):
        values = [
            value
            for value in (previous.get(key), current.get(key))
            if isinstance(value, int)
        ]
        combined[key] = sum(values) if values else None
    combined["request_id"] = current.get("request_id") or previous.get("request_id")
    return combined


def _nested_mappings(value: object) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [
            value,
            *(record for child in value.values() for record in _nested_mappings(child)),
        ]
    if isinstance(value, list):
        return [record for child in value for record in _nested_mappings(child)]
    return []


def _make_log(fields: Mapping[str, Any]) -> RunLogRecord:
    run_id = fields["run_id"]
    pair = fields["pair"]
    prompt = fields["prompt"]
    order = fields["order"]
    seed_index = fields["seed_index"]
    raw = fields["raw"]
    parsed = fields["parsed"]
    timestamp = fields["timestamp"]
    lens_body = fields["lens_body"]
    idiom_notes = fields["idiom_notes"]
    usage = fields["usage"]
    adapter = fields["adapter"]
    value = parsed.get("parsed")
    return run_log_record(
        run_id=run_id,
        pair_id=pair["judge_pair_id"],
        lens=fields["lens_name"],
        lens_sha256=_sha256(lens_body),
        idiom_notes_sha256=_sha256(idiom_notes),
        model_id=adapter["model_id"] or "not-reported",
        provider_version=None,
        client_name=adapter["client_name"],
        client_version=fields["client_version"],
        temperature=None,
        seed=None,
        max_tokens=None,
        top_p=None,
        thinking_settings={"effort": "medium"},
        order=order,
        seed_index=seed_index,
        prompt_sha256=_sha256(prompt),
        system_prompt_sha256=adapter["system_prompt_sha256"],
        response_raw=raw,
        parsed=value if isinstance(value, dict) else None,
        parse_ok=bool(parsed["parse_ok"]),
        retry_count=int(parsed["retry_count"]),
        tokens_in=usage["tokens_in"],
        tokens_out=usage["tokens_out"],
        request_id=usage["request_id"],
        timestamp=timestamp.isoformat(),
    )


def _load_pairs(dataset: Path) -> list[dict[str, str]]:
    items = _read_jsonl(dataset / "items.jsonl")
    units = _read_jsonl(dataset / "units.jsonl")
    tasks = {
        item["id"]: item["description"] for item in _read_jsonl(dataset / "tasks.jsonl")
    }
    item_by_id = {item["id"]: item for item in items}
    pairs: list[dict[str, str]] = []
    for unit in units:
        if unit.get("kind") != "pair":
            continue
        item_a, item_b = (item_by_id[item_id] for item_id in unit["item_ids"])
        if _not_transferable(item_a) or _not_transferable(item_b):
            raise ValueError(f"pair is marked not-for-transfer: {unit['id']}")
        pairs.append(
            {
                "pair_id": unit["id"],
                "judge_pair_id": opaque_pair_id(unit["id"]),
                "a_code": item_a["text"],
                "b_code": item_b["text"],
                "task": tasks[unit["task_id"]],
            }
        )
    return pairs


def _not_transferable(item: Mapping[str, Any]) -> bool:
    metadata = item.get("metadata", {})
    return bool(
        item.get("license") == "not-for-transfer"
        or isinstance(metadata, Mapping)
        and metadata.get("not_for_transfer") is True
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("_record_type") or record.get("record_type"):
            continue
        records.append(record)
    return records


def _print_dry_run(
    prompts: Sequence[tuple[dict[str, str], str, str, int]],
    excluded: list[dict[str, object]],
    client: str,
) -> None:
    payloads = [prompt for _, prompt, _, _ in prompts]
    summary = {
        "client": client,
        "call_count": len(payloads),
        "excluded": excluded,
        "token_estimate_total": sum(
            (len(payload.encode("utf-8")) + 3) // 4 for payload in payloads
        ),
        "token_estimate_per_call": [
            (len(payload.encode("utf-8")) + 3) // 4 for payload in payloads
        ],
    }
    print(json.dumps(summary, sort_keys=True))
    for index, payload in enumerate(payloads, 1):
        print(f"--- payload {index} ---")
        print(payload)


def _data_sent_statement(
    prompts: Sequence[tuple[dict[str, str], str, str, int]],
    adapter: Mapping[str, object],
    lens_body: str,
    idiom_notes: str,
) -> dict[str, object]:
    return {
        "statement": (
            "Only the listed SHA-256 hashes identify data sent: code snippets, task "
            "text, lens rubric, and language idiom notes. No labels, reasons, or raw "
            "snippets are included in this manifest."
        ),
        "pair_ids": sorted({pair["judge_pair_id"] for pair, _, _, _ in prompts}),
        "snippets": [
            {"pair_id": pair["judge_pair_id"], "side": side, "sha256": _sha256(code)}
            for pair, _, _, _ in prompts
            for side, code in (
                ("A", pair["a_code"]),
                ("B", pair["b_code"]),
                ("task", pair["task"]),
            )
        ],
        "lens_sha256": _sha256(lens_body),
        "idiom_notes_sha256": _sha256(idiom_notes),
        "provider": adapter["client_name"],
        "model_id": adapter["model_id"],
    }


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
