#!/usr/bin/env bash
set -euo pipefail

skills_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
verifier="$skills_dir/varde-knowledge/evals/verify-knowledge-eval.sh"

# No evaluated run exists. Fixtures must never award behavioral PASS results
# or emit undeclared assertions; an empty result delegates grading to the judge.
for eval_id in 8 9; do
  result="$(EVAL_ID="$eval_id" EVAL_SKILL_DIR="$skills_dir/varde-knowledge" \
    EVAL_SANDBOX_DIR="$skills_dir/varde-knowledge" bash "$verifier")"
  jq -e '.results == []' <<< "$result" >/dev/null || {
    echo "FAIL: knowledge eval $eval_id grades static fixtures as run evidence" >&2
    exit 1
  }
done

echo 'PASS: knowledge handoff assertions remain for session-evidence judging'

fixture=$(mktemp -d "${TMPDIR:-/tmp}/knowledge-output.XXXXXX")
trap 'rm -rf "$fixture"' EXIT
for output_state in absent empty valid; do
  if [[ "$output_state" != absent ]]; then mkdir -p "$fixture/memory-bank/knowledge/decision"; fi
  if [[ "$output_state" == valid ]]; then
    cat > "$fixture/memory-bank/knowledge/decision/occ.md" <<'NOTE'
---
type: decision
description: Use OCC
generated: { by: test, at: 2026-09-28T00:00:00Z }
---
## What
OCC.
## Why
Concurrent writes.
## Constraints
Compare versions.
NOTE
  fi
  result=$(cd "$fixture" && EVAL_ID=1 bash "$verifier")
  expected=FAIL; [[ "$output_state" == valid ]] && expected=PASS
  jq -e --arg verdict "$expected" '.results | length == 4 and all(.[]; .verdict == $verdict)' <<< "$result" >/dev/null
done
echo 'PASS: missing, empty, and valid knowledge output emit structured verdicts'
