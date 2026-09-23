#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_DIR="$SKILLS_DIR/varde-change"
SETUP="$SKILL_DIR/evals/setup-change-eval.sh"
VERIFY="$SKILL_DIR/evals/verify-change-eval.sh"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_json() {
  local file="$1" expression="$2" message="$3"
  jq -e "$expression" "$file" >/dev/null || fail "$message"
}

setup_case() {
  local id="$1" root="$TEST_ROOT/eval-$1"
  mkdir -p "$root"
  (
    cd "$root"
    EVAL_ID="$id" EVAL_CONFIG=with_skill EVAL_RUN=1 \
      EVAL_RUN_DIR="$root/run" EVAL_SKILL_DIR="$SKILL_DIR" \
      EVAL_SANDBOX_DIR="$root" bash "$SETUP"
  )
  printf '%s\n' "$root"
}

verify_case() {
  local id="$1" root="$2" output="$3"
  (
    cd "$root"
    EVAL_ID="$id" EVAL_CONFIG=with_skill EVAL_RUN=1 \
      EVAL_RUN_DIR="$root/run" EVAL_SKILL_DIR="$SKILL_DIR" \
      EVAL_SANDBOX_DIR="$root" bash "$VERIFY"
  ) > "$output"
}

jq -e '.evals[0:5] | all(.setup_script == "evals/setup-change-eval.sh" and .verification_script == "evals/verify-change-eval.sh")' \
  "$SKILL_DIR/evals/evals.json" >/dev/null || fail "representative evals lack scripts"
jq -e '
  ([.evals[].id] | index(8)) != null and
  (.evals[] | select(.id == 8) | .assertions | length) == 5
' "$SKILL_DIR/evals/evals.json" >/dev/null || fail "existing-plan eval is missing"
grep -Fq 'Review-only requests belong to `varde-review`.' "$SKILL_DIR/SKILL.md" || \
  fail "review-only requests lack explicit ownership routing"
grep -Fq 'references/build-micro-change.md' \
  "$SKILL_DIR/references/build.md" || \
  fail "build router omits micro-change branch"
grep -Fq 'references/build-plan.md' \
  "$SKILL_DIR/references/build.md" || \
  fail "build router omits plan-run branch"
grep -Fq 'references/build-existing-plan.md' \
  "$SKILL_DIR/references/build.md" || \
  fail "build router omits existing-plan branch"
grep -Fq 'varde-workflow conclude' \
  "$SKILL_DIR/references/build-existing-plan.md" || \
  fail "existing-plan branch omits plan finish"
grep -Fq 'status: todo' \
  "$SKILL_DIR/references/build-decomposition.md" || \
  fail "decomposition uses a non-schema task state"
verify_words="$(wc -w < "$SKILL_DIR/references/verify.md" | tr -d ' ')"
((verify_words < 450)) || fail "verification guidance exceeds 449 words"
status_words="$(wc -w < "$SKILL_DIR/references/status.md" | tr -d ' ')"
((status_words < 250)) || fail "status guidance exceeds 249 words"
grep -Fq 'varde-code context_pack' \
  "$SKILL_DIR/references/plan-start.md" || \
  fail "planning omits scoped Varde Code discovery"
grep -Fq 'varde-code batch' \
  "$SKILL_DIR/references/build-micro-change.md" || \
  fail "micro-change execution omits batched Varde Code context"
grep -Fq 'varde-code batch' \
  "$SKILL_DIR/references/build-existing-plan.md" || \
  fail "existing-plan execution omits batched Varde Code context"
grep -Fq 'references/plan-start.md' \
  "$SKILL_DIR/references/plan.md" || \
  fail "plan router omits new-plan branch"

status_root="$(setup_case 1)"
mkdir -p "$status_root/run"
cat > "$status_root/run/transcript.txt" <<'TRANSCRIPT'
Routed through references/status.md.
Active plan: 2026-09-18-active.
Open handoff: 2026-09-19-open.
Recommended next mode: varde-change build. Stop here.
TRANSCRIPT
verify_case 1 "$status_root" "$TEST_ROOT/status-clean.json"
assert_json "$TEST_ROOT/status-clean.json" \
  '([.results[].verdict] | all(. == "PASS"))' \
  "status fixture reports unchanged files as changed"
