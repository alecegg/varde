#!/usr/bin/env bash
set -euo pipefail

# The memory-location paragraph is inlined in consuming SKILL.md files and
# must match after line-wrap whitespace is ignored (see README.md).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SKILLS_DIR"

python3 - <<'PY'
import glob, re, sys

paragraph = (
    "Resolve `<working>` and `<knowledge>` once with "
    "`varde-workflow paths --json`; retry once with escalated access, then ask; "
    "never guess. Outside a repo, use `mv`, not `git mv`."
)
normalized_paragraph = re.sub(r"\s+", " ", paragraph).strip()

checked = 0
for skill_md in sorted(glob.glob("varde-*/SKILL.md")):
    text = open(skill_md, encoding="utf-8").read()
    if "varde-workflow paths --json" not in text:
        continue
    checked += 1
    normalized_text = re.sub(r"\s+", " ", text)
    if normalized_paragraph not in normalized_text:
        sys.exit(f"FAIL: {skill_md}'s memory paragraph differs from the pinned text")

if checked != 6:
    sys.exit(f"FAIL: expected 6 SKILL.md files to inline the memory paragraph, found {checked}")

print(f"memory-location paragraph: pinned text matched in {checked} SKILL.md file(s)")
PY

echo "vendored-copies: memory-location paragraph check passed."
