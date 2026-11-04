"""Pure protocol functions for the baseline agreement driver (no I/O, no model calls).

Cell plan, call and token counting, agreement decision, cap check, token
estimate, prompts and the usage-ledger line schema.

Ledger line schema (``notes/usage-ledger.jsonl``, one JSON object per line):

- intent: ``{"kind": "intent", "run", "key", "client", "role", "cell",
  "prompt_chars", "est_tokens", "ts"}`` written BEFORE every call.
- result: ``{"kind": "result", "run", "key", "client", "role", "cell",
  "outcome": "ok" | "error" | "limit", "tokens", "estimated", "output_chars",
  "ts"}`` written after the call.
- limit: ``{"kind": "limit", "client", "resume_after", "ts"}`` (epoch seconds).
- probe: ``{"kind": "probe", "client", "overhead_tokens", "ts"}``.

An intent without a result for the same (run, key, attempt order) counts as a
call with its ``est_tokens`` (fail closed).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

MAX_CALLS = 200
MAX_TOKENS = 1_500_000
MAX_REPAIRS = 2
PROBE_CALLS = 4
DEFAULT_OVERHEAD_TOKENS = 7_500  # plan figure until probes measure it

PROBLEMS = ("recurring-orders", "job-scheduler", "report-pipeline", "notifier")
LANGUAGES = ("python", "typescript", "csharp")
BASES = ("clean-code", "aposd", "modern")
LENS_FILES = {
    "clean-code": "lens-1-clean-code.md",
    "aposd": "lens-2-philosophy-of-software-design.md",
    "modern": "lens-3-modern-practice-cognitive-load.md",
}
FAMILIES = ("luna", "sonnet")

# Rough characters per role for the dry-run projection (prompt, output).
ROLE_CHARS = {
    "write": (6_000, 8_000),
    "repair": (12_000, 8_000),
    "conflicts": (26_000, 2_000),
    "case": (28_000, 3_000),
    "ruling": (40_000, 10_000),
    "fix": (14_000, 8_000),
}
# A typical cell has conflicts that involve two of the three schools.
TYPICAL_CELL_ROLES = ("write",) * 3 + ("conflicts",) + ("case",) * 2 + ("ruling",)


@dataclass(frozen=True)
class Cell:
    problem: str
    language: str

    @property
    def key(self) -> str:
        return f"{self.language}/{self.problem}"


def all_cells() -> list[Cell]:
    return [Cell(p, lang) for lang in LANGUAGES for p in PROBLEMS]


def parse_cells(spec: str) -> list[Cell]:
    """``all`` or comma-separated ``language/problem`` keys."""
    cells = all_cells()
    if spec == "all":
        return cells
    by_key = {cell.key: cell for cell in cells}
    wanted = [part.strip() for part in spec.split(",") if part.strip()]
    unknown = [key for key in wanted if key not in by_key]
    if unknown:
        raise ValueError(f"unknown cells: {', '.join(unknown)}")
    return [by_key[key] for key in wanted]


def other_family(family: str) -> str:
    return FAMILIES[1 - FAMILIES.index(family)]


def writer_families(index: int) -> dict[str, str]:
    """Base -> family: Luna writes clean-code and modern on even cells."""
    even = index % 2 == 0
    return {
        "clean-code": "luna" if even else "sonnet",
        "aposd": "sonnet" if even else "luna",
        "modern": "luna" if even else "sonnet",
    }


def judge_family(index: int) -> str:
    return "sonnet" if index % 2 == 0 else "luna"


def max_agreement_calls() -> int:
    """3 writes, 2 repairs, 1 conflicts, 3 cases, 1 ruling, and 1 fix."""
    return len(BASES) + MAX_REPAIRS + 1 + len(BASES) + 1 + 1


def planned_calls(cell_count: int) -> dict[str, int]:
    agreement = cell_count * max_agreement_calls()
    return {
        "agreement": agreement,
        "probes": PROBE_CALLS,
        "total": agreement + PROBE_CALLS,
        "typical_total": cell_count * len(TYPICAL_CELL_ROLES) + PROBE_CALLS,
    }


def estimate_tokens(prompt_chars: int, output_chars: int, overhead: int) -> int:
    """chars/4 of prompt and output plus the per-call overhead."""
    return math.ceil((prompt_chars + output_chars) / 4) + overhead


def projected_tokens(cell_count: int, overhead: int) -> dict[str, int]:
    """Typical (7 calls per cell) and worst-case (11) projections."""

    def role_tokens(role: str) -> int:
        prompt, output = ROLE_CHARS[role]
        return estimate_tokens(prompt, output, overhead)

    typical_cell = sum(role_tokens(r) for r in TYPICAL_CELL_ROLES)
    probes = PROBE_CALLS * estimate_tokens(500, 200, overhead)
    worst_cell = (
        typical_cell
        + MAX_REPAIRS * role_tokens("repair")
        + role_tokens("case")
        + role_tokens("fix")
    )
    return {
        "typical": cell_count * (typical_cell) + probes,
        "worst_case": cell_count * (worst_cell) + probes,
    }


def billed_tokens(usage: Mapping[str, int]) -> int:
    """Billed input (incl. cache creation and read) plus output."""
    keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return sum(int(usage.get(k, 0) or 0) for k in keys) + int(
        usage.get("output_tokens", 0) or 0
    )


# ---- ledger ------------------------------------------------------------------


@dataclass(frozen=True)
class Totals:
    calls: int
    tokens: int
    estimated_calls: int


def ledger_totals(lines: Iterable[Mapping]) -> Totals:
    """Each intent is one call. Tokens come from its result, else its estimate.

    A result pairs with the latest unpaired intent of the same run and key, so
    an earlier crashed attempt keeps its estimate.
    """
    calls: list[list] = []  # [intent, result or None]
    open_by_key: dict[tuple, list[list]] = {}
    for line in lines:
        kind = line.get("kind")
        if kind == "intent":
            entry = [line, None]
            calls.append(entry)
            open_by_key.setdefault((line["run"], line["key"]), []).append(entry)
        elif kind == "result":
            waiting = open_by_key.get((line["run"], line["key"]))
            if waiting:
                waiting.pop()[1] = line
    tokens = estimated = 0
    for intent, result in calls:
        if result is None:
            tokens += int(intent["est_tokens"])
            estimated += 1
            continue
        tokens += int(result["tokens"])
        estimated += 1 if result.get("estimated") else 0
    return Totals(len(calls), tokens, estimated)


def calls_after_limit(lines: Iterable[Mapping]) -> list[str]:
    """Keys of intents written for a client before its recorded resume_after."""
    limits: dict[str, float] = {}
    bad: list[str] = []
    for line in lines:
        kind = line.get("kind")
        if kind == "limit":
            limits[line["client"]] = float(line["resume_after"])
        elif kind == "intent" and float(line["ts"]) < limits.get(line["client"], 0.0):
            bad.append(f"{line['client']}:{line['key']}")
    return bad


def check_cap(
    totals: Totals,
    next_tokens: int,
    max_calls: int = MAX_CALLS,
    max_tokens: int = MAX_TOKENS,
) -> str | None:
    """Reason to refuse one more call, or None."""
    if totals.calls + 1 > max_calls:
        return f"call cap: {totals.calls} used of {max_calls}"
    if totals.tokens + next_tokens > max_tokens:
        return (
            f"token cap: {totals.tokens} used + {next_tokens} estimated"
            f" exceeds {max_tokens}"
        )
    return None


def done_keys(lines: Iterable[Mapping], run: str) -> set[str]:
    return {
        line["key"]
        for line in lines
        if line.get("kind") == "result"
        and line.get("run") == run
        and line.get("outcome") == "ok"
    }


def active_limits(lines: Iterable[Mapping], now: float) -> dict[str, float]:
    """Client -> latest recorded resume_after still in the future."""
    latest: dict[str, float] = {}
    for line in lines:
        if line.get("kind") == "limit":
            latest[line["client"]] = float(line["resume_after"])
    return {client: at for client, at in latest.items() if at > now}


def measured_overhead(lines: Iterable[Mapping]) -> int | None:
    values = sorted(
        int(line["overhead_tokens"]) for line in lines if line.get("kind") == "probe"
    )
    return values[len(values) // 2] if values else None


# ---- agreement decision --------------------------------------------------------


FENCE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)


def extract_code(reply: str) -> str | None:
    """The largest fenced block of a reply, or None."""
    blocks = FENCE.findall(reply)
    return max(blocks, key=len) if blocks else None


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- prompts (problem text, spec, idiom notes, lens, code only) --------------------


@dataclass(frozen=True)
class ProblemText:
    prompt: str
    spec: str
    api: str
    idiom: str


def _brief(text: ProblemText, language: str) -> str:
    return (
        f"Problem: {text.prompt.strip()}\n\nBehaviour spec:\n{text.spec.strip()}\n\n"
        f"API names:\n{text.api.strip()}\n\nLanguage idiom notes ({language}):\n"
        f"{text.idiom.strip()}\n"
    )


def lens_principles(lens_file: str) -> str:
    """Only the principles of a rater lens file (no pairwise rubric or JSON schema)."""
    match = re.search(
        r"^## Lens\s*\n(.*?)(?=^## |\Z)", lens_file, re.MULTILINE | re.DOTALL
    )
    return (match.group(1) if match else lens_file).strip()


@dataclass(frozen=True)
class Persona:
    name: str
    school: str
    values: str
    trades: str


PERSONAS = {
    "clean-code": Persona(
        "a Clean Code practitioner",
        "Robert C. Martin's Clean Code",
        (
            "small functions that each do one nameable thing, one level of abstraction "
            "per function, names that let a reader skip the callee, few arguments, no "
            "duplication, and code that reads top-down"
        ),
        (
            "total line count, a few extra small functions, and some indirection, as "
            "long as every extraction adds meaning"
        ),
    ),
    "aposd": Persona(
        "a follower of A Philosophy of Software Design",
        "John Ousterhout's A Philosophy of Software Design",
        (
            "deep modules (much work behind a simple interface), information hiding, "
            "low change amplification and low cognitive load, with complexity pulled "
            "downward"
        ),
        (
            "function count and the one-thing-per-function rule: it will keep a longer "
            "function whole, and merge shallow or entangled pieces"
        ),
    ),
    "modern": Persona(
        "a modern-practice, cognitive-load practitioner",
        "modern code-review and readability practice (code health, cognitive load)",
        (
            "the simplest code a new reader can follow quickly: shallow nesting, "
            "linear flow, few names and states in mind at once, no speculative "
            "generality, comments that explain why"
        ),
        (
            "both fine-grained decomposition and deep-module doctrine: it accepts "
            "either shape when the control flow stays simple and the code is no "
            "bigger than the present need"
        ),
    ),
}

PRIORITIES = "must-keep / strong / flexible"


def persona_text(base: str, lens: str) -> str:
    """Who the expert is, what they value and trade, and the lens principles."""
    persona = PERSONAS[base]
    return (
        f"You are {persona.name}, a committed practitioner of {persona.school}.\n"
        f"You value most: {persona.values}.\n"
        f"You will trade away: {persona.trades}.\n\n"
        f"Your numbered principles:\n{lens_principles(lens)}\n"
    )


def writer_prompt(text: ProblemText, language: str, base: str, lens: str) -> str:
    return (
        f"{persona_text(base, lens)}\nWrite the best {language} solution to this "
        "problem, in one file: the code a practitioner of your school would write, "
        "passing the behaviour spec below. Reply with one fenced code block "
        f"only.\n\n{_brief(text, language)}"
    )


def repair_prompt(language: str, code: str, test_output: str) -> str:
    return (
        f"This {language} solution fails its behaviour tests. Fix it and reply "
        f"with one fenced code block only.\n\nCode:\n```\n{code}```\n\n"
        f"Test output:\n{test_output[-3000:]}\n"
    )


def _metrics_json(metrics: Mapping) -> str:
    return json.dumps(metrics, sort_keys=True)


def _versions_block(versions: Mapping[str, str], metrics: Mapping[str, Mapping]) -> str:
    return "\n".join(
        f"\nVersion {base} (metrics {_metrics_json(metrics.get(base, {}))}):\n"
        f"```\n{code}```"
        for base, code in versions.items()
    )


def conflicts_prompt(
    language: str, versions: Mapping[str, str], metrics: Mapping[str, Mapping]
) -> str:
    schools = ", ".join(versions)
    return (
        f"Below are passing {language} versions of one program, each written by a "
        "practitioner of a different school of design, with measured metrics. "
        "List the real design conflicts between them. Skip cosmetic differences. "
        "Write one line per conflict, numbered, in this form:\n"
        "N. <topic> | schools: <the schools in conflict, from "
        f"{schools}> | metric: <the metric affected> | <what is at stake>\n"
        "Reply with the numbered lines only, with no code block. If there is no "
        "real conflict, reply 'no conflicts'.\n"
        + _versions_block(versions, metrics)
        + "\n"
    )


@dataclass(frozen=True)
class Conflict:
    number: str
    text: str
    schools: tuple[str, ...]


CONFLICT_LINE = re.compile(r"^\s*(\d+)[.)]\s*(.+?)\s*$", re.MULTILINE)
SCHOOLS_FIELD = re.compile(r"schools?\s*:\s*([^|\n]*)", re.IGNORECASE)


def _bases_in(text: str) -> tuple[str, ...]:
    return tuple(
        base
        for base in BASES
        if re.search(rf"(?<![\w-]){re.escape(base)}(?![\w-])", text, re.IGNORECASE)
    )


def parse_conflicts(reply: str) -> list[Conflict]:
    """Numbered conflict lines with their party schools; none for 'no conflicts'.

    A line that names no known school is a conflict among all schools.
    """
    conflicts = []
    for number, text in CONFLICT_LINE.findall(reply):
        field = SCHOOLS_FIELD.search(text)
        schools = _bases_in(field.group(1)) if field else ()
        conflicts.append(Conflict(number, text, schools or BASES))
    return conflicts


def conflict_parties(conflicts: Sequence[Conflict]) -> list[str]:
    """Schools that are a party to at least one conflict, in BASES order."""
    return [base for base in BASES if any(base in c.schools for c in conflicts)]


def case_prompt(
    base: str,
    lens: str,
    language: str,
    versions: Mapping[str, str],
    metrics: Mapping[str, Mapping],
    conflicts: str,
) -> str:
    return (
        f"{persona_text(base, lens)}\nA judge will rule on the conflicts between "
        f"the {language} versions below and write the final version. Conflicts:\n"
        f"{conflicts.strip()}\n"
        f"\nYour school is '{base}'. For each numbered conflict that names your "
        "school, state what you want and why it is warranted, citing your "
        "principle numbers and the evidence in the code (name the function or "
        f"line). Give each issue a priority ({PRIORITIES}) and state what you "
        "would trade. Not every conflict matters equally to you; mark only what "
        "you truly need as must-keep. Reply with a short numbered list only, with "
        "no code block.\n" + _versions_block(versions, metrics) + "\n"
    )


def ruling_prompt(
    language: str,
    versions: Mapping[str, str],
    metrics: Mapping[str, Mapping],
    conflicts: str,
    cases: Mapping[str, str],
) -> str:
    parts = [
        (
            f"You are the judge. Below are passing {language} versions of one "
            "program with measured metrics, the conflicts between them, and the "
            "case each involved expert filed. The experts do not need to agree. "
            "For each issue, weigh the validity and the evidence of every case "
            "against the code and the principles it cites; do not side with an "
            "expert automatically. Reject a case that is not warranted by its "
            "expert's principles and the code. First give one ruling per issue as "
            "a line: issue, decision (upheld / partly upheld / rejected), reason. "
            "If there are no conflicts, give one line stating that you merged the "
            "versions. Then end your reply with one fenced code block holding the "
            "final file: a single version that mostly satisfies all parties and "
            "keeps the behaviour tests passing."
        ),
        _versions_block(versions, metrics),
        f"\nConflicts:\n{conflicts.strip()}",
    ]
    for base, case in cases.items():
        parts.append(f"\nCase of the {PERSONAS[base].school} expert:\n{case.strip()}")
    return "\n".join(parts) + "\n"


def split_ruling(reply: str) -> tuple[str, str | None]:
    """(per-issue rulings text without the code, final code or None)."""
    return FENCE.sub("", reply).strip(), extract_code(reply)


def fix_prompt(language: str, merged: str, test_output: str) -> str:
    return repair_prompt(language, merged, test_output)


def _is_agreed(entry: Mapping) -> bool:
    """Agreed with passing tests; a judge ruling must carry its rulings text."""
    if entry.get("agreed") is not True or entry.get("tests_passed") is not True:
        return False
    return entry.get("status") != "judge_ruled" or bool(
        str(entry.get("rulings", "")).strip()
    )


def check_agreement_entries(
    entries: Mapping[str, Mapping], min_per_language: int, min_total: int
) -> list[str]:
    """Problems with an agreement summary; empty list means it passes."""
    problems: list[str] = []
    total = 0
    for language in LANGUAGES:
        good = sum(
            1
            for key, entry in entries.items()
            if key.startswith(f"{language}/") and _is_agreed(entry)
        )
        total += good
        if good < min_per_language:
            problems.append(f"{language}: {good} agreed cells, need {min_per_language}")
    if total < min_total:
        problems.append(f"total: {total} agreed cells, need {min_total}")
    return problems