printf '%s\n' changed >> "$status_root/memory-bank/working/plans/2026-09-18-active/plan.md"
verify_case 1 "$status_root" "$TEST_ROOT/status-dirty.json"
assert_json "$TEST_ROOT/status-dirty.json" '.results[2].verdict == "FAIL"' \
  "status fixture misses changed plan files"

plan_root="$(setup_case 2)"
mkdir -p "$plan_root/memory-bank/working/plans/rate-limiting"
cat > "$plan_root/memory-bank/working/plans/rate-limiting/plan.md" <<'PLAN'
## Problem

The public API needs rate limiting.

## Solution

Add configurable client limits.

## Acceptance criteria

- [ ] Requests are limited.
PLAN
mkdir -p "$plan_root/run"
cat > "$plan_root/run/transcript.txt" <<'TRANSCRIPT'
Routed through references/plan.md.
Which limit scope should the plan use?

  1. Per client
  2. Global

Recommendation: 1 because clients need isolation.
TRANSCRIPT
verify_case 2 "$plan_root" "$TEST_ROOT/plan.json"
assert_json "$TEST_ROOT/plan.json" \
  '([.results[].verdict] | all(. == "PASS"))' \
  "planning fixture rejects a valid seeded plan"
sed 's/^Recommendation:/My recommendation is/' \
  "$plan_root/run/transcript.txt" > "$plan_root/run/transcript.tmp"
mv "$plan_root/run/transcript.tmp" "$plan_root/run/transcript.txt"
verify_case 2 "$plan_root" "$TEST_ROOT/plan-natural-recommendation.json"
assert_json "$TEST_ROOT/plan-natural-recommendation.json" \
  '.results[4].verdict == "PASS"' \
  "planning fixture rejects a natural recommendation label"
mkdir -p "$plan_root/src"
printf '%s\n' changed > "$plan_root/src/untracked.ts"
verify_case 2 "$plan_root" "$TEST_ROOT/plan-dirty.json"
assert_json "$TEST_ROOT/plan-dirty.json" '.results[3].verdict == "FAIL"' \
  "planning fixture misses untracked source files"

build_root="$(setup_case 3)"
cat > "$build_root/src/queue/worker.ts" <<'SOURCE'
export function retryDelay(attempt: number): number {
  return 2 ** attempt + Math.random();
}
SOURCE
mkdir -p "$build_root/run"
cat > "$build_root/run/transcript.txt" <<'TRANSCRIPT'
Routed through references/build.md.
Implemented exponential backoff with jitter.
Verification check passed for retry behavior.
TRANSCRIPT
verify_case 3 "$build_root" "$TEST_ROOT/build.json"
assert_json "$TEST_ROOT/build.json" \
  '([.results[].verdict] | all(. == "PASS"))' \
  "build fixture rejects valid direct micro-change behavior"

verify_root="$(setup_case 4)"
mkdir -p "$verify_root/run"
cat > "$verify_root/run/transcript.txt" <<'TRANSCRIPT'
Routed through references/verify.md.
Passed: test -f src/manage.ts.
Passed: export function manage.
Unavailable: manage-compat-check does not exist.
Failed: expected return "legacy" was absent.
Run varde-change build when fixes are wanted.
TRANSCRIPT
verify_case 4 "$verify_root" "$TEST_ROOT/verify-clean.json"
assert_json "$TEST_ROOT/verify-clean.json" \
  '([.results[].verdict] | all(. == "PASS"))' \
  "verification fixture reports untouched plans as changed"
printf '%s\n' changed >> "$verify_root/memory-bank/working/plans/2026-08-10-manage-command/plan.md"
verify_case 4 "$verify_root" "$TEST_ROOT/verify-dirty.json"
assert_json "$TEST_ROOT/verify-dirty.json" '.results[2].verdict == "FAIL"' \
  "verification fixture misses plan mutations"

group_root="$(setup_case 5)"
verify_case 5 "$group_root" "$TEST_ROOT/group-clean.json"
assert_json "$TEST_ROOT/group-clean.json" '.results[0].verdict == "PASS"' \
  "group fixture reports untouched repository state as changed"
printf '%s\n' changed >> "$group_root/memory-bank/working/plans/notifications/plan.md"
verify_case 5 "$group_root" "$TEST_ROOT/group-dirty.json"
assert_json "$TEST_ROOT/group-dirty.json" '.results[0].verdict == "FAIL"' \
  "group fixture misses orchestration mutations"

