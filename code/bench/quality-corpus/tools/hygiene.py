"""Validate blind prompt inputs: fixed denylist, parity and opaque pair ids."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

DENYLIST = re.compile(
    r"\b(?:over_split|sensible|padded|tiny|variant|golden|monolith)\b|"
    r"(?:items|labels)/(?:python|typescript|java|go|rust|csharp|cpp)|"
    r"\b(?:dev|test)[-_ ]split\b|"
    r"\b(?:panel\s+)?labels?\s*[:=]\s*(?:A|B|tie|unanimous|majority|contested)\b",
    re.IGNORECASE,
)
LINE_COMMENTS = {
    ".py": "#",
    ".sh": "#",
    ".rb": "#",
    ".go": "//",
    ".rs": "//",
    ".java": "//",
    ".cs": "//",
    ".cpp": "//",
    ".cc": "//",
    ".ts": "//",
    ".js": "//",
}


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    message: str


def length_class(length: int) -> str:
    return "short" if length < 80 else "medium" if length < 240 else "long"


def comments(text: str, suffix: str) -> list[str]:
    line_marker = LINE_COMMENTS.get(suffix)
    found = re.findall(r"/\*.*?\*/", text, re.DOTALL)
    if line_marker:
        found.extend(
            line.strip()[len(line_marker) :].strip()
            for line in text.splitlines()
            if line.lstrip().startswith(line_marker)
        )
    if suffix == ".py":
        found.extend(
            re.findall(r"(?s)(?:^|\n)\s*(?:'''|\"\"\")(.*?)(?:'''|\"\"\")", text)
        )
    return found


def comment_shape(text: str, suffix: str) -> tuple[int, str]:
    values = comments(text, suffix)
    return len(values), length_class(sum(map(len, values)))


def replace_opaque_ids(
    data: dict, fields: tuple[str, ...] = ("pair_id", "left_id", "right_id")
) -> tuple[dict, dict[str, str]]:
    mapping = {}
    rewritten = dict(data)
    for field in fields:
        if field in rewritten:
            original = str(rewritten[field])
            digest = hashlib.sha256(original.encode()).hexdigest()[:24]
            mapping[original] = digest
            rewritten[field] = digest
    return rewritten, mapping


def check(item_dir: Path) -> list[Finding]:
    task = item_dir / "task.txt"
    targets = [
        p
        for p in item_dir.rglob("*")
        if p.is_file()
        and (
            p.name.startswith("behaviour_test.")
            or p == task
            or p.suffix not in {".json", ".toml"}
        )
    ]
    code_files = [
        p for p in targets if not p.name.startswith("behaviour_test.") and p != task
    ]
    findings = [
        Finding("forbidden_text", str(path), "fixed denylist hit")
        for path in targets
        if DENYLIST.search(path.read_text(errors="replace"))
    ]
    if task.exists() and DENYLIST.search(task.read_text(errors="replace")):
        findings.append(Finding("forbidden_text", str(task), "fixed denylist hit"))
    if len(code_files) == 2 and comment_shape(
        code_files[0].read_text(errors="replace"), code_files[0].suffix
    ) != comment_shape(code_files[1].read_text(errors="replace"), code_files[1].suffix):
        findings.append(
            Finding(
                "comment_parity", str(item_dir), "comment count or length class differs"
            )
        )
    pair = item_dir / "pair.json"
    if pair.exists():
        data = json.loads(pair.read_text())
        for key, value in data.items():
            if key.endswith("_id") and not re.fullmatch(r"[0-9a-f]{24,64}", str(value)):
                findings.append(
                    Finding("opaque_id", str(pair), f"{key} must be an opaque hash")
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--rewrite-ids", action="store_true")
    args = parser.parse_args()
    if not args.items.is_dir():
        parser.error(f"items directory does not exist: {args.items}")
    if not args.check and not args.rewrite_ids:
        parser.error("--check is required unless --rewrite-ids is used")
    if args.rewrite_ids:
        mapping = {}
        for pair_file in sorted(args.items.rglob("pair.json")):
            data = json.loads(pair_file.read_text())
            rewritten, item_mapping = replace_opaque_ids(data)
            if item_mapping:
                pair_file.write_text(json.dumps(rewritten, indent=2) + "\n")
                mapping.update(item_mapping)
        print(json.dumps({"rewritten_ids": mapping}, sort_keys=True))
        return 0
    item_dirs = (
        [args.items]
        if any(args.items.glob("behaviour_test.*"))
        else [
            path
            for path in args.items.rglob("*")
            if path.is_dir() and any(path.glob("behaviour_test.*"))
        ]
    )
    findings = [finding for path in item_dirs for finding in check(path)]
    for finding in findings:
        print(json.dumps(finding.__dict__, sort_keys=True))
    if not findings:
        print("hygiene: ok")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
