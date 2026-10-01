#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

for profile in varde-planner varde-executor varde-reviewer varde-explorer; do
  for variant in claude.md codex.toml opencode.md; do
    prompt="$AGENTS_DIR/$profile/$variant"
    [ -f "$prompt" ] || fail "missing generated prompt: $prompt"

    grep -Fq '## CLI policy' "$prompt" || \
      fail "$profile/$variant lacks a CLI policy"
    grep -Fq 'references/varde-code-cli.md' "$prompt" || \
      fail "$profile/$variant lacks the Varde Code policy reference"
    grep -Eq 'degraded.*capability|capability.*degraded' "$prompt" || \
      fail "$profile/$variant lacks degraded-capability reporting"
    grep -Fq 'manual evidence' "$prompt" || \
      fail "$profile/$variant lacks manual evidence reporting"

  done
done


# Gate evidence needs these three fragile commands in role prompts. Mask only
# their exact prefix, so another command on the same line remains checked.
python3 - "$AGENTS_DIR" <<'PY_GATE'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
gate = re.compile(r"varde-workflow review (?:check|inspect|record)(?=\s|$)")
manual = re.compile(r"varde-code [a-z_]+ .*--json|varde-workflow [a-z_]+ .*--json")
def copied_manual(text):
    return bool(manual.search(gate.sub("review-gate", text)))

for command in ("check", "inspect", "record"):
    assert not copied_manual(f"varde-workflow review {command} --subject example --json")
for text in (
    "varde-workflow review contract --file contract.json --json",
    "varde-workflow review unknown --json",
    "varde-workflow review record-evil --json",
    "varde-workflow transition task.md done --json",
    "varde-code nav_map --json",
    "varde-workflow review record --json; varde-code nav_map --json",
    "varde-workflow review check --json; varde-workflow transition task.md done --json",
):
    assert copied_manual(text), text
for profile in ("varde-planner", "varde-executor", "varde-reviewer", "varde-explorer"):
    for variant in ("claude.md", "codex.toml", "opencode.md"):
        if copied_manual((root / profile / variant).read_text()):
            sys.exit(f"FAIL: {profile}/{variant} copied a CLI command manual")
PY_GATE

for profile in varde-planner varde-executor; do
  grep -Fq 'references/varde-workflow-cli.md' \
    "$AGENTS_DIR/$profile/claude.md" || \
    fail "$profile does not name its workflow CLI policy"
done

for profile in varde-reviewer varde-explorer; do
  if grep -Fq 'references/varde-workflow-cli.md' "$AGENTS_DIR/$profile/claude.md"; then
    fail "$profile claims workflow artifact ownership"
  fi
done

echo "Agent CLI policy contracts passed."
