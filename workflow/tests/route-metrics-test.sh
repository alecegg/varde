#!/usr/bin/env bash
set -euo pipefail

source "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)/core/tests/lib/repo.sh"
source "$REPO_ROOT/workflow/tests/lib/varde-bin.sh"
prefer_checkout_varde "$REPO_ROOT"

script="$REPO_ROOT/workflow/scripts/route-metrics.sh"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/route-metrics-test.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT

require() {
  local file="$1"
  mkdir -p "$(dirname "$file")"
  cat >"$file"
}

# Two skills with predictable token counts (tokens are ceil(bytes / 4)) and one
# skill without routes, which must print nothing.
require "$fixture/varde-alpha/SKILL.md" <<'MD'
# Alpha

## Status route

Read `references/status.md`.

## Verify route

Read `references/verify.md`.
MD
require "$fixture/varde-alpha/references/status.md" <<<'Status body.'
require "$fixture/varde-alpha/references/verify.md" <<<'Verify body text, one line.'
require "$fixture/varde-beta/SKILL.md" <<'MD'
# Beta

## Report route

Read `references/report.md`.
MD
require "$fixture/varde-beta/references/report.md" <<<'Report body.'
require "$fixture/varde-plain/SKILL.md" <<<'# Plain

No routes here.
'

actual="$fixture/actual.txt"
if ! bash "$script" "$fixture/varde-alpha" "$fixture/varde-beta" "$fixture/varde-plain" >"$actual"; then
  echo "FAIL: route-metrics.sh failed" >&2
  cat "$actual" >&2
  exit 1
fi

expected="$fixture/expected.txt"
printf '%s\n' \
  $'varde-alpha\tStatus route\t30\t30' \
  $'varde-alpha\tVerify route\t33\t33' \
  $'varde-beta\tReport route\t18\t18' >"$expected"

if ! diff -u "$expected" "$actual"; then
  echo "FAIL: route metrics differ from expected" >&2
  exit 1
fi

echo "PASS: route metrics report skill, route, and main-agent token bounds"
