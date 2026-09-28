#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_DIR="$SKILLS_DIR/varde-change"
SETUP="$SKILL_DIR/evals/setup-change-eval.sh"
VERIFY="$SKILL_DIR/evals/verify-change-eval.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/change-eval-fixtures.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# The redirect fixture must resolve through paths.toml, while its verifier
# rejects the repo-default location.
redirect_root="$TEST_ROOT/redirect-eval"
mkdir -p "$redirect_root"
(
  cd "$redirect_root"
  EVAL_ID=16 EVAL_CONFIG=with_skill EVAL_RUN=1 \
    EVAL_RUN_DIR="$redirect_root/run" EVAL_SKILL_DIR="$SKILL_DIR" \
    EVAL_SANDBOX_DIR="$redirect_root" bash "$SETUP"
)
resolved="$(cd "$redirect_root" && VARDE_CONFIG_DIR="$redirect_root/config" varde-workflow paths --json | jq -r '.data.working')"
[[ "$resolved" == "$(cd "$redirect_root/redirected/working" && pwd -P)" ]] || fail "redirect fixture did not resolve configured working path: $resolved"
mkdir -p "$resolved/plans/example"
printf '%s\n' '---' 'status: draft' '---' > "$resolved/plans/example/plan.md"
(
  cd "$redirect_root"
  EVAL_ID=16 EVAL_CONFIG=with_skill EVAL_RUN=1 \
    EVAL_RUN_DIR="$redirect_root/run" EVAL_SKILL_DIR="$SKILL_DIR" \
    EVAL_SANDBOX_DIR="$redirect_root" bash "$VERIFY"
) | jq -e '.results[0].verdict == "PASS"' >/dev/null || fail "redirect fixture verifier rejected configured plan"

assert_json() {
  local file="$1" expression="$2" message="$3"
  jq -e "$expression" "$file" >/dev/null || fail "$message"
}

# Positive cases must grade every emitted assertion as PASS. The grader no
# longer emits every declared assertion for every eval — assertions it drops
# fall through to the LLM judge — so this only requires that whatever it does
# emit is (a) a real declared assertion for this eval id and (b) passing.
assert_all_pass() {
  local id="$1" file="$2" message="$3"
  jq -e --argjson eval_id "$id" \
    --slurpfile catalog "$SKILL_DIR/evals/evals.json" '
      ($catalog[0].evals[] | select(.id == $eval_id) | .assertions) as $declared |
      ((.results | length) > 0) and
      (.results | all(.verdict == "PASS")) and
      ([.results[].assertion] | all(. as $a | $declared | index($a) != null))
    ' "$file" >/dev/null || fail "$message"
}

# Negative cases must fail the targeted assertion (by index).
assert_fails() {
  local file="$1" index="$2" message="$3"
  jq -e --argjson i "$index" '.results[$i].verdict == "FAIL"' "$file" >/dev/null ||
    fail "$message"
}

have_node=1
if ! command -v node >/dev/null 2>&1; then
  have_node=0
  echo "SKIP: node unavailable; skipping node-graded cases for evals 3, 9, and 12" >&2
fi

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

states_table="$SKILL_DIR/references/varde-workflow-cli.md"
legal_states="$(grep -E '^\| `(plan|task)` \|' "$states_table" |
  sed -E 's/^\| `[a-z]+` \| ([^|]+) \|.*/\1/' | tr ',' '\n' | tr -d '` ' | sort -u)"
bad_states="$(grep -rhoE 'status: *[a-z_]+' "$SKILL_DIR"/references/*.md |
  grep -v 'status: open\|status: closed' |
  sed -E 's/status: *//' | sort -u |
  grep -vxFf <(printf '%s\n' "$legal_states") || true)"
[ -z "$bad_states" ] || fail "non-schema state literal(s) in varde-change references: $bad_states"

