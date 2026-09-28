#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VERIFIER="$SKILLS_DIR/varde-prototype/evals/verify-prototype-eval.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/prototype-verifier.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

all_pass() {
  jq -e '(.results | length) > 0 and (all(.results[]; .verdict == "PASS"))' >/dev/null
}

any_fail() {
  jq -e '(.results | length) > 0 and (any(.results[]; .verdict == "FAIL"))' >/dev/null
}

# --- eval 1 PASS: three linked variants, <a href>, no <script> ---
sbox="$TEST_ROOT/eval1-pass"
mkdir -p "$sbox/memory-bank/working/prototypes/dashboard-layout"
cat > "$sbox/memory-bank/working/prototypes/dashboard-layout/variant-a.html" <<'HTML'
<html><body><a href="variant-b.html">B</a><a href="variant-c.html">C</a></body></html>
HTML
cat > "$sbox/memory-bank/working/prototypes/dashboard-layout/variant-b.html" <<'HTML'
<html><body><a href="variant-a.html">A</a><a href="variant-c.html">C</a></body></html>
HTML
cat > "$sbox/memory-bank/working/prototypes/dashboard-layout/variant-c.html" <<'HTML'
<html><body><a href="variant-a.html">A</a><a href="variant-b.html">B</a></body></html>
HTML

result=$(cd "$sbox" && EVAL_ID=1 /bin/bash "$VERIFIER")
printf '%s' "$result" | all_pass \
  || fail "eval 1 expected all PASS, got: $result"

# --- eval 1 FAIL: files outside expected storage ---
sbox="$TEST_ROOT/eval1-fail"
mkdir -p "$sbox/wrong"
printf '%s\n' '<html><body><a href="variant-b.html">B</a></body></html>' > "$sbox/wrong/variant-a.html"
cp "$sbox/wrong/variant-a.html" "$sbox/wrong/variant-b.html"
result=$(cd "$sbox" && EVAL_ID=1 /bin/bash "$VERIFIER")
printf '%s' "$result" | any_fail \
  || fail "eval 1 expected a FAIL for misplaced variant files, got: $result"

# --- eval 3 PASS: expected logic.html ---
sbox="$TEST_ROOT/eval3-pass"
mkdir -p "$sbox/memory-bank/working/prototypes/order-cancellation"
printf '%s\n' '<html><body></body></html>' > "$sbox/memory-bank/working/prototypes/order-cancellation/logic.html"
result=$(cd "$sbox" && EVAL_ID=3 /bin/bash "$VERIFIER")
printf '%s' "$result" | all_pass \
  || fail "eval 3 expected all PASS, got: $result"

# --- eval 3 FAIL: logic.html outside expected storage ---
sbox="$TEST_ROOT/eval3-fail"
mkdir -p "$sbox/wrong"
printf '%s\n' '<html><body></body></html>' > "$sbox/wrong/logic.html"
result=$(cd "$sbox" && EVAL_ID=3 /bin/bash "$VERIFIER")
printf '%s' "$result" | any_fail \
  || fail "eval 3 expected a FAIL for misplaced logic.html, got: $result"


# Semantic failures may produce narrow mechanical PASS, never semantic credit.
sbox="$TEST_ROOT/eval3-pass"
printf '%s\n' '<script src="framework.js"></script>' > "$sbox/memory-bank/working/prototypes/order-cancellation/logic.html"
result=$(cd "$sbox" && EVAL_ID=3 /bin/bash "$VERIFIER")
jq -e '.results | length == 1 and .[0].assertion == "logic.html exists at the requested evaluation path" and .[0].verdict == "PASS"' <<< "$result" >/dev/null \
  || fail 'logic existence check granted credit to unchecked semantic requirements'
python3 - "$VERIFIER" <<'PY'
import json, subprocess, os, sys
from pathlib import Path
verifier=Path(sys.argv[1]); declared=json.loads((verifier.parent/'evals.json').read_text())['evals']
for case in declared:
 if 'verification_script' not in case: continue
 result=subprocess.run(['bash', str(verifier)], env=dict(os.environ,EVAL_ID=str(case['id'])),capture_output=True,text=True,check=True)
 for item in json.loads(result.stdout)['results']:
  assert item['assertion'] in case['assertions'], item['assertion']
PY

echo "PASS: prototype-verifier"
