#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo "usage: check-pr-body.sh <body-file>" >&2
  exit 2
fi

python3 - "$1" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
visible = re.sub(r"(?ms)^```[^\n]*\n.*?^```[ \t]*$", "", text)
headings = ["## Summary", "## Evidence", "## Merge Danger"]
matches = list(re.finditer(r"^## (?:Summary|Evidence|Merge Danger)[ \t]*$", visible, re.MULTILINE))
found = [match.group(0).strip() for match in matches]
if found != headings:
    missing = next((heading for heading in headings if heading not in found), None)
    if missing:
        raise SystemExit(f"missing required section: {missing}")
    duplicate = next((heading for heading in headings if found.count(heading) > 1), None)
    if duplicate:
        raise SystemExit(f"duplicate section: {duplicate}")
    wrong = next((actual for actual, expected in zip(found, headings) if actual != expected), "unknown")
    raise SystemExit(f"misordered section: {wrong}; expected {headings[found.index(wrong)]}")
positions = [match.start() for match in matches]

for index, heading in enumerate(headings):
    start = positions[index] + len(heading)
    end = positions[index + 1] if index + 1 < len(positions) else len(visible)
    body = visible[start:end].strip()
    if not body:
        raise SystemExit(f"empty section: {heading}")
    if re.search(r"(?im)^\s*(?:<[^>\n]+>|TODO|TBD)\s*$", body):
        raise SystemExit(f"placeholder in section: {heading}")

evidence = visible[positions[1] + len(headings[1]):positions[2]]
if not re.search(r"(?m)^\s*(?:[-*]\s*)?`[^`\n]+`", evidence):
    raise SystemExit("Evidence must include a command")
PY
