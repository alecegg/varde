#!/usr/bin/env bash
#
# Measure a skill's description trigger accuracy against an eval set.
#
# Usage:
#   scripts/run-evals.sh <skill-name> <queries.json> [--runs N]
#   scripts/run-evals.sh varde-plan  varde-plan/evals/evals.json
#   scripts/run-evals.sh varde-build varde-build/evals/evals.json --runs 5
#
# The queries file is a JSON array of objects, each with:
#   - "query":          the prompt to send (string)
#   - "should_trigger": whether this skill should fire (bool)
#   - "note":           optional; ignored by this script (human doc only)
#
# Each query is run N times (default 3) through `claude -p`; the trigger rate is
# the fraction of runs where a Skill tool_use invoked <skill-name>. Per the
# agentskills.io method: a should_trigger query PASSES if rate > 0.5; a
# should-not-trigger (near-miss) query PASSES if rate < 0.5.
#
# Output: one FAIL line per failing query on stdout, then a summary line
#   evals: pass=<n> fail=<n> skill=<name>
# Diagnostics go to stderr.
#
# Exit codes:
#   0  all queries passed
#   1  one or more queries failed
#   2  usage error or missing dependency (jq / claude)
#
# NOTE: this spawns (query-count x runs) `claude -p` invocations — it is billed
# and slow. Treat the committed eval file as a TRAIN set: if you tune a
# description to fix a failure here, validate the winner on a fresh held-out set
# rather than trusting this same set (avoids overfitting to these phrasings).

set -euo pipefail

die() { printf 'error: %s\n' "$1" >&2; exit 2; }

case "${1:-}" in
  -h|--help|"")
    sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; s/^#$//' | sed '$d'
    exit 0
    ;;
esac

SKILL_NAME="$1"; shift
QUERIES="${1:-}"; shift || true
RUNS=3
while [ $# -gt 0 ]; do
  case "$1" in
    --runs) RUNS="${2:?--runs needs a value}"; shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$QUERIES" ] || die "missing queries.json (see --help)"
[ -f "$QUERIES" ] || die "queries file not found: $QUERIES"
command -v jq >/dev/null 2>&1 || die "jq is required"
command -v claude >/dev/null 2>&1 || die "claude CLI is required"

len=$(jq 'length' "$QUERIES") || die "invalid JSON in $QUERIES"
pass=0; fail=0

for i in $(seq 0 $((len - 1))); do
  query=$(jq -r ".[$i].query" "$QUERIES")
  want=$(jq -r ".[$i].should_trigger" "$QUERIES")
  hits=0
  for _ in $(seq "$RUNS"); do
    if claude -p "$query" --output-format json 2>/dev/null \
        | jq -e --arg s "$SKILL_NAME" \
          'any(.messages[].content[]?; .type=="tool_use" and .name=="Skill" and .input.skill==$s)' \
          >/dev/null 2>&1; then
      hits=$((hits + 1))
    fi
  done
  # rate > 0.5 means the majority of runs triggered
  triggered_majority=$(awk -v h="$hits" -v r="$RUNS" 'BEGIN{print (h/r > 0.5) ? 1 : 0}')
  if { [ "$want" = true ] && [ "$triggered_majority" = 1 ]; } \
     || { [ "$want" = false ] && [ "$triggered_majority" = 0 ]; }; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL [want=%s hits=%s/%s] %s\n' "$want" "$hits" "$RUNS" "$query"
  fi
done

printf 'evals: pass=%s fail=%s skill=%s\n' "$pass" "$fail" "$SKILL_NAME"
[ "$fail" -eq 0 ]
