#!/usr/bin/env bash
set -euo pipefail

verdict() {
  if "$@"; then
    printf PASS
  else
    printf FAIL
  fi
}

# Builds one {assertion, verdict, evidence} object.
emit() {
  jq -n --arg a "$1" --arg v "$2" --arg e "$3" '{assertion:$a, verdict:$v, evidence:$e}'
}

# Combines emit() outputs (one per argument) into {"results":[...]}.
# With no arguments, emits an empty result set.
emit_results() {
  if [[ $# -eq 0 ]]; then
    printf '{"results":[]}'
    return
  fi
  printf '%s\n' "$@" | jq -s '{results: .}'
}

one_plan_exists() {
  [[ "$(find memory-bank/working/plans -name plan.md -type f 2>/dev/null | wc -l | tr -d ' ')" == 1 ]]
}

plan_has_seed_sections() {
  local plan_file
  plan_file="$(find memory-bank/working/plans -name plan.md -type f -print -quit 2>/dev/null)"
  [[ -n "$plan_file" ]] || return 1
  grep -Fq '## Problem' "$plan_file" &&
    grep -Fq '## Solution' "$plan_file" &&
    grep -Fq '## Acceptance criteria' "$plan_file"
}

repository_artifacts_are_clean() {
  unchanged_since_seed memory-bank && unchanged_since_seed src
}

all_tasks_done() {
  local task
  while IFS= read -r task; do
    grep -Eq '^status:[[:space:]]*done[[:space:]]*$' "$task" || return 1
  done < <(find memory-bank/working/plans -path '*/tasks/*.md' -type f)
}

all_criteria_checked() {
  local plan_file="$1"
  awk '
    /^## Acceptance criteria/ {inside=1; next}
    inside && /^## / {inside=0}
    inside && /^- \[ \]/ {unchecked=1}
    END {exit(unchecked ? 1 : 0)}
  ' "$plan_file"
}

node_available() {
  command -v node >/dev/null 2>&1
}

# The setup script commits the fixture as the repository's root commit, so
# "seeded" state stays comparable even if the agent commits its own work.
seed_commit() {
  git rev-list --max-parents=0 HEAD 2>/dev/null | tail -n1
}

unchanged_since_seed() {
  local seed
  seed="$(seed_commit)"
  [[ -n "$seed" ]] &&
    git diff --quiet "$seed" -- "$1" &&
    [[ -z "$(git ls-files --others --exclude-standard -- "$1")" ]]
}

files_changed_since_seed() {
  local seed
  seed="$(seed_commit)"
  {
    [[ -n "$seed" ]] && git diff --name-only "$seed"
    git ls-files --others --exclude-standard
  } | sort -u
}

# Runs the fixture's own `npm test` script (node --test) in a directory.
node_tests_pass() {
  (cd "$1" && node --test --test-timeout=30000 >/dev/null 2>&1)
}

retry_delay_is_exponential_with_jitter() {
  node --input-type=module -e '
    import { pathToFileURL } from "node:url";
    const { retryDelay } = await import(pathToFileURL(process.argv[1]).href);
    const mean = (attempt) => {
      const values = Array.from({ length: 400 }, () => retryDelay(attempt));
      if (!values.every((v) => Number.isFinite(v) && v >= 0)) process.exit(1);
      return [values.reduce((a, b) => a + b, 0) / values.length, new Set(values).size];
    };
    const [m1] = mean(1);
    const [m2, distinct] = mean(2);
    const [m3] = mean(3);
    process.exit(m2 > 1.4 * m1 && m3 > 1.4 * m2 && distinct > 1 ? 0 : 1);
  ' "$PWD/src/queue/worker.mjs" >/dev/null 2>&1
}

cache_invalidation_is_fixed() {
  node --input-type=module -e '
    import { pathToFileURL } from "node:url";
    const { createCache } = await import(pathToFileURL(process.argv[1]).href);
    const cache = createCache();
    cache.set("user:42", "old");
    cache.set("user:7", "old");
    cache.set("session:1", "keep");
    cache.invalidate("user");
    const namespace = cache.get("user:42") === undefined &&
      cache.get("user:7") === undefined && cache.get("session:1") === "keep";
    const exact = createCache();
    exact.set("user:42", "old");
    exact.set("user:7", "keep");
    exact.invalidate("user:42");
    const single = exact.get("user:42") === undefined && exact.get("user:7") === "keep";
    process.exit(namespace && single ? 0 : 1);
  ' "$PWD/src/cache.mjs" >/dev/null 2>&1
}

parser_returns_fixed() {
  node --input-type=module -e '
    import { pathToFileURL } from "node:url";
    const { parse } = await import(pathToFileURL(process.argv[1]).href);
    process.exit(parse("input") === "fixed" ? 0 : 1);
  ' "$PWD/src/parser.mjs" >/dev/null 2>&1
}

# A regression test must be new or changed, pass now, and fail when the
# seeded src/cache.mjs is restored in a scratch copy. Every step fails
# closed: a sandbox-denied mktemp, a failed copy, or a failed git show
# must not be mistaken for a passing regression test.
regression_test_catches_bug() {
  local seed scratch status
  files_changed_since_seed | grep -Eq '^test/|\.test\.m?js$' || return 1
  node_tests_pass . || return 1
  seed="$(seed_commit)"
  [[ -n "$seed" ]] || return 1
  scratch="$(mktemp -d "${TMPDIR:-/tmp}/change-eval.XXXXXX")" || return 1
  cp -R . "$scratch/repo" || { rm -rf "$scratch"; return 1; }
  git show "$seed:src/cache.mjs" > "$scratch/repo/src/cache.mjs" || { rm -rf "$scratch"; return 1; }
  status=0
  node_tests_pass "$scratch/repo" && status=1
  rm -rf "$scratch"
  return "$status"
}

# Process/independence assertions deliberately fall through to the judge.
# File contents and coordinator prose cannot prove a separate reviewer ran.
policy_sources_unchanged() {
  unchanged_since_seed src && unchanged_since_seed test
}

human_choice_is_persisted() {
  one_plan_exists || return 1
  local plan_file
  plan_file="$(find memory-bank/working/plans -name plan.md -type f -print -quit)"
  [[ "$(basename "$(dirname "$plan_file")")" == *-draft ]] || return 1
  grep -Eq '^status:[[:space:]]*backlog[[:space:]]*$' "$plan_file" || return 1
  awk '
    NR == 1 && $0 == "---" {frontmatter=1; next}
    frontmatter && $0 == "---" {frontmatter=0; next}
    frontmatter && /^type:[[:space:]]*plan[[:space:]]*$/ {kind=1}
    frontmatter && /^title:[[:space:]]*[^[:space:]]/ && $0 !~ /^title:[[:space:]]*""[[:space:]]*$/ {title=1}
    END {exit(kind && title ? 0 : 1)}
  ' "$plan_file" || return 1
  plan_has_seed_sections || return 1
  ! find memory-bank/working/plans -path '*/tasks/*' -type f -print -quit | grep -q . || return 1
  awk '
    /^## Open Questions/ {inside=1; next}
    inside && /^## / {inside=0}
    inside && tolower($0) ~ /account/ && tolower($0) ~ /ip/ && tolower($0) !~ /n\/a|^[[:space:]]*-[[:space:]]*resolved/ {found=1}
    END {exit(found ? 0 : 1)}
  ' "$plan_file"
}

parallel_wave_tasks_done() {
  local tasks_dir="memory-bank/working/plans/2026-10-06-parallel-wave/tasks"
  local task_name
  [[ -d "$tasks_dir" ]] || return 1
  [[ "$(find "$tasks_dir" -name '*.md' -type f | wc -l | tr -d ' ')" == 3 ]] || return 1
  for task_name in a b c; do
    [[ -f "$tasks_dir/$task_name.md" ]] &&
      grep -Eq '^status:[[:space:]]*done[[:space:]]*$' "$tasks_dir/$task_name.md" || return 1
  done
}

parallel_wave_test_files_exist() {
  local task_name test_file
  for task_name in a b c; do
    test_file="test/$task_name.test.mjs"
    [[ -f "src/$task_name.mjs" && -f "$test_file" ]] || return 1
    grep -Fq 'node:test' "$test_file" || return 1
    grep -Eq '(^|[^[:alnum:]_.])test[[:space:]]*\(' "$test_file" || return 1
  done
}

parallel_wave_commits_are_ordered() {
  local a_commit b_commit c_commit
  a_commit="$(git log -1 --format=%H HEAD -- src/a.mjs 2>/dev/null)"
  b_commit="$(git log -1 --format=%H HEAD -- src/b.mjs 2>/dev/null)"
  c_commit="$(git log -1 --format=%H HEAD -- src/c.mjs 2>/dev/null)"
  [[ -n "$a_commit" && -n "$b_commit" && -n "$c_commit" ]] || return 1
  [[ "$c_commit" != "$a_commit" && "$c_commit" != "$b_commit" ]] || return 1
  git merge-base --is-ancestor "$a_commit" "$c_commit" 2>/dev/null &&
    git merge-base --is-ancestor "$b_commit" "$c_commit" 2>/dev/null
}

parallel_wave_target_branch_is_seeded() {
  local seed target_branch target_head
  seed="$(seed_commit)"
  target_branch="$(git config --get eval.targetBranch 2>/dev/null)" || return 1
  [[ -n "$seed" && -n "$target_branch" ]] || return 1
  target_head="$(git rev-parse --verify "refs/heads/$target_branch" 2>/dev/null)" || return 1
  [[ "$target_head" == "$seed" ]]
}

case "$EVAL_ID" in
  1)
    unchanged="$(verdict unchanged_since_seed memory-bank)"
    evidence="memory-bank differs from the seed"
    [[ "$unchanged" == PASS ]] && evidence="memory-bank matches the seed"
    emit_results "$(emit "Leaves every plan, task, session note, and legacy handoff file byte-identical" "$unchanged" "$evidence")"
    ;;
  2)
    seeded="$(verdict plan_has_seed_sections)"
    seeded_evidence="plan.md is missing required seed sections"
    [[ "$seeded" == PASS ]] && seeded_evidence="plan.md contains Problem, Solution, and Acceptance criteria"

    one_file="FAIL"
    if one_plan_exists &&
       [[ "$(find memory-bank/working/plans -type f 2>/dev/null | wc -l | tr -d ' ')" == 1 ]] &&
       ! find memory-bank/working/plans -type d -name tasks -print -quit 2>/dev/null | grep -q . &&
       ! grep -Fq '## Tasks' "$(find memory-bank/working/plans -name plan.md -type f -print -quit)"; then
      one_file="PASS"
    fi
    one_file_evidence="unexpected plan or task artifacts exist"
    [[ "$one_file" == PASS ]] && one_file_evidence="exactly one plan.md exists without task artifacts"

    source_unchanged="$(verdict unchanged_since_seed src)"
    source_unchanged_evidence="src differs from the seed"
    [[ "$source_unchanged" == PASS ]] && source_unchanged_evidence="src matches the seed"

    emit_results \
      "$(emit "Creates plan.md seeded with a best guess before asking the first question" "$seeded" "$seeded_evidence")" \
      "$(emit "Produces exactly one file — plan.md — with no ## Tasks section and no tasks/ files" "$one_file" "$one_file_evidence")" \
      "$(emit "Changes no production source during planning" "$source_unchanged" "$source_unchanged_evidence")"
    ;;
  3)
    implemented="FAIL"
    implemented_evidence="retryDelay does not grow exponentially with jitter"
    verified="FAIL"
    verified_evidence="test/worker.test.mjs is missing, the change wasn't implemented, or node --test fails"
    if ! node_available; then
      implemented_evidence="node unavailable"
      verified_evidence="node unavailable"
    else
      if [[ -f src/queue/worker.mjs ]] && retry_delay_is_exponential_with_jitter; then
        implemented="PASS"
        implemented_evidence="mean delay grows at least 1.4x per attempt and samples vary"
      fi
      if [[ -f test/worker.test.mjs ]] &&
         [[ "$implemented" == "PASS" ]] && node_tests_pass .; then
        verified="PASS"
        verified_evidence="node --test passes on the changed worker"
      fi
    fi
    plans_unchanged="$(verdict unchanged_since_seed memory-bank)"
    plans_unchanged_evidence="memory-bank differs from the seed"
    [[ "$plans_unchanged" == PASS ]] && plans_unchanged_evidence="memory-bank matches the seed"

    source_changed="FAIL"
    if ! unchanged_since_seed src; then
      source_changed="PASS"
    fi
    source_changed_evidence="src matches the seed"
    [[ "$source_changed" == PASS ]] && source_changed_evidence="src differs from the seed"

    emit_results \
      "$(emit "Implements exponential backoff with jitter in src/queue/worker.mjs" "$implemented" "$implemented_evidence")" \
      "$(emit "Reports running a test command, and the repository's tests pass on the changed worker" "$verified" "$verified_evidence")" \
      "$(emit "Creates no plan or task artifacts for the micro-change" "$plans_unchanged" "$plans_unchanged_evidence")" \
      "$(emit "Changes production source for the requested bounded change" "$source_changed" "$source_changed_evidence")"
    ;;
  4)
    source_unchanged="$(verdict unchanged_since_seed src)"
    source_unchanged_evidence="src differs from the seed"
    [[ "$source_unchanged" == PASS ]] && source_unchanged_evidence="src matches the seed"

    unchanged="$(verdict unchanged_since_seed memory-bank)"
    unchanged_evidence="memory-bank differs from the seed"
    [[ "$unchanged" == PASS ]] && unchanged_evidence="memory-bank matches the seed"

    emit_results \
      "$(emit "Leaves production source unchanged, reporting evidence instead of building fixes" "$source_unchanged" "$source_unchanged_evidence")" \
      "$(emit "Leaves plan.md acceptance checkboxes and every task status exactly as found" "$unchanged" "$unchanged_evidence")"
    ;;
  5)
    unchanged="$(verdict repository_artifacts_are_clean)"
    evidence="repository artifacts differ from the seed"
    [[ "$unchanged" == PASS ]] && evidence="memory-bank and src match the seed"
    emit_results "$(emit "Leaves group plans and production source unchanged before selection" "$unchanged" "$evidence")"
    ;;
  7)
    delivery_untouched="$(verdict unchanged_since_seed memory-bank/working/plans/notifications/delivery)"
    delivery_evidence="delivery child plan or tasks changed"
    [[ "$delivery_untouched" == PASS ]] && delivery_evidence="delivery child plan and tasks are unchanged"

    schema_status_unmoved="FAIL"
    if grep -Eq '^status:[[:space:]]*backlog[[:space:]]*$' \
      memory-bank/working/plans/notifications/schema/plan.md; then
      schema_status_unmoved="PASS"
    fi
    schema_status_evidence="schema plan moved out of backlog despite its blocked task"
    [[ "$schema_status_unmoved" == PASS ]] && schema_status_evidence="schema plan stays backlog with its task blocked"

    nothing_merged="$(verdict unchanged_since_seed src)"
    nothing_merged_evidence="production source changed even though the schema task is blocked"
    [[ "$nothing_merged" == PASS ]] && nothing_merged_evidence="no production source changed"

    emit_results \
      "$(emit "Never builds or edits the delivery child" "$delivery_untouched" "$delivery_evidence")" \
      "$(emit "Builds the schema child and finds its task blocked, halting immediately" "$schema_status_unmoved" "$schema_status_evidence")" \
      "$(emit "Reports the blocked child, task, and reason without merging anything" "$nothing_merged" "$nothing_merged_evidence")"
    ;;
  8|24)
    plan_file="memory-bank/working/plans/2026-09-20-retry-policy/plan.md"
    named_plan="FAIL"
    if one_plan_exists && [[ -f "$plan_file" ]]; then
      named_plan="PASS"
    fi
    named_plan_evidence="the named plan is missing or another plan exists"
    [[ "$named_plan" == PASS ]] && named_plan_evidence="the named plan remains the only plan"

    decomposed="FAIL"
    if find memory-bank/working/plans/2026-09-20-retry-policy/tasks \
      -name '*.md' -type f -print -quit 2>/dev/null | grep -q .; then
      decomposed="PASS"
    fi
    decomposed_evidence="the named plan contains no task files"
    [[ "$decomposed" == PASS ]] && decomposed_evidence="the named plan contains task files"

    implemented="FAIL"
    if [[ -f src/retry-policy.ts ]] &&
       grep -Eq 'return[[:space:]]+5' src/retry-policy.ts; then
      implemented="PASS"
    fi
    implemented_evidence="retry policy source is missing or incorrect"
    [[ "$implemented" == PASS ]] && implemented_evidence="retry policy source returns 5"

    completed="FAIL"
    if grep -Eq '^status:[[:space:]]*completed[[:space:]]*$' "$plan_file" &&
       [[ "$decomposed" == "PASS" ]] && all_tasks_done; then
      completed="PASS"
    fi
    completed_evidence="plan or task statuses remain incomplete"
    [[ "$completed" == PASS ]] && completed_evidence="plan and task statuses are terminal"

    checked="$(verdict all_criteria_checked "$plan_file")"
    checked_evidence="unchecked acceptance criteria remain"
    [[ "$checked" == PASS ]] && checked_evidence="no unchecked acceptance criteria remain"

    emit_results \
      "$(emit "Builds the named existing plan without creating a replacement plan" "$named_plan" "$named_plan_evidence")" \
      "$(emit "Decomposes the plan specification into task files before implementation" "$decomposed" "$decomposed_evidence")" \
      "$(emit "Creates src/retry-policy.ts with maxAttempts returning 5" "$implemented" "$implemented_evidence")" \
      "$(emit "Marks every generated task done and the plan completed" "$completed" "$completed_evidence")" \
      "$(emit "Verifies and checks every plan acceptance criterion" "$checked" "$checked_evidence")"
    ;;
  9)
    fixed="FAIL"
    fixed_evidence="invalidate(\"user\") still leaves namespaced entries cached"
    regression="FAIL"
    regression_evidence="no new or changed test fails on the seeded source and passes after the fix"
    if ! node_available; then
      fixed_evidence="node unavailable"
      regression_evidence="node unavailable"
    else
      if [[ -f src/cache.mjs ]] && cache_invalidation_is_fixed; then
        fixed="PASS"
        fixed_evidence="invalidate(\"user\") evicts user:* and keeps other entries"
      fi
      if regression_test_catches_bug; then
        regression="PASS"
        regression_evidence="node --test passes now and fails with the seeded src/cache.mjs"
      fi
    fi
    emit_results \
      "$(emit "Fixes the reported symptom: invalidating a namespace evicts its namespaced entries" "$fixed" "$fixed_evidence")" \
      "$(emit "Adds a regression test that fails on the seeded source and passes after the fix" "$regression" "$regression_evidence")"
    ;;
  10)
    unchanged="$(verdict unchanged_since_seed src)"
    evidence="src differs from the seed commit"
    [[ "$unchanged" == PASS ]] && evidence="src matches the seed commit with no untracked files"
    emit_results "$(emit "Leaves production source byte-identical to the seed" "$unchanged" "$evidence")"
    ;;
  11)
    unchanged="$(verdict unchanged_since_seed src)"
    evidence="src differs from the seed"
    [[ "$unchanged" == PASS ]] && evidence="src matches the seed"
    emit_results "$(emit "Leaves production source unchanged" "$unchanged" "$evidence")"
    ;;
  12)
    changed="FAIL"
    changed_evidence="parser source is unchanged or parse() does not return fixed"
    verified="FAIL"
    verified_evidence="test/parser.test.mjs is missing, was changed, or node --test fails"
    if ! node_available; then
      changed_evidence="node unavailable"
      verified_evidence="node unavailable"
    else
      if [[ -f src/parser.mjs ]] && ! unchanged_since_seed src && parser_returns_fixed; then
        changed="PASS"
        changed_evidence="parse() returns fixed"
      fi
      if [[ -f test/parser.test.mjs ]] && unchanged_since_seed test/parser.test.mjs &&
         node_tests_pass .; then
        verified="PASS"
        verified_evidence="the seeded parser test passes unchanged"
      fi
    fi
    emit_results \
      "$(emit "Changes the seeded parser source so parse() returns \"fixed\"" "$changed" "$changed_evidence")" \
      "$(emit "Reports running a test command, and the unchanged parser test passes" "$verified" "$verified_evidence")"
    ;;
  13)
    unchanged="FAIL"
    evidence="the draft or finalized plan file changed"
    if unchanged_since_seed memory-bank/working/plans/2026-09-01-alpha &&
       unchanged_since_seed memory-bank/working/plans/2026-09-02-beta-draft; then
      unchanged="PASS"
      evidence="both plan files remain unchanged"
    fi
    emit_results "$(emit "Leaves both plan files unchanged" "$unchanged" "$evidence")"
    ;;
  14)
    task_file="memory-bank/working/plans/2026-09-21-logger-fix/tasks/flush-on-exit.md"
    no_new_tasks="FAIL"
    if [[ "$(find memory-bank/working/plans/2026-09-21-logger-fix/tasks -name '*.md' -type f | wc -l | tr -d ' ')" == 1 ]]; then
      no_new_tasks="PASS"
    fi
    no_new_tasks_evidence="a task file other than flush-on-exit.md was created"
    [[ "$no_new_tasks" == PASS ]] && no_new_tasks_evidence="only the assigned task file exists"

    implemented="FAIL"
    if [[ -f src/logger.ts ]] && awk '
        /close\(\)[[:space:]]*:[[:space:]]*void[[:space:]]*\{/ {inside=1}
        inside && /flush\(/ {found=1}
        inside && /^[[:space:]]*\}/ {inside=0}
        END {exit(found ? 0 : 1)}
      ' src/logger.ts; then
      implemented="PASS"
    fi
    implemented_evidence="close() does not call flush()"
    [[ "$implemented" == PASS ]] && implemented_evidence="close() calls flush() before returning"

    parent_progress="FAIL"
    if [[ -f "$task_file" ]] &&
       grep -Eq '^status:[[:space:]]*in_progress[[:space:]]*$' "$task_file" &&
       unchanged_since_seed "$task_file"; then
      parent_progress="PASS"
    fi
    parent_progress_evidence="the task file changed from its in_progress seed state"
    [[ "$parent_progress" == PASS ]] && parent_progress_evidence="the task remains in_progress and the task file is unchanged for orchestrator-owned Progress"

    emit_results \
      "$(emit "Creates no additional task files" "$no_new_tasks" "$no_new_tasks_evidence")" \
      "$(emit "Implements flush() in src/logger.ts's close() method" "$implemented" "$implemented_evidence")" \
      "$(emit "Reports evidence without editing task Progress; leaves the task in_progress for the orchestrator" "$parent_progress" "$parent_progress_evidence")"
    ;;
  15)
    old_dir="memory-bank/working/plans/2026-09-10-widget-exporter-draft"
    new_dir="memory-bank/working/plans/2026-09-10-widget-exporter"

    renamed="FAIL"
    if [[ ! -d "$old_dir" ]] && [[ -f "$new_dir/plan.md" ]]; then
      renamed="PASS"
    fi
    renamed_evidence="the draft directory was not renamed to a title-derived slug"
    [[ "$renamed" == PASS ]] && renamed_evidence="the plan directory is renamed to $new_dir"

    plan_file="$new_dir/plan.md"
    [[ -f "$plan_file" ]] || plan_file="$old_dir/plan.md"

    backlog="FAIL"
    if [[ -f "$plan_file" ]] && grep -Eq '^status:[[:space:]]*backlog[[:space:]]*$' "$plan_file"; then
      backlog="PASS"
    fi
    backlog_evidence="the plan's status changed away from backlog"
    [[ "$backlog" == PASS ]] && backlog_evidence="the plan stays status: backlog"

    no_tasks="PASS"
    if [[ -d "$new_dir/tasks" ]] || [[ -d "$old_dir/tasks" ]]; then
      no_tasks="FAIL"
    fi
    no_tasks_evidence="task files were created during finalize"
    [[ "$no_tasks" == PASS ]] && no_tasks_evidence="no task files were created"

    emit_results \
      "$(emit "Renames the plan directory from its -draft id to a slug derived from the title" "$renamed" "$renamed_evidence")" \
      "$(emit "Leaves the plan's status as backlog after finalizing" "$backlog" "$backlog_evidence")" \
      "$(emit "Does not create task files or start building" "$no_tasks" "$no_tasks_evidence")"
    ;;
  16)
    redirected="FAIL"
    if find redirected/working/plans -name plan.md -type f -print -quit 2>/dev/null | grep -q . &&
       ! find memory-bank/working/plans -name plan.md -type f -print -quit 2>/dev/null | grep -q .; then
      redirected="PASS"
    fi
    emit_results "$(emit "Writes the plan under the configured working path, not the repo default" "$redirected" "configured path: redirected/working/plans")"
    ;;
  21)
    clean="$(verdict policy_sources_unchanged)"
    emit_results "$(emit "Leaves src and test byte-identical to the seed when independent review is unavailable" "$clean" "compared source and tests against seed, including committed and untracked edits")"
    ;;
  22)
    clean="$(verdict policy_sources_unchanged)"
    planned="$(verdict human_choice_is_persisted)"
    emit_results \
      "$(emit "Leaves production source and test byte-identical while the human choice is unresolved" "$clean" "compared source and tests against seed")" \
      "$(emit "Persists the unresolved rate-limit scope in a draft plan without task files" "$planned" "requires draft plan, live account/IP Open Question, and no tasks")"
    ;;
  26|27)
    session_id="fixture-session-2026-10-07"
    session_hash="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())' "$session_id")"
    expected="memory-bank/working/session-notes/2026-10-06-session-$session_hash/notes.md"
    path="FAIL"
    [[ -f "$expected" ]] && path="PASS"
    count="$(find memory-bank/working/session-notes -type f -name notes.md -path "*session-$session_hash/notes.md" | wc -l | tr -d ' ')"
    one_note="FAIL"
    [[ "$count" == 1 ]] && one_note="PASS"

    formatted="FAIL"
    if [[ -f "$expected" ]] && python3 - "$expected" "$EVAL_ID" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
