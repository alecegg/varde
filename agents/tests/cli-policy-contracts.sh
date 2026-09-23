#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

for profile in plan executor review explore; do
  for variant in claude.md codex.toml opencode.md; do
    prompt="$AGENTS_DIR/$profile/$variant"
    [ -f "$prompt" ] || fail "missing generated prompt: $prompt"

    grep -Fq '## CLI policy' "$prompt" || \
      fail "$profile/$variant lacks a CLI policy"
    grep -Fq 'references/varde-code.md' "$prompt" || \
      fail "$profile/$variant lacks the Varde Code policy reference"
    grep -Fq 'degraded capability' "$prompt" || \
      fail "$profile/$variant lacks degraded-capability reporting"
    grep -Fq 'manual evidence' "$prompt" || \
      fail "$profile/$variant lacks manual evidence reporting"

    if grep -Eq 'varde-code [a-z_]+ .*--json|varde-workflow [a-z_]+ .*--json' "$prompt"; then
      fail "$profile/$variant copied a CLI command manual"
    fi
  done
done

for profile in plan executor; do
  grep -Fq 'references/varde-workflow-cli.md' \
    "$AGENTS_DIR/$profile/claude.md" || \
    fail "$profile does not name its workflow CLI policy"
done

for profile in review explore; do
  if grep -Fq 'references/varde-workflow-cli.md' "$AGENTS_DIR/$profile/claude.md"; then
    fail "$profile claims workflow artifact ownership"
  fi
done

echo "Agent CLI policy contracts passed."