grep -Fq 'references/orchestration-discovery.md' \
  "$SKILL_DIR/references/orchestrate.md" || \
  fail "orchestration router omits discovery reference"
grep -Fq 'references/orchestration-run.md' \
  "$SKILL_DIR/references/orchestrate.md" || \
  fail "orchestration router omits named-run reference"
grep -Fq 'Present them, then stop' \
  "$SKILL_DIR/references/orchestration-discovery.md" || \
  fail "discovery branch omits selection stop"
grep -Fq 'stop immediately' \
  "$SKILL_DIR/references/orchestration-run.md" || \
  fail "named-run branch omits failure stopping"

jq -e '
  .evals[6].id == 7 and
  (.evals[6].assertions | length) == 4 and
  .evals[6].setup_script == "evals/setup-change-eval.sh" and
  .evals[6].verification_script == "evals/verify-change-eval.sh"
' "$SKILL_DIR/evals/evals.json" >/dev/null || fail "named-group eval contract is incomplete"

named_group_root="$(setup_case 7)"
mkdir -p "$named_group_root/run"
cat > "$named_group_root/run/transcript.txt" <<'TRANSCRIPT'
Schema child is backlog.
Delivery child is backlog.
Build each child sequentially through varde-change build.
If schema fails, halt immediately: no delivery.
Nothing executed or modified during this walkthrough.
TRANSCRIPT
verify_case 7 "$named_group_root" "$TEST_ROOT/named-group-ambiguous.json"
assert_json "$TEST_ROOT/named-group-ambiguous.json" '.results[0].verdict == "FAIL"' \
  "named-group fixture accepts mentions without an explicit order"
cat > "$named_group_root/run/transcript.txt" <<'TRANSCRIPT'
Expected order: schema then delivery.
Build each child sequentially through varde-change build.
If schema fails, halt immediately: no delivery.
Nothing executed or modified during this walkthrough.
TRANSCRIPT
verify_case 7 "$named_group_root" "$TEST_ROOT/named-group-clean.json"
assert_json "$TEST_ROOT/named-group-clean.json" '
  [.results[].assertion] == [
    "Orders the schema child before delivery using the declared dependency",
    "Delegates child plans sequentially through varde-change build",
    "Stops immediately after a failed child without running later children",
    "Leaves group plans and production source unchanged during the walkthrough"
  ] and
  ([.results[].verdict] | all(. == "PASS"))
' "named-group fixture rejects a valid walkthrough"
cat > "$named_group_root/run/transcript.txt" <<'TRANSCRIPT'
Expected order: schema then delivery.
Build each child sequentially through varde-change build.
If schema blocks or fails, I stop there: `delivery` doesn't run.
Nothing executed or modified during this walkthrough.
TRANSCRIPT
verify_case 7 "$named_group_root" "$TEST_ROOT/named-group-natural-stop.json"
assert_json "$TEST_ROOT/named-group-natural-stop.json" \
  '.results[2].verdict == "PASS"' \
  "named-group fixture rejects equivalent failure-stop wording"
printf '%s\n' changed >> "$named_group_root/memory-bank/working/plans/notifications/schema/plan.md"
verify_case 7 "$named_group_root" "$TEST_ROOT/named-group-dirty.json"
assert_json "$TEST_ROOT/named-group-dirty.json" '
  [.results[0:3][].verdict] == ["PASS", "PASS", "PASS"] and
  .results[3].verdict == "FAIL"
' \
  "named-group fixture misses orchestration mutations"

existing_build_root="$(setup_case 8)"
mkdir -p "$existing_build_root/memory-bank/working/plans/2026-09-20-retry-policy/tasks"
mkdir -p "$existing_build_root/src"
cat > "$existing_build_root/memory-bank/working/plans/2026-09-20-retry-policy/tasks/implement.md" <<'TASK'
---
type: task
parent: 2026-09-20-retry-policy
status: done
depends_on: []
modifies: []
creates: [src/retry-policy.ts]
---

Implement retry policy.
TASK
cat > "$existing_build_root/src/retry-policy.ts" <<'SOURCE'
export function maxAttempts(): number {
  return 5;
}
SOURCE
sed -e 's/^status: active$/status: completed/' \
  -e 's/^- \[ \]/- [x]/' \
  "$existing_build_root/memory-bank/working/plans/2026-09-20-retry-policy/plan.md" \
  > "$existing_build_root/plan.tmp"
