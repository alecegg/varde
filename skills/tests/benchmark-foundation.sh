#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKFLOW="$REPO_ROOT/.github/workflows/skills-benchmarks.yml"

assert_event_path() {
  local event="$1"
  awk -v event="$event" \
    -v required='      - ".github/workflows/skills-benchmarks.yml"' '
      $0 == "  " event ":" { inside=1; next }
      inside && $0 ~ /^  [[:alnum:]_-]+:/ { exit }
      inside && $0 == required { found=1 }
      END { exit(found ? 0 : 1) }
    ' "$WORKFLOW" || {
      echo "FAIL: $event omits workflow self-trigger" >&2
      exit 1
    }
}

"$SCRIPT_DIR/output-evals.sh"
"$SCRIPT_DIR/changed-output-evals.sh"
"$SCRIPT_DIR/lifecycle-scenarios.sh"
"$SCRIPT_DIR/word-count-audit.sh"
"$SCRIPT_DIR/change-path-benchmarks.sh"
assert_event_path pull_request
assert_event_path push

echo "benchmark foundation checks passed"
