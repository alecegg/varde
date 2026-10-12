#!/usr/bin/env bash
set -euo pipefail

# Pins each outcome rule as a fixed string in every file that owns it. The
# Markdown references wrap prose, so whitespace is collapsed before the grep.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

SLICE_RULE='Test only your slice (task asserts plus unit tests of the changed package, and the one changed integration target only if the task edits an integration test or a CLI contract); never run the full suite; after a fix rerun only the failing target.'
POLL_RULE='Do not poll a running command or agent; wait on completion or use one long wait.'
ASSERT_RULE='No workspace-wide or full-suite asserts in task files; the integration gate owns them.'
QUEUE_RULE="The integration queue's full gate runs once per batch and bisects failures to the culprit task; do not poll running commands or agents."

PIN_FILES=(
  agents/capabilities.json
  agents/varde-builder/claude.md
  agents/varde-builder/codex.toml
  agents/varde-builder/opencode-v2.md
  agents/varde-builder/opencode.md
  agents/varde-builder/pi.md
  skills/varde-change/references/build-execution.md
  skills/varde-change/references/build-orchestrate-tasks.md
  skills/varde-change/references/plan-decomposition.md
)

PINS=(
  "$SLICE_RULE|agents/capabilities.json"
  "$SLICE_RULE|agents/varde-builder/claude.md"
  "$SLICE_RULE|agents/varde-builder/codex.toml"
  "$SLICE_RULE|agents/varde-builder/opencode-v2.md"
  "$SLICE_RULE|agents/varde-builder/opencode.md"
  "$SLICE_RULE|agents/varde-builder/pi.md"
  "$SLICE_RULE|skills/varde-change/references/build-execution.md"
  "$POLL_RULE|agents/capabilities.json"
  "$POLL_RULE|agents/varde-builder/claude.md"
  "$POLL_RULE|agents/varde-builder/codex.toml"
  "$POLL_RULE|agents/varde-builder/opencode-v2.md"
  "$POLL_RULE|agents/varde-builder/opencode.md"
  "$POLL_RULE|agents/varde-builder/pi.md"
  "$POLL_RULE|skills/varde-change/references/build-execution.md"
  "$ASSERT_RULE|skills/varde-change/references/plan-decomposition.md"
  "$QUEUE_RULE|skills/varde-change/references/build-orchestrate-tasks.md"
)

missing_pins() {
  local root="$1" pin rule file
  for pin in "${PINS[@]}"; do
    rule="${pin%%|*}"
    file="${pin#*|}"
    if ! tr -s '[:space:]' ' ' 2>/dev/null < "$root/$file" | grep -Fq -- "$rule"; then
      printf '%s\t%s\n' "$file" "$rule"
    fi
  done
}

current="$(missing_pins "$REPO_ROOT")"
if [[ -n "$current" ]]; then
  printf 'FAIL: outcome rules missing:\n%s\n' "$current" >&2
  exit 1
fi

# Mutation check: remove each rule from one owning file in a scratch copy and
# require the missing-pin check to report that file and rule.
scratch="$(mktemp -d "${TMPDIR:-/tmp}/outcome-rules.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT
mutations=0
for file in "${PIN_FILES[@]}"; do
  mkdir -p "$scratch/$(dirname "$file")"
  cp "$REPO_ROOT/$file" "$scratch/$file"
  for pin in "${PINS[@]}"; do
    rule="${pin%%|*}"
    [[ "${pin#*|}" == "$file" ]] || continue
    python3 - "$scratch/$file" "$rule" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
rule = sys.argv[2]
text = " ".join(path.read_text().split())
if rule not in text:
    raise SystemExit(f"mutation target missing: {rule}")
path.write_text(text.replace(rule, "[removed outcome rule]"))
PY
    detected="$(missing_pins "$scratch")"
    cp "$REPO_ROOT/$file" "$scratch/$file"
    if ! grep -Fq -- "$(printf '%s\t%s' "$file" "$rule")" <<<"$detected"; then
      printf 'FAIL: mutation survived for %s: %s\n' "$file" "$rule" >&2
      exit 1
    fi
    mutations=$((mutations + 1))
  done
done

printf 'Outcome rule pins passed in %d files (%d pins).\n' "${#PIN_FILES[@]}" "${#PINS[@]}"
printf 'Mutation checks detected %d removed outcome rules.\n' "$mutations"
