"""Lint agent-facing Markdown files and skill directories."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path

import yaml
from varde_core.envelope import negative_result, success, tool_error
from varde_core.layout import skill_dirs
from varde_core.text_audit import (
    Finding,
    Severity,
    audit,
    eval_content,
    expand_skill_dir,
    skill_refs,
    skill_spec,
)

from varde_learn.docs.flow.scan import text_tokens

HOW_TOKEN_CAP = 300
HOW_SUMMARY_MAX = 100
EVAL_SKIPPED = frozenset({"trigger-queries.json", "mutations.json"})
_HOW_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


class InputError(Exception):
    """A missing, unreadable, or empty lint input."""


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class Report:
    findings: list[Finding]
    files: int

    def errors(self) -> int:
        return sum(finding.severity is Severity.ERROR for finding in self.findings)

    def warnings(self) -> int:
        return sum(finding.severity is Severity.WARN for finding in self.findings)

    def render_text(self) -> str:
        lines = []
        for finding in self.findings:
            label = "ERROR" if finding.severity is Severity.ERROR else "WARN "
            lines.append(f"{label} {finding.path}:{finding.line} {finding.message}")
        lines.append(
            (  # noqa: UP034 - Explicit grouping is required for split output text.
                f"{self.errors()} error(s), {self.warnings()} warning(s) across "
                f"{self.files} file(s)."
            )
        )
        return "\n".join(lines) + "\n"


class HowRule(StrEnum):
    """Rules specific to how topic files (``<pkg>/how/<skill>/<step>.md``)."""

    SCHEMA = "how-schema"
    SUMMARY = "how-summary"
    TOKENS = "how-tokens"


def is_how_file(path: Path) -> bool:
    return path.suffix == ".md" and path.parent.parent.name == "how"


def _expand_how_dir(path: Path) -> list[Path] | None:
    """Topic files under a ``how`` tree or one skill's ``how`` directory."""
    if path.name == "how":
        return sorted(path.glob("*/*.md"))
    if path.parent.name == "how":
        return sorted(path.glob("*.md"))
    return None


def _how_finding(path: str, rule: HowRule, message: str) -> Finding:
    return Finding(path, 1, rule, Severity.ERROR, message)  # type: ignore[arg-type]


def _check_how_meta(path: Path, meta: object) -> list[Finding]:
    shown = str(path)
    if not isinstance(meta, dict):
        return [_how_finding(shown, HowRule.SCHEMA, "frontmatter is not a mapping")]
    found = []
    expected = f"{path.parent.name}/{path.stem}"
    if meta.get("topic") != expected:
        found.append(
            _how_finding(shown, HowRule.SCHEMA, f"`topic` must be `{expected}`")
        )
    version = meta.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        found.append(
            _how_finding(shown, HowRule.SCHEMA, "`version` must be a positive integer")
        )
    summary = meta.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        found.append(
            _how_finding(shown, HowRule.SCHEMA, "`summary` must be a non-empty string")
        )
    elif len(summary) > HOW_SUMMARY_MAX:
        found.append(
            _how_finding(
                shown,
                HowRule.SUMMARY,
                f"`summary` is {len(summary)} chars, max is {HOW_SUMMARY_MAX}",
            )
        )
    unknown = sorted(
        str(key) for key in meta if key not in {"topic", "version", "summary"}
    )
    if unknown:
        found.append(
            _how_finding(
                shown,
                HowRule.SCHEMA,
                f"unknown frontmatter field(s): {', '.join(unknown)}",
            )
        )
    return found


def lint_how(path: Path, text: str) -> list[Finding]:
    """Frontmatter schema, summary length, and body token cap for a topic file."""
    shown = str(path)
    match = _HOW_FRONTMATTER.match(text)
    if match is None:
        return [_how_finding(shown, HowRule.SCHEMA, "missing `---` frontmatter")]
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as error:
        return [
            _how_finding(shown, HowRule.SCHEMA, f"frontmatter is not YAML: {error}")
        ]
    found = _check_how_meta(path, meta)
    size = text_tokens(match.group(2).strip("\n"))
    if size > HOW_TOKEN_CAP:
        found.append(
            _how_finding(
                shown,
                HowRule.TOKENS,
                f"body is ~{size} tokens, over the {HOW_TOKEN_CAP}-token cap",
            )
        )
    return found


