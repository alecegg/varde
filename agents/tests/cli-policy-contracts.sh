#!/usr/bin/env bash
set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# B-agent-1 cuts the per-role CLI policy block: command selection and fallback
# rules stay in the skills the role loads, not in the generated role files.
python3 - "$AGENTS_DIR" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
profiles = ("varde-planner", "varde-builder", "varde-reviewer", "varde-explorer")
variants = ("claude.md", "codex.toml", "opencode.md", "opencode-v2.md", "pi.md")
removed = (
    "## cli policy",
    "references/varde-code-cli.md",
    "references/varde-workflow-cli.md",
    "degraded capability",
    "manual evidence",
)
for profile in profiles:
    for variant in variants:
        text = " ".join((root / profile / variant).read_text().lower().split())
        for phrase in removed:
            assert phrase not in text, (profile, variant, phrase)
print("Role files carry no CLI policy block.")
PY