status_root="$(setup_case 1)"
mkdir -p "$status_root/run"
cat > "$status_root/run/transcript.txt" <<'TRANSCRIPT'
Routed through references/status.md.
Active plan: 2026-09-18-active.
Open handoff: 2026-09-19-open.
Recommended next mode: varde-change build. Stop here.
TRANSCRIPT
verify_case 1 "$status_root" "$TEST_ROOT/status-clean.json"
assert_all_pass 1 "$TEST_ROOT/status-clean.json" \
  "status fixture reports unchanged files as changed"
printf '%s\n' changed >> "$status_root/memory-bank/working/plans/2026-09-18-active/plan.md"
verify_case 1 "$status_root" "$TEST_ROOT/status-dirty.json"
assert_json "$TEST_ROOT/status-dirty.json" '.results[0].verdict == "FAIL"' \
  "status fixture misses changed plan files"
git -C "$status_root" add memory-bank
git -C "$status_root" commit -qm "forbidden committed plan edit"
verify_case 1 "$status_root" "$TEST_ROOT/status-committed.json"
assert_fails "$TEST_ROOT/status-committed.json" 0 \
  "status fixture misses committed plan edits"

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
Routed through references/plan-start.md.
Which limit scope should the plan use?

  1. Per client
  2. Global

Recommendation: 1 because clients need isolation.
TRANSCRIPT
verify_case 2 "$plan_root" "$TEST_ROOT/plan.json"
assert_all_pass 2 "$TEST_ROOT/plan.json" \
  "planning fixture rejects a valid seeded plan"
mkdir -p "$plan_root/src"
printf '%s\n' changed > "$plan_root/src/untracked.ts"
verify_case 2 "$plan_root" "$TEST_ROOT/plan-dirty.json"
assert_json "$TEST_ROOT/plan-dirty.json" '.results[2].verdict == "FAIL"' \
  "planning fixture misses untracked source files"

build_root="$(setup_case 3)"
mkdir -p "$build_root/run"
cat > "$build_root/run/transcript.txt" <<'TRANSCRIPT'
Routed through references/build.md.
Implemented exponential backoff with jitter.
Ran `node --test test/worker.test.mjs`: 1 passed.
TRANSCRIPT
if [ "$have_node" -eq 1 ]; then
  cat > "$build_root/src/queue/worker.mjs" <<'SOURCE'
const BASE_DELAY_MS = 1000;

export function retryDelay(attempt) {
  const ceiling = BASE_DELAY_MS * 2 ** attempt;
  return ceiling / 2 + Math.random() * (ceiling / 2);
}
SOURCE
  verify_case 3 "$build_root" "$TEST_ROOT/build.json"
  assert_all_pass 3 "$TEST_ROOT/build.json" \
    "build fixture rejects valid direct micro-change behavior"

  # Negative: a named check whose re-run fails.
  cat >> "$build_root/test/worker.test.mjs" <<'TEST'

test("broken check", () => {
  assert.equal(1, 2);
});
TEST
  verify_case 3 "$build_root" "$TEST_ROOT/build-failing-check.json"
  assert_fails "$TEST_ROOT/build-failing-check.json" 1 \
    "build fixture accepts a check that fails on re-run"
  git -C "$build_root" checkout -q -- test/worker.test.mjs

  # Negative: exponential growth without jitter.
  cat > "$build_root/src/queue/worker.mjs" <<'SOURCE'
export function retryDelay(attempt) {
  return 1000 * 2 ** attempt;
}
SOURCE
  verify_case 3 "$build_root" "$TEST_ROOT/build-no-jitter.json"
  assert_fails "$TEST_ROOT/build-no-jitter.json" 0 \
    "build fixture accepts exponential backoff without jitter"
  assert_fails "$TEST_ROOT/build-no-jitter.json" 1 \
    "build fixture accepts verification of an incomplete change"

  # Negative: jitter on a fixed delay.
  cat > "$build_root/src/queue/worker.mjs" <<'SOURCE'