def _expand(path: Path) -> list[Path]:
    if path.is_dir():
        how = _expand_how_dir(path)
        if how is not None:
            return how
        return expand_skill_dir(path)
    if path.is_file():
        return [path]
    raise InputError(f"varde learn check: no such file or directory: {path}")


def _eval_files(path: Path) -> list[Path]:
    """Assertion files in `evals/` of a skill dir or its SKILL.md."""
    if path.name == "SKILL.md" and path.is_file():
        return _eval_files(path.parent)
    if not (path.is_dir() and (path / "SKILL.md").is_file()):
        return []
    return sorted(
        file
        for file in (path / "evals").glob("*.json")
        if file.name not in EVAL_SKIPPED
    )


def _skill_root(file: Path) -> Path | None:
    """The skill directory holding a file, or None for other documents."""
    for parent in file.resolve().parents:
        if (parent / "SKILL.md").is_file():
            return parent
    return None


@cache
def _known_skills(root: Path) -> frozenset[str]:
    """Skill names beside this skill and in its repository checkout."""
    names = {path.name for path in root.parent.glob("varde-*") if path.is_dir()}
    for parent in root.parents:
        if (parent / "layers.toml").is_file():
            names.update(skill_dirs(parent))
            break
    return frozenset(names)


def _skill_ref_findings(file: Path, text: str) -> list[Finding]:
    root = _skill_root(file)
    if root is None or is_how_file(file):
        return []
    return skill_refs(text, str(file), root.name, _known_skills(root))


def _skill_spec_findings(file: Path, text: str) -> list[Finding]:
    if file.name != "SKILL.md" or is_how_file(file):
        return []
    match = _HOW_FRONTMATTER.match(text)
    try:
        meta = yaml.safe_load(match.group(1)) if match else None
    except yaml.YAMLError:
        meta = None
    return skill_spec(
        meta, file.resolve().parent.name, str(file), len(text.splitlines())
    )


def lint(paths: list[Path]) -> Report:
    files: list[Path] = []
    for path in paths:
        files.extend(_expand(path))
    if not files:
        raise InputError("varde learn check: no Markdown files found")

    findings: list[Finding] = []
    eval_files = [file for path in paths for file in _eval_files(path)]
    for file in eval_files:
        try:
            findings.extend(eval_content(file.read_text(encoding="utf-8"), str(file)))
        except (OSError, UnicodeError) as error:
            raise InputError(f"varde learn check: {file}: {error}") from error
    for file in files:
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise InputError(f"varde learn check: {file}: {error}") from error
        findings.extend(audit(text, str(file)))
        findings.extend(_skill_ref_findings(file, text))
        findings.extend(_skill_spec_findings(file, text))
        if is_how_file(file):
            findings.extend(lint_how(file, text))
    return Report(findings, len(files) + len(eval_files))


def json_envelope(report: Report) -> dict[str, object]:
    meta = {"truncated": False}
    data = {
        "findings": [
            {
                **asdict(finding),
                "rule": finding.rule.value,
                "severity": finding.severity.value,
            }
            for finding in report.findings
        ]
    }
    if report.errors() == 0:
        return success(data, meta)
    message = (
        f"{report.errors()} error(s), {report.warnings()} warning(s) "
        f"across {report.files} file(s)"
    )
    return negative_result("doc_lint_errors", message, data, meta)


def run(
    paths: list[Path], *, json_output: bool = False, stdout=None, stderr=None
) -> int:
    """Run lint, writing output streams and returning the CLI status."""
    import sys

    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    try:
        report = lint(paths)
    except InputError as error:
        message = (
            tool_error("doc_lint_input", str(error)) if json_output else str(error)
        )
        print(
            _json_text(message) if json_output else message,
            file=stderr,
        )
        return 2
    if json_output:
        print(_json_text(json_envelope(report)), file=stdout)
    else:
        print(report.render_text(), end="", file=stdout)
    return 1 if report.errors() else 0