mv "$existing_build_root/plan.tmp" \
  "$existing_build_root/memory-bank/working/plans/2026-09-20-retry-policy/plan.md"
verify_case 8 "$existing_build_root" "$TEST_ROOT/existing-build.json"
assert_json "$TEST_ROOT/existing-build.json" \
  '([.results[].verdict] | all(. == "PASS"))' \
  "existing-plan fixture rejects completed work"
sed 's/^status: done$/status: backlog/' \
  "$existing_build_root/memory-bank/working/plans/2026-09-20-retry-policy/tasks/implement.md" \
  > "$existing_build_root/task.tmp"
mv "$existing_build_root/task.tmp" \
  "$existing_build_root/memory-bank/working/plans/2026-09-20-retry-policy/tasks/implement.md"
verify_case 8 "$existing_build_root" "$TEST_ROOT/existing-build-incomplete.json"
assert_json "$TEST_ROOT/existing-build-incomplete.json" \
  '.results[3].verdict == "FAIL"' \
  "existing-plan fixture misses incomplete tasks"

for eval_id in 9 10; do
  debug_root="$(setup_case "$eval_id")"
  mkdir -p "$debug_root/run"
  if [ "$eval_id" -eq 9 ]; then
    cat > "$debug_root/run/transcript.txt" <<'TRANSCRIPT'
Routed through references/debugging-entry.md.
debug_mode: fix
route_source: automatic
Reproduction: cache remains stale.
Hypotheses: invalidation skips nested entries.
Experiments: nested entries reproduce the failure.
Implementation begins after the evidence gate.
Cause: nested entries bypassed invalidation.
Verification: the reproduction and regression checks pass.
TRANSCRIPT
    printf '%s\n' fixed > "$debug_root/src/cache.ts"
  else
    cat > "$debug_root/run/transcript.txt" <<'TRANSCRIPT'
Routed through references/debugging-entry.md.
debug_mode: diagnose
route_source: explicit
Reproduction: cache remains stale.
Hypotheses: invalidation skips nested entries.
Experiments: nested entries reproduce the failure.
Evidence limit: no fix was attempted.
TRANSCRIPT
  fi
  verify_case "$eval_id" "$debug_root" "$TEST_ROOT/debug-$eval_id.json"
  jq -e --argjson eval_id "$eval_id" \
    --slurpfile catalog "$SKILL_DIR/evals/evals.json" '
      ([.results[].assertion] == [
        $catalog[0].evals[] | select(.id == $eval_id) | .assertions[]
      ]) and ([.results[].verdict] | all(. == "PASS"))
    ' "$TEST_ROOT/debug-$eval_id.json" >/dev/null || \
    fail "debug eval $eval_id verifier differs from declarations"

  cat > "$debug_root/run/transcript.txt" <<'TRANSCRIPT'
Routed through references/debugging-entry.md.
Reproduction: cache remains stale.
Hypotheses: invalidation skips nested entries.
Experiments: nested entries reproduce the failure.
Implementation begins after the evidence gate.
Cause: nested entries bypassed invalidation.
Verification: the reproduction and regression checks pass.
Evidence limit: no fix was attempted.
TRANSCRIPT
  if [ "$eval_id" -eq 9 ]; then
    printf '%s\n' 'route_source: automatic' >> "$debug_root/run/transcript.txt"
  else
    printf '%s\n' 'route_source: explicit' >> "$debug_root/run/transcript.txt"
  fi
  verify_case "$eval_id" "$debug_root" "$TEST_ROOT/debug-$eval_id-generic.json"
  assert_json "$TEST_ROOT/debug-$eval_id-generic.json" \
    '.results[0].verdict == "FAIL"' \
    "debug eval $eval_id accepts a generic debugging-entry path"

  if [ "$eval_id" -eq 9 ]; then
    printf '%s\n' 'debug_mode: fix' > "$debug_root/run/transcript.txt"
  else
    printf '%s\n' 'debug_mode: diagnose' > "$debug_root/run/transcript.txt"
  fi
  verify_case "$eval_id" "$debug_root" "$TEST_ROOT/debug-$eval_id-mode-only.json"
  assert_json "$TEST_ROOT/debug-$eval_id-mode-only.json" \
    '.results[0].verdict == "FAIL"' \
    "debug eval $eval_id accepts a missing route source"
done

echo "change output eval fixtures passed"