export function retryDelay(attempt) {
  return 1000 + Math.random() * 100;
}
SOURCE
  verify_case 3 "$build_root" "$TEST_ROOT/build-fixed-jitter.json"
  assert_fails "$TEST_ROOT/build-fixed-jitter.json" 0 \
    "build fixture accepts jitter without exponential growth"
fi

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
assert_all_pass 4 "$TEST_ROOT/verify-clean.json" \
  "verification fixture reports untouched plans as changed"

# Positive: classifications under section headings.
cp "$verify_root/run/transcript.txt" "$verify_root/run/transcript.good"
cat > "$verify_root/run/transcript.txt" <<'TRANSCRIPT'
Criteria for 2026-08-10-manage-command:

### Passed (2)
- `test -f src/manage.ts` exits 0.
- `src/manage.ts` contains `export function manage`.

### Unavailable (1)
- The compatibility checker: `manage-compat-check` is not on PATH.

### Failed (1)
- `src/manage.ts` returns "ready", not "legacy".

Run varde-change build when fixes are wanted.
TRANSCRIPT
verify_case 4 "$verify_root" "$TEST_ROOT/verify-sections.json"
assert_all_pass 4 "$TEST_ROOT/verify-sections.json" \
  "verification fixture rejects outcomes grouped under headings"

mv "$verify_root/run/transcript.good" "$verify_root/run/transcript.txt"

printf '%s\n' changed >> "$verify_root/memory-bank/working/plans/2026-08-10-manage-command/plan.md"
verify_case 4 "$verify_root" "$TEST_ROOT/verify-dirty.json"
assert_fails "$TEST_ROOT/verify-dirty.json" 1 \
  "verification fixture misses plan mutations"
printf '%s\n' 'export function fixed() {}' >> "$verify_root/src/manage.ts"
verify_case 4 "$verify_root" "$TEST_ROOT/verify-source-edit.json"
assert_fails "$TEST_ROOT/verify-source-edit.json" 0 \
  "verification fixture misses source edits"

group_root="$(setup_case 5)"
mkdir -p "$group_root/run"
cat > "$group_root/run/transcript.txt" <<'TRANSCRIPT'
Routed through references/orchestrate.md.
Found one incomplete group: notifications (shape: group).
Children: schema (backlog), delivery (backlog, depends on schema).
Select the notifications group to run it; nothing has run yet.
TRANSCRIPT
verify_case 5 "$group_root" "$TEST_ROOT/group-clean.json"
assert_all_pass 5 "$TEST_ROOT/group-clean.json" \
  "group fixture rejects a valid discovery walkthrough"
printf '%s\n' changed >> "$group_root/memory-bank/working/plans/notifications/plan.md"
verify_case 5 "$group_root" "$TEST_ROOT/group-dirty.json"
assert_fails "$TEST_ROOT/group-dirty.json" 0 \
  "group fixture misses orchestration mutations"

named_group_root="$(setup_case 7)"
mkdir -p "$named_group_root/run"
cat > "$named_group_root/run/transcript.txt" <<'TRANSCRIPT'
Expected order: schema then delivery.
Built the schema child first; its one task is already blocked on a product
decision. Halted immediately: no delivery, nothing merged.
TRANSCRIPT
verify_case 7 "$named_group_root" "$TEST_ROOT/named-group-clean.json"
assert_all_pass 7 "$TEST_ROOT/named-group-clean.json" \
  "named-group fixture rejects a valid blocked-child run"
printf '%s\n' changed >> "$named_group_root/memory-bank/working/plans/notifications/delivery/plan.md"
verify_case 7 "$named_group_root" "$TEST_ROOT/named-group-dirty.json"
assert_fails "$TEST_ROOT/named-group-dirty.json" 0 \
  "named-group fixture misses the delivery child being touched past a blocked schema task"

existing_build_root="$(setup_case 8)"
mkdir -p "$existing_build_root/memory-bank/working/plans/2026-09-20-retry-policy/tasks"
mkdir -p "$existing_build_root/src"
cat > "$existing_build_root/memory-bank/working/plans/2026-09-20-retry-policy/tasks/implement.md" <<'TASK'
---
type: task
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

