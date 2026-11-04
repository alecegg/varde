"""Source hygiene rules that need syntax trees or whole-file comparisons."""

from __future__ import annotations

import json
import re
from itertools import pairwise
from pathlib import Path

from item_spec_entry import entry_doc, entry_form
from item_spec_languages import VERSIONS
from item_spec_symbols import unused_python_locals, unused_symbols
from varde_code.parse import parse_source


def source_findings(
    item: Path, language: str, sources: dict[str, str], entries
) -> list[dict]:
    findings = []
    parsed = (
        {version: parse_source(language, source) for version, source in sources.items()}
        if language != "python"
        else {}
    )
    for version, source in sources.items():
        findings.extend(
            _finding("unused_symbol", version, name, 1, "referenced")
            for name in unused_symbols(
                language,
                source,
                entries[version].name if entries[version] else "",
                parsed.get(version),
            )
        )
        if language == "python":
            findings.extend(
                _finding("unused_local", version, name, 1, "read")
                for name in unused_python_locals(source)
            )
        for number, line in enumerate(source.splitlines(), 1):
            width = len(line.expandtabs(8))
            if width > 100:
                findings.append(
                    _finding("line_too_long", version, str(number), width, 100)
                )
    docs = {
        v: entry_doc(
            language, sources[v], entries[v].name if entries[v] else "", parsed.get(v)
        )
        for v in VERSIONS
    }
    if len(set(docs.values())) > 1:
        findings.extend(
            _finding(
                "entry_doc_text_parity",
                v,
                entries[v].name if entries[v] else "",
                docs[v],
                "identical",
            )
            for v in VERSIONS
        )
    forms = {
        v: entry_form(
            language, sources[v], entries[v].name if entries[v] else "", parsed.get(v)
        )
        for v in VERSIONS
    }
    if len(set(forms.values())) > 1:
        findings.extend(
            _finding(
                "entry_declaration_form",
                v,
                entries[v].name if entries[v] else "",
                forms[v],
                "identical",
            )
            for v in VERSIONS
        )
    pair = item / "pair.json"
    if pair.is_file():
        ids = [
            str(value)
            for key, value in json.loads(pair.read_text()).items()
            if key.endswith("_id")
        ]
        if not ids_opaque(ids):
            findings.append(
                _finding("pair_id_not_opaque", "", "pair.json", ids, "hex ids")
            )
        elif patterned_ids(ids):
            findings.append(
                _finding("pair_id_opaque", "", "pair.json", ids, "opaque ids")
            )
    return findings


def _finding(kind: str, version: str, function: str, value, limit) -> dict:
    return {
        "kind": kind,
        "version": version,
        "function": function,
        "value": value,
        "limit": limit,
    }


def patterned_ids(ids: list[str]) -> bool:
    if len(ids) < 2:
        return False
    if not ids_opaque(ids):
        return False
    if all(_common_prefix(left, right) > 8 for left, right in pairwise(sorted(ids))):
        return True
    values = sorted(int(value, 16) for value in ids)
    differences = [right - left for left, right in pairwise(values)]
    return bool(differences) and differences[0] < 2**16 and len(set(differences)) == 1


def ids_opaque(ids: list[str]) -> bool:
    return all(re.fullmatch(r"[0-9a-f]{16,}", value) for value in ids)


def _common_prefix(left: str, right: str) -> int:
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            return index
    return min(len(left), len(right))
