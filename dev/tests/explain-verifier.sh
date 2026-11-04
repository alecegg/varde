#!/usr/bin/env bash
set -euo pipefail
source "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)/core/tests/lib/repo.sh"
EXPLAIN="$(skill_dir varde-explain)/evals/verify-explain-eval.sh"
EXPLORE="$(skill_dir varde-explore)/evals/verify-explore-eval.sh"
ROOT=$(mktemp -d "${TMPDIR:-/tmp}/explain-verifier.XXXXXX")
trap 'rm -rf "$ROOT"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }
all_pass() { jq -e '(.results | length) > 0 and (all(.results[]; .verdict == "PASS"))' >/dev/null; }
any_fail() { jq -e '(.results | length) > 0 and (any(.results[]; .verdict == "FAIL"))' >/dev/null; }
run() { (cd "$1" && EVAL_ID="$2" bash "$3"); }
seed_repo() {
  mkdir -p "$1"
  git -C "$1" init -q
  git -C "$1" config user.name test
  git -C "$1" config user.email test@example.com
  mkdir -p "$1/src"
  printf 'source baseline\n' > "$1/src/source.txt"
  git -C "$1" add src/source.txt
  git -C "$1" commit -qm seed
}

s="$ROOT/explain-pass"; mkdir -p "$s/working/explanations"
cat > "$s/working/explanations/2026-10-17-session-validation.html" <<'HTML'
<html><head><style>body{font:1rem sans-serif}</style></head><body><h1>Background</h1><h2>Intuition</h2><h2>How It Works</h2></body></html>
HTML
result=$(run "$s" 1 "$EXPLAIN"); printf '%s' "$result" | all_pass || fail "explain eval 1 PASS failed: $result"
s="$ROOT/explain-fail"; mkdir -p "$s/working/explanations"
cat > "$s/working/explanations/2026-10-17-session-validation.html" <<'HTML'
<html><head><link rel="stylesheet" href="https://example.test/a.css"></head><body><h1>Background</h1><h2>Intuition</h2></body></html>
HTML
result=$(run "$s" 1 "$EXPLAIN"); printf '%s' "$result" | any_fail || fail "explain eval 1 FAIL fixture passed: $result"
for id in 2 3 5; do
  s="$ROOT/explain-chat-$id"; mkdir -p "$s/working/explanations"
  result=$(run "$s" "$id" "$EXPLAIN"); printf '%s' "$result" | all_pass || fail "explain eval $id empty PASS failed: $result"
  printf '%s\n' '<html></html>' > "$s/working/explanations/unwanted.html"
  result=$(run "$s" "$id" "$EXPLAIN"); printf '%s' "$result" | any_fail || fail "explain eval $id FAIL fixture passed: $result"
done
s="$ROOT/options-pass"; mkdir -p "$s/working/explanations"
cat > "$s/working/explanations/2026-10-17-session-validation-options.html" <<'HTML'
<html><body><h1>Options</h1><h2>Tradeoffs</h2><h2>Recommendation</h2></body></html>
HTML
result=$(run "$s" 7 "$EXPLAIN"); printf '%s' "$result" | all_pass || fail "explain eval 7 PASS failed: $result"
s="$ROOT/options-fail"; mkdir -p "$s/working/explanations"
printf '%s\n' '<html><body><h1>Options</h1><h2>Tradeoffs</h2></body></html>' > "$s/working/explanations/2026-10-17-options.html"
result=$(run "$s" 7 "$EXPLAIN"); printf '%s' "$result" | any_fail || fail "explain eval 7 FAIL fixture passed: $result"

s="$ROOT/explore-pass"; mkdir -p "$s/working" "$s/.varde-eval-config" "$s/.varde-eval-learn"; seed_repo "$s"
mkdir -p "$s/knowledge"
result=$(run "$s" 4 "$EXPLORE"); printf '%s' "$result" | all_pass || fail "explore eval 4 PASS failed: $result"
mkdir -p "$s/working/explanations"
printf '%s\n' '<html></html>' > "$s/working/explanations/extra.html"
result=$(run "$s" 4 "$EXPLORE"); jq -e 'any(.results[]; .assertion == "No HTML artifact is written for a chat options comparison" and .verdict == "FAIL")' <<< "$result" >/dev/null || fail "explore eval 4 HTML FAIL fixture passed: $result"
rm -f "$s/working/explanations/extra.html"
printf 'source changed\n' >> "$s/src/source.txt"
result=$(run "$s" 4 "$EXPLORE"); jq -e 'any(.results[]; .assertion == "No source changes are made" and .verdict == "FAIL")' <<< "$result" >/dev/null || fail "explore eval 4 source FAIL fixture passed: $result"
s="$ROOT/explore-plan"; mkdir -p "$s/working"; seed_repo "$s"
result=$(run "$s" 4 "$EXPLORE"); printf '%s' "$result" | all_pass || fail "explore eval 4 clean PASS failed: $result"
mkdir -p "$s/working/plans"; touch "$s/working/plans/plan.md"
result=$(run "$s" 4 "$EXPLORE"); any_fail <<< "$result" || fail "explore eval 4 plan FAIL fixture passed: $result"
s="$ROOT/explore-transition"; mkdir -p "$s/working/explanations"
result=$(run "$s" 6 "$EXPLORE"); printf '%s' "$result" | all_pass || fail "explore eval 6 PASS failed: $result"
printf '%s\n' '<html></html>' > "$s/working/explanations/unwanted.html"
result=$(run "$s" 6 "$EXPLORE"); printf '%s' "$result" | any_fail || fail "explore eval 6 FAIL fixture passed: $result"

# Validate declarations from a clean sandbox repo, not this dirty checkout.
s="$ROOT/declared-check"; seed_repo "$s"
python3 - "$EXPLAIN" "$EXPLORE" "$s" <<'PY'
import json, os, subprocess, sys
from pathlib import Path
for script in map(Path, sys.argv[1:3]):
    declared=json.loads((script.parent/'evals.json').read_text())['evals']
    assert declared, f'{script}: no evals'
    for case in declared:
        assert case.get('verification_script') == f'evals/{script.name}', case
        result=subprocess.run(['bash',str(script)],cwd=sys.argv[3],env=dict(os.environ,EVAL_ID=str(case['id'])),capture_output=True,text=True,check=True)
        items=json.loads(result.stdout)['results']
        assert items, f"eval {case['id']} reported no assertions"
        for item in items: assert item['assertion'] in case['assertions'], item['assertion']
PY
echo 'PASS: explain-verifier'