eval_id = sys.argv[2]
text = path.read_text(encoding="utf-8")
frontmatter, _, body = text.partition("\n---\n")
required_fields = (
    "type: session-notes", "status: open", "description:", "timestamp:",
    "cwd:", "keywords:", "repo_root:", "branch:", "head_sha:",
    "dirty:", "links:",
)
required_sections = (
    "# Session notes:", "## Rules", "## Decisions", "## What's left",
    "## Suggested next skill",
)
valid = all(field in frontmatter for field in required_fields)
valid = valid and all(section in body for section in required_sections)
sys.exit(0 if valid else 1)
PY
    then
      formatted="PASS"
    fi

    refreshed="PASS"
    if [[ "$EVAL_ID" == 27 ]]; then
      refreshed="FAIL"
      if [[ -f "$expected" ]] && grep -Fq 'timestamp: 2026-10-07T00:05:00Z' "$expected" &&
         grep -Fq 'Second milestone refreshed' "$expected"; then
        refreshed="PASS"
      fi
    fi

    if [[ "$EVAL_ID" == 27 ]]; then
      emit_results \
        "$(emit "Uses the original reserved first-date path keyed by the SHA-256 session ID" "$path" "$expected")" \
        "$(emit "Uses the session-notes frontmatter and body format" "$formatted" "requires all standard frontmatter fields and template headings")" \
        "$(emit "Changes the existing note timestamp and milestone content" "$refreshed" "requires the next UTC timestamp and refreshed body marker")" \
        "$(emit "Leaves exactly one session note for this session" "$one_note" "found $count matching session note(s)")"
    else
      emit_results \
        "$(emit "Uses the original reserved first-date path keyed by the SHA-256 session ID" "$path" "$expected")" \
        "$(emit "Uses the session-notes frontmatter and body format" "$formatted" "requires all standard frontmatter fields and template headings")" \
        "$(emit "Leaves exactly one session note for this session" "$one_note" "found $count matching session note(s)")"
    fi
    ;;
  23|25)
    tasks_done="$(verdict parallel_wave_tasks_done)"
    task_files="$(verdict parallel_wave_test_files_exist)"
    ordered_commits="$(verdict parallel_wave_commits_are_ordered)"
    target_unchanged="$(verdict parallel_wave_target_branch_is_seeded)"
    node_tests="FAIL"
    node_tests_evidence="focused test files are missing or node --test failed"
    if [[ "$task_files" == "PASS" ]] && node_available && node --test >/dev/null 2>&1; then
      node_tests="PASS"
      node_tests_evidence="node --test passed on the resulting branch"
    elif ! node_available; then
      node_tests_evidence="node unavailable"
    fi

    emit_results \
      "$(emit "Marks all three parallel-wave task files done" "$tasks_done" "requires exactly a.md, b.md, and c.md with status: done")" \
      "$(emit "Creates one source module and one node:test file for each task" "$task_files" "requires src/a.mjs, src/b.mjs, src/c.mjs and their three focused tests")" \
      "$(emit "Makes the c task commit descend from the a and b task commits" "$ordered_commits" "checks commits touching each task source on the resulting branch")" \
      "$(emit "Leaves the fixture target branch at the seed commit through the finish choice" "$target_unchanged" "compares the recorded target branch head with the root seed commit")" \
      "$(emit "Passes the fixture tests with node --test on the resulting branch" "$node_tests" "$node_tests_evidence")"
    ;;
  *)
    printf 'unsupported change eval id: %s\n' "$EVAL_ID" >&2
    exit 2
    ;;
esac