# Eval 9: fix mode against a real, reproducible cache bug.
fix_root="$(setup_case 9)"
[ -f "$fix_root/ISSUE.md" ] || fail "debug fixture lacks ISSUE.md"
jq -e '.scripts.test == "node --test"' "$fix_root/package.json" >/dev/null ||
  fail "debug fixture lacks a node --test script"
mkdir -p "$fix_root/run"
cat > "$fix_root/run/transcript.txt" <<'TRANSCRIPT'
Fixing: reproduce, then change.
Reproduction: after invalidate("user"), get("user:42") still returns the old value.
Hypotheses: invalidate deletes only the exact key.
Experiments: invalidate("user:42") evicts; invalidate("user") does not.
Implementation begins after the evidence gate.
Cause: invalidate deleted only the exact key, not the namespace.
Verification: the regression test and original reproduction pass.
TRANSCRIPT
if [ "$have_node" -eq 1 ]; then
  (cd "$fix_root" && node --test >/dev/null 2>&1) ||
    fail "debug fixture seeds a failing test suite"
  (cd "$fix_root" && node --input-type=module -e '
    import { createCache } from "./src/cache.mjs";
    const cache = createCache();
    cache.set("user:42", "old");
    cache.invalidate("user");
    process.exit(cache.get("user:42") === "old" ? 0 : 1);
  ') || fail "debug fixture does not reproduce the ISSUE.md symptom"

  cat > "$fix_root/test/invalidate.test.mjs" <<'TEST'
import assert from "node:assert/strict";
import test from "node:test";
import { createCache } from "../src/cache.mjs";

test("invalidate evicts namespaced entries", () => {
  const cache = createCache();
  cache.set("user:42", "old");
  cache.invalidate("user");
  assert.equal(cache.get("user:42"), undefined);
});
TEST
  # Negative: regression test added but the source is still broken.
  verify_case 9 "$fix_root" "$TEST_ROOT/debug-9-unfixed.json"
  assert_fails "$TEST_ROOT/debug-9-unfixed.json" 0 \
    "debug eval 9 accepts an unfixed cache"
  assert_fails "$TEST_ROOT/debug-9-unfixed.json" 1 \
    "debug eval 9 accepts a regression test that fails after the fix"

  sed -i.bak 's/entries.delete(prefix);/for (const key of [...entries.keys()]) { if (key === prefix || key.startsWith(prefix + ":")) entries.delete(key); }/' \
    "$fix_root/src/cache.mjs"
  rm -f "$fix_root/src/cache.mjs.bak"
  verify_case 9 "$fix_root" "$TEST_ROOT/debug-9.json"
  assert_all_pass 9 "$TEST_ROOT/debug-9.json" \
    "debug eval 9 rejects a verified fix with a regression test"

  # Negative: fix without a regression test.
  mv "$fix_root/test/invalidate.test.mjs" "$TEST_ROOT/invalidate.test.mjs"
  verify_case 9 "$fix_root" "$TEST_ROOT/debug-9-no-test.json"
  assert_fails "$TEST_ROOT/debug-9-no-test.json" 1 \
    "debug eval 9 accepts a fix without a regression test"

  # Negative: a new test that passes on the seeded source too.
  cat > "$fix_root/test/shallow.test.mjs" <<'TEST'
import assert from "node:assert/strict";
import test from "node:test";
import { createCache } from "../src/cache.mjs";

test("invalidate evicts the exact key", () => {
  const cache = createCache();
  cache.set("user", "old");
  cache.invalidate("user");
  assert.equal(cache.get("user"), undefined);
});
TEST
  verify_case 9 "$fix_root" "$TEST_ROOT/debug-9-shallow-test.json"
  assert_fails "$TEST_ROOT/debug-9-shallow-test.json" 1 \
    "debug eval 9 accepts a test that does not catch the bug"
  rm "$fix_root/test/shallow.test.mjs"
  mv "$TEST_ROOT/invalidate.test.mjs" "$fix_root/test/invalidate.test.mjs"

  # Negative: a fix that evicts everything, not just the namespace.
  cp "$fix_root/src/cache.mjs" "$TEST_ROOT/cache.fixed"
  sed -i.bak 's/for (const key of .*$/entries.clear();/' "$fix_root/src/cache.mjs"
  rm -f "$fix_root/src/cache.mjs.bak"
  verify_case 9 "$fix_root" "$TEST_ROOT/debug-9-overbroad.json"
  assert_fails "$TEST_ROOT/debug-9-overbroad.json" 0 \
    "debug eval 9 accepts a fix that clears unrelated entries"
  cp "$TEST_ROOT/cache.fixed" "$fix_root/src/cache.mjs"
fi

# Eval 10: diagnose only; no node needed.
diagnose_root="$(setup_case 10)"
mkdir -p "$diagnose_root/run"
cat > "$diagnose_root/run/transcript.txt" <<'TRANSCRIPT'
Diagnosing only; I won't change code.
Reproduction: after invalidate("user"), get("user:42") still returns the old value.
Hypotheses: invalidate deletes only the exact key.
Experiments: invalidate("user:42") evicts; invalidate("user") does not.
Evidence limit: I cannot confirm when the regression shipped; no fix was attempted.
TRANSCRIPT
verify_case 10 "$diagnose_root" "$TEST_ROOT/debug-10.json"
assert_all_pass 10 "$TEST_ROOT/debug-10.json" \
  "debug eval 10 rejects a diagnosis-only report"
printf '%s\n' '// instrumentation' >> "$diagnose_root/src/cache.mjs"
verify_case 10 "$diagnose_root" "$TEST_ROOT/debug-10-edit.json"
assert_fails "$TEST_ROOT/debug-10-edit.json" 0 \
  "debug eval 10 accepts a source edit"
git -C "$diagnose_root" checkout -q -- src/cache.mjs
git -C "$diagnose_root" add -A
git -C "$diagnose_root" -c user.email=x@example.invalid -c user.name=x \
  commit -qm "agent commit" --allow-empty
printf '%s\n' '// committed edit' >> "$diagnose_root/src/cache.mjs"
git -C "$diagnose_root" commit -qam "agent commits an edit"
verify_case 10 "$diagnose_root" "$TEST_ROOT/debug-10-committed-edit.json"
assert_fails "$TEST_ROOT/debug-10-committed-edit.json" 0 \
  "debug eval 10 misses a committed source edit"

# Eval 11: explicit exploration.
explore_root="$(setup_case 11)"
mkdir -p "$explore_root/run"
cat > "$explore_root/run/transcript.txt" <<'TRANSCRIPT'
This is an exploration request, so varde-explore owns it; not entering debug mode.
TRANSCRIPT
verify_case 11 "$explore_root" "$TEST_ROOT/explore.json"
assert_all_pass 11 "$TEST_ROOT/explore.json" \
  "explore fixture rejects an exploration handoff"

# Eval 12: explicit build with a seeded failing parser test.
parser_root="$(setup_case 12)"
mkdir -p "$parser_root/run"
cat > "$parser_root/run/transcript.txt" <<'TRANSCRIPT'
Explicit build: changed parse() to return "fixed".
Ran `npm test`: 1 passed.
TRANSCRIPT
if [ "$have_node" -eq 1 ]; then
  if (cd "$parser_root" && node --test >/dev/null 2>&1); then
    fail "parser fixture seeds a passing test"
  fi
  # Negative: verification claimed on unchanged source.
  verify_case 12 "$parser_root" "$TEST_ROOT/parser-unchanged.json"
  assert_fails "$TEST_ROOT/parser-unchanged.json" 0 \
    "parser fixture accepts unchanged source"
  assert_fails "$TEST_ROOT/parser-unchanged.json" 1 \
    "parser fixture accepts a failing verification"

  cat > "$parser_root/src/parser.mjs" <<'SOURCE'
export function parse(_input) {
  return 'fixed';
}
SOURCE
  verify_case 12 "$parser_root" "$TEST_ROOT/parser.json"
  assert_all_pass 12 "$TEST_ROOT/parser.json" \
    "parser fixture rejects a verified direct fix"

  # Negative: the seeded test was rewritten to pass.
  sed -i.bak 's/"fixed")/parse("input"))/' "$parser_root/test/parser.test.mjs"
  rm -f "$parser_root/test/parser.test.mjs.bak"
  verify_case 12 "$parser_root" "$TEST_ROOT/parser-test-edited.json"
  assert_fails "$TEST_ROOT/parser-test-edited.json" 1 \
    "parser fixture accepts a rewritten parser test"
fi

# Policy fixtures verify observable filesystem effects. They do not pretend
# synthetic prose proves that an independent agent reviewed anything.
unavailable_root="$(setup_case 21)"
verify_case 21 "$unavailable_root" "$TEST_ROOT/unavailable-clean.json"
assert_all_pass 21 "$TEST_ROOT/unavailable-clean.json" "reviewer-unavailable fixture rejects untouched source"
printf '%s\n' '// forbidden edit' >> "$unavailable_root/src/parser.mjs"
git -C "$unavailable_root" commit -qam 'forbidden source edit'
verify_case 21 "$unavailable_root" "$TEST_ROOT/unavailable-edited.json"
assert_fails "$TEST_ROOT/unavailable-edited.json" 0 "reviewer-unavailable fixture misses committed implementation"

human_root="$(setup_case 22)"
mkdir -p "$human_root/memory-bank/working/plans/rate-limit-draft"
cat > "$human_root/memory-bank/working/plans/rate-limit-draft/plan.md" <<'PLAN'
---
status: backlog
title: Add API rate limiting
type: plan
---

## Problem

The public API has no rate limit.

## Solution

Add a limit after the user chooses its identity scope.

## Acceptance criteria

- [ ] Requests beyond the configured limit are rejected.

## Open Questions

- Should the limit apply per account or per IP?
PLAN
verify_case 22 "$human_root" "$TEST_ROOT/human-choice.json"
assert_all_pass 22 "$TEST_ROOT/human-choice.json" "human-choice fixture rejects unresolved persisted scope"
human_plan="$human_root/memory-bank/working/plans/rate-limit-draft/plan.md"
cp "$human_plan" "$TEST_ROOT/human-plan-valid.md"
cat > "$human_plan" <<'PLAN'
---
status: backlog
---
## Open Questions

- Should the limit apply per account or per IP?
PLAN
verify_case 22 "$human_root" "$TEST_ROOT/human-choice-malformed.json"
assert_fails "$TEST_ROOT/human-choice-malformed.json" 1 "human-choice fixture accepts missing plan metadata and seed sections"
cp "$TEST_ROOT/human-plan-valid.md" "$human_plan"
printf '%s\n' '// guessed implementation' > "$human_root/src/limits.mjs"
verify_case 22 "$human_root" "$TEST_ROOT/human-choice-edit.json"
assert_fails "$TEST_ROOT/human-choice-edit.json" 0 "human-choice fixture misses untracked production source"
rm "$human_root/src/limits.mjs"
printf '%s\n' '## Tasks' > "$human_root/memory-bank/working/plans/rate-limit-draft/tasks.md"
mkdir -p "$human_root/memory-bank/working/plans/rate-limit-draft/tasks"
printf '%s\n' 'Implement guessed scope' > "$human_root/memory-bank/working/plans/rate-limit-draft/tasks/implement.md"
verify_case 22 "$human_root" "$TEST_ROOT/human-choice-tasks.json"
assert_fails "$TEST_ROOT/human-choice-tasks.json" 1 "human-choice fixture accepts executable tasks before decision"

echo "change output eval fixtures passed"
