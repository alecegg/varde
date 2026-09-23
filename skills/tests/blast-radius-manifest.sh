#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

template="$REPO_ROOT/skills/varde-change/assets/TASK-TEMPLATE.md"
decomposition="$REPO_ROOT/skills/varde-change/references/build-decomposition.md"
fundamentals="$REPO_ROOT/skills/varde-change/references/plan-fundamentals.md"

grep -Fq 'verification_resources: []' "$template" ||
  fail "task template omits verification resource field"
grep -Fq 'impact:<repo-relative-path>' "$template" ||
  fail "task template omits canonical impact resource format"
grep -Fq '#### Impact evidence' "$template" ||
  fail "task template omits impact evidence section"
grep -Fq 'dependents or blast_radius query' "$template" ||
  fail "task template omits impact query field"
grep -Fq 'exact canonical impact identifiers' "$template" ||
  fail "task template omits exact resource rule"

grep -Fq 'record `#### Impact evidence`' "$decomposition" ||
  fail "decomposition omits impact evidence requirement"
grep -Fq 'impact:<repo-relative-path>' "$decomposition" ||
  fail "decomposition omits canonical impact resource format"
grep -Fq 'verification_resources' "$decomposition" ||
  fail "decomposition omits manifest resource field"

grep -Fq '`dependents`/`blast_radius`' "$fundamentals" ||
  fail "planning guidance omits blast-radius queries"
grep -Fq 'focused source reads' "$fundamentals" ||
  fail "planning guidance omits source confirmation"
grep -Fq 'impact:<repo-relative-path>' "$fundamentals" ||
  fail "planning guidance omits canonical impact identifiers"

echo "Blast-radius manifest contract fixtures passed."
