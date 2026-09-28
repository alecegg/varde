#!/usr/bin/env bash
set -euo pipefail

skills_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/docs-refresh-scope.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/run"
(
  cd "$fixture"
  EVAL_ID=5 bash "$skills_dir/varde-docs/evals/setup-docs-eval.sh"
)
printf 'Inventory: README.md and code-cli/CHANGELOG.md\n' > "$fixture/run/transcript.txt"
(
  cd "$fixture"
  EVAL_ID=5 EVAL_TRANSCRIPT="$fixture/run/transcript.txt" \
    bash "$skills_dir/varde-docs/evals/verify-docs-eval.sh"
) | jq -e '.results[0].verdict == "PASS"' >/dev/null

printf 'Inventory: README.md only\n' > "$fixture/run/transcript.txt"
(
  cd "$fixture"
  EVAL_ID=5 EVAL_TRANSCRIPT="$fixture/run/transcript.txt" \
    bash "$skills_dir/varde-docs/evals/verify-docs-eval.sh"
) | jq -e '.results[0].verdict == "FAIL"' >/dev/null
echo 'Module CHANGELOG eval fixture accepts its inventory and rejects omission.'
