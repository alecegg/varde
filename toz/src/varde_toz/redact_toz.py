"""Capture redaction and never-capture rules."""

from __future__ import annotations

import os
import re
from pathlib import Path

from varde_core.redact import RedactConfig, Redactor, SecretValue

from .config import load_config

BUILTIN_NEVER = (
    "env",
    "printenv",
    "printenv *",
    "cat *.env*",
    "gh auth token*",
    "*secret*",
    "aws configure *",
    "kubectl get secret*",
)


def never_capture(
    source: str, patterns: list[str] | tuple[()] = (), builtin: bool = True
) -> str | None:
    value = source.strip()
    rules = (BUILTIN_NEVER if builtin else ()) + tuple(patterns)
    for pattern in rules:
        if re.fullmatch(re.escape(pattern).replace(r"\*", ".*"), value, re.IGNORECASE):
            return "never-capture"
    return None


def redact_capture(
    text: str, *, builtin: bool = True, patterns: list[str] | tuple[str, ...] = ()
):
    result = Redactor(RedactConfig(builtin=builtin, patterns=patterns)).redact(text)
    return result.text, sum(n.count for n in result.notices)


def configured_redactor(root: Path):
    config = load_config()
    section = config.get("redact", {})
    section = section if isinstance(section, dict) else {}
    patterns = section.get("patterns", [])
    if not isinstance(patterns, list) or not all(
        isinstance(item, str) for item in patterns
    ):
        raise ValueError("redact.patterns must be an array of strings")
    values: dict[str, str] = {}
    if section.get("values", True):
        values.update(
            {
                name: value
                for name, value in os.environ.items()
                if re.search(
                    r"(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY)",
                    name,
                    re.IGNORECASE,
                )
                and value
            }
        )
        for path in sorted(root.glob(".env*")):
            values.update(_dotenv_values(path))
        for raw_path in section.get("dotenv", []):
            path = Path(raw_path)
            values.update(_dotenv_values(path if path.is_absolute() else root / path))
    return {
        "builtin": section.get("builtin", True) is not False,
        "patterns": patterns,
        "values": values,
        "reveal": section.get("reveal", 2),
        "capture": config.get("capture", {}),
    }


def _dotenv_values(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return {}
    result = {}
    for line in text.splitlines():
        match = re.match(
            r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line
        )
        if match:
            value = match.group(2).strip("\"'")
            if value and re.search(
                r"(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY)",
                match.group(1),
                re.IGNORECASE,
            ):
                result[match.group(1)] = value
    return result


def redact_configured(text: str, config: dict):
    values = [SecretValue(name, value) for name, value in config["values"].items()]
    result = Redactor(
        RedactConfig(
            builtin=config["builtin"],
            patterns=config["patterns"],
            values=values,
            reveal=config["reveal"],
        )
    ).redact(text)
    return result.text, sum(notice.count for notice in result.notices)
