"""Shared redaction engine for patterns and literal secret values."""

from __future__ import annotations

import re
from collections import namedtuple
from enum import Enum

BUILTIN: tuple[tuple[str, str], ...] = (
    ("aws-key", r"AKIA[0-9A-Z]{16}"),
    ("aws-secret", r"(?i)aws_secret_access_key\s*[=:]\s*[\"']?[A-Za-z0-9/+=]{40}"),
    ("github", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"),
    ("github-pat", r"\bgithub_pat_[A-Za-z0-9_]{80,}\b"),
    ("api-key", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}\b"),
    ("slack", r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),
    ("bearer", r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{16,}=*"),
    (
        "pem",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    ),
    (
        "env-assign",
        r"(?im)^[^\S\r\n]*(?:export[^\S\r\n]+)?[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY)[A-Z0-9_]*[^\S\r\n]*=(?:[^\S\r\n]|\r?\n)*\S+",
    ),
    ("url-creds", r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s@/]+@"),
)


class Kind(str, Enum):
    PATTERN = "pattern"
    VALUE = "value"


def _record_equal(self, other):
    if type(self) is not type(other):
        return False
    return tuple.__eq__(self, other)


def _record_not_equal(self, other):
    return not _record_equal(self, other)


def _record_type(name, fields, annotations, defaults=()):
    record = namedtuple(name, fields, defaults=defaults, module=__name__)
    record.__annotations__ = annotations
    record.__eq__ = _record_equal
    record.__ne__ = _record_not_equal
    record.__hash__ = tuple.__hash__
    return record


SecretValue = _record_type("SecretValue", "name value", {"name": str, "value": str})
RedactConfig = _record_type(
    "RedactConfig",
    "builtin patterns values reveal",
    {
        "builtin": bool,
        "patterns": tuple[str, ...] | list[str],
        "values": tuple[SecretValue, ...] | list[SecretValue],
        "reveal": int,
    },
    defaults=(True, (), (), 2),
)
Span = _record_type(
    "Span",
    "start end replacement kind",
    {"start": int, "end": int, "replacement": str, "kind": Kind},
)
Notice = _record_type(
    "Notice",
    "kind label count",
    {"kind": Kind, "label": str, "count": int},
)
Redacted = _record_type(
    "Redacted",
    "text notices",
    {"text": str, "notices": list[Notice]},
)
_Rule = _record_type(
    "_Rule",
    "matcher replacement kind label",
    {"matcher": re.Pattern[str] | str, "replacement": str, "kind": Kind, "label": str},
)
_Candidate = _record_type(
    "_Candidate",
    "start end order",
    {"start": int, "end": int, "order": int},
)
_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")


def _value_replacement(reveal: int, name: str, value: str) -> str:
    marker = f"[redacted:value:{name}]"
    if reveal == 0 or len(value) < 4 * reveal + 8:
        return marker
    return f"{value[:reveal]}…{value[-reveal:]}{marker}"


class Redactor:
    """Compiled redaction rules. Invalid user regexes raise ``ValueError``."""

    def __init__(self, cfg: RedactConfig):
        rules: list[_Rule] = []
        if cfg.builtin:
            rules.extend(
                _Rule(re.compile(pattern), f"[redacted:{kind}]", Kind.PATTERN, kind)
                for kind, pattern in BUILTIN
            )
        for pattern in cfg.patterns:
            try:
                matcher = re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid redact pattern {pattern!r}: {exc}") from exc
            rules.append(_Rule(matcher, "[redacted:user]", Kind.PATTERN, "user"))
        values = sorted(
            (value for value in cfg.values if value.value),
            key=lambda value: (-len(value.value.encode("utf-8")), value.name),
        )
        rules.extend(
            _Rule(
                value.value,
                _value_replacement(cfg.reveal, value.name, value.value),
                Kind.VALUE,
                value.name,
            )
            for value in values
        )
        self._rules = tuple(rules)

    def _selected(self, text: str) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for order, rule in enumerate(self._rules):
            # These _record_type records are invisible to Pyright's field analysis.
            if (
                getattr(rule, "label", None) == "pem"
                and getattr(rule, "kind", None) is Kind.PATTERN
            ):
                candidates.extend(_pem_candidates(text, order))
                continue
            if (
                getattr(rule, "label", None) == "url-creds"
                and getattr(rule, "kind", None) is Kind.PATTERN
            ):
                candidates.extend(_url_credential_candidates(text, order))
                continue
            matcher = getattr(rule, "matcher", "")
            if isinstance(matcher, str):
                start = 0
                while (found := text.find(matcher, start)) >= 0:
                    candidates.append(_Candidate(found, found + len(matcher), order))
                    start = found + len(matcher)
            else:
                matches = matcher.finditer(text)
                if (
                    getattr(rule, "label", None) == "env-assign"
                    and getattr(rule, "kind", None) is Kind.PATTERN
                ):
                    candidates.extend(
                        _Candidate(
                            _preceding_whitespace_start(text, match.start()),
                            match.end(),
                            order,
                        )
                        for match in matches
                    )
                else:
                    candidates.extend(
                        _Candidate(match.start(), match.end(), order)
                        for match in matches
                    )
        candidates.sort(
            key=lambda candidate: (candidate.start, -candidate.end, candidate.order)
        )
        selected: list[_Candidate] = []
        last_end = 0
        last_empty: int | None = None
        for candidate in candidates:
            if candidate.start < last_end:
                if selected and candidate.end > selected[-1].end:
                    selected[-1] = _Candidate(
                        selected[-1].start, candidate.end, selected[-1].order
                    )
                    last_end = candidate.end
                continue
            if candidate.start == candidate.end and last_empty == candidate.start:
                continue
            last_empty = candidate.start if candidate.start == candidate.end else None
            last_end = candidate.end
            selected.append(candidate)
        return selected

    def redact_spans(self, text: str) -> list[Span]:
        selected = self._selected(text)
        if not selected:
            return []
        last_offset = max(candidate.end for candidate in selected)
        byte_offsets = [0] * (last_offset + 1)
        byte_offset = 0
        for index, char in enumerate(text[:last_offset]):
            codepoint = ord(char)
            if codepoint <= 0x7F:
                byte_offset += 1
            elif codepoint <= 0x7FF:
                byte_offset += 2
            elif codepoint <= 0xFFFF:
                byte_offset += 3
            else:
                byte_offset += 4
            byte_offsets[index + 1] = byte_offset
        return [
            Span(
                byte_offsets[candidate.start],
                byte_offsets[candidate.end],
                getattr(self._rules[candidate.order], "replacement", None),
                getattr(self._rules[candidate.order], "kind", None),
            )
            for candidate in selected
        ]

    def redact(self, text: str) -> Redacted:
        output: list[str] = []
        notices: list[Notice] = []
        cursor = 0
        for candidate in self._selected(text):
            rule = self._rules[candidate.order]
            output.extend(
                (text[cursor : candidate.start], getattr(rule, "replacement", ""))
            )
            cursor = candidate.end
            for index, notice in enumerate(notices):
                if getattr(notice, "kind", None) == getattr(
                    rule, "kind", None
                ) and getattr(notice, "label", None) == getattr(rule, "label", None):
                    notices[index] = Notice(
                        getattr(notice, "kind", None),
                        getattr(notice, "label", None),
                        getattr(notice, "count", 0) + 1,
                    )
                    break
            else:
                notices.append(
                    Notice(getattr(rule, "kind", None), getattr(rule, "label", None), 1)
                )
        output.append(text[cursor:])
        return Redacted("".join(output), notices)


def __getattr__(name):
    if name != "values":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = __import__(f"{__name__}.values", fromlist=["values"])
    globals()[name] = module
    return module


def _preceding_whitespace_start(text: str, start: int) -> int:
    while start:
        newline = start - 1
        if text[newline] != "\n":
            break
        previous_line_start = text.rfind("\n", 0, newline) + 1
        previous_line = text[previous_line_start:newline].removesuffix("\r")
        if not all(char.isspace() for char in previous_line):
            break
        start = previous_line_start
    return start


def _pem_candidates(text: str, order: int) -> list[_Candidate]:
    candidates = []
    search_from = 0
    while (begin := _PEM_BEGIN.search(text, search_from)) is not None:
        end = _PEM_END.search(text, begin.end())
        if end is None:
            break
        candidates.append(_Candidate(begin.start(), end.end(), order))
        search_from = end.end()
    return candidates


def _url_credential_candidates(text: str, order: int) -> list[_Candidate]:
    candidates = []
    marker = 0
    while (marker := text.find("://", marker)) >= 0:
        scheme_start = marker - 1
        while (
            scheme_start >= 0
            and text[scheme_start] in "abcdefghijklmnopqrstuvwxyz0123456789+.-"
        ):
            scheme_start -= 1
        scheme_start += 1
        scheme_start = next(
            (
                index
                for index in range(scheme_start, marker)
                if text[index] in "abcdefghijklmnopqrstuvwxyz"
                and (
                    index == 0
                    or not (text[index - 1].isalnum() or text[index - 1] == "_")
                )
            ),
            marker,
        )
        if scheme_start < marker and text[scheme_start] in "abcdefghijklmnopqrstuvwxyz":
            at_boundary = scheme_start == 0 or not (
                text[scheme_start - 1].isalnum() or text[scheme_start - 1] == "_"
            )
            if at_boundary:
                username_start = marker + 3
                username_end = username_start
                while (
                    username_end < len(text)
                    and not text[username_end].isspace()
                    and text[username_end] not in ":/@"
                ):
                    username_end += 1
                if (
                    username_end > username_start
                    and username_end < len(text)
                    and text[username_end] == ":"
                ):
                    password_start = username_end + 1
                    password_end = password_start
                    while (
                        password_end < len(text)
                        and not text[password_end].isspace()
                        and text[password_end] not in "@/"
                    ):
                        password_end += 1
                    if (
                        password_end > password_start
                        and password_end < len(text)
                        and text[password_end] == "@"
                    ):
                        candidates.append(
                            _Candidate(scheme_start, password_end + 1, order)
                        )
        marker += 3
    return candidates


__all__ = [
    "Kind",
    "Notice",
    "RedactConfig",
    "Redacted",
    "Redactor",
    "SecretValue",
    "Span",
    "values",
]
