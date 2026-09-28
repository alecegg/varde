# Correctness findings

Findings are ordered by impact. Locations identify the reviewed baseline; line numbers may move after fixes. Options are distinct alternatives. The first option is recommended in each finding.

## [CORRECTNESS-001] Inherited subjects reject worktree executors

**Severity:** high
**Label:** triage
**Disposition:** fix
**Location:** `skills/varde-change/references/build-dispatch.md:101`

### Summary

Parent subjects bind their exact repository directory. Parallel and refactor workers inherit that subject but check it from another worktree. commands/review.rs:152 derives the current repository; review_gates.rs:766 rejects the mismatch. An isolated main/linked reproduction returned exit 4 review_invalid, even with shared working storage.

Value/cost: The broken branch matters, but its remedy changes a shared policy or execution contract.

### Solutions

1. **Recommended:** Add an explicitly authorized worktree binding and separate change evidence.
2. Approve a separate subject for each worktree.
3. Execute serially in the subject checkout.

**Status:** **Fixed:** option 1. Explicit parent bindings now pin registered Git identity, scope, task and approval; start/resume reject stale or escaped execution. Inspection, verified release and non-destructive abandonment retain separate evidence. Every archived binding requires combined final review. Workflow workspace tests pass, including 39 review-gate integration tests.

**Decision:** User selected option 1. Explicitly authorize linked worktrees under the parent subject, register each worktree and its task scope, reuse approval only within that scope, track changes separately, and review the combined result before completion. Do not accept arbitrary repository directories.

## [CORRECTNESS-002] Group orchestration has no parent approval

**Severity:** high
**Label:** triage
**Disposition:** fix
**Location:** `skills/varde-change/references/orchestrate.md:60`

### Summary

Split groups skip finalization. Children obtain subjects, but Finish transitions the parent backlog to active then completed without a parent subject. review_checkpoints.rs:120 and review_gates.rs:618 require one. Isolated transition reproduction returned exit 4 review_missing. Resumed active parents would also attempt active to active.

Value/cost: The broken branch matters, but its remedy changes a shared policy or execution contract.

### Solutions

1. **Recommended:** Define aggregate group approval and checkpoints before activation and completion.
2. Define a CLI bookkeeping exemption with child-readiness enforcement.
3. Leave the parent incomplete until aggregate evidence exists.

**Status:** **Fixed:** option 1. Groups now obtain independent aggregate approval before activation; active resume uses its legal checkpoint, child gates remain, and combined review precedes conclusion. Feature checkouts own exact-root subjects and tracked bookkeeping. Disposable CLI gate fixture and full skill suite pass.

**Decision:** User selected option 1. Give the group its own aggregate review subject and approval/checkpoints. Review overall scope and child dependencies before activation, review the combined result before completion, and preserve an already-active group state on resume.

## [CORRECTNESS-003] Knowledge handoff evals grade fixtures instead of runs

**Severity:** high
**Label:** auto-fix
**Disposition:** fix
**Location:** `skills/varde-knowledge/evals/verify-knowledge-eval.sh:104`

### Summary

Case 9 returned four PASS assertions without an evaluated session by inspecting fixtures, instruction text, prompts, and expected output. Case 8 has the same pattern. grade.rs:143 removes mechanically graded assertions from judge input, so these assertions cannot detect incorrect agent behavior.

Value/cost: A bounded correction removes a concrete failure with little maintenance cost.

### Solutions

1. **Recommended:** Return no mechanical grades for cases 8 and 9 so the judge uses session evidence.
2. Turn cases into real sandbox tasks and inspect produced artifacts.
3. Verify captured tool events and resulting handoffs.

**Status:** **Fixed:** option 1. Cases 8/9 return empty mechanical results; unchanged assertions go to session-evidence judging. Regression check passes.

## [CORRECTNESS-004] Case 8 emits undeclared assertions

**Severity:** medium
**Label:** auto-fix
**Disposition:** fix
**Location:** `skills/varde-knowledge/evals/verify-knowledge-eval.sh:99`

### Summary

The first two emitted assertion strings differ from evals.json case 8. grade.rs:260 rejects undeclared assertions, aborting deterministic grading.

Value/cost: A bounded correction removes a concrete failure with little maintenance cost.

### Solutions

1. **Recommended:** Use judge fallback together with the preceding fix.
2. Align the emitted text exactly (leaves false positives).
3. Introduce shared assertion identifiers.

**Status:** **Fixed:** option 1. Removed undeclared static assertion output together with the false-positive path.

## [CORRECTNESS-005] Parallel spikes require forbidden source commits

**Severity:** medium
**Label:** triage
**Disposition:** fix
**Location:** `skills/varde-change/references/build-parallel.md:16`

### Summary

build-plan.md:49 and build-execution.md:34 require spikes to revert changes and commit nothing. Parallel integration requires a task commit, audits its paths, and merges it. Resume exempts spike commits but normal dispatch does not. Static branch contradiction, no model-run reproduction.

Value/cost: The broken branch matters, but its remedy changes a shared policy or execution contract.

### Solutions

1. **Recommended:** Keep spikes serial and skip their source-commit audit.
2. Support no-source-commit workers throughout parallel integration.
3. Route spikes only to design or prototype work.

**Status:** **Fixed:** option 1. Spikes route serially, revert exploratory source, retain findings/verification, and skip only their source-commit audit. Normal tasks retain commit ownership checks. Routing regression and full skill suite pass.

**Decision:** User selected option 1. Run spikes serially, skip their source-commit audit, and retain findings and verification evidence. Preserve the requirement to revert exploratory changes and commit no source changes.

## [CORRECTNESS-006] Approved human-only fixes return to triage

**Severity:** medium
**Label:** triage
**Disposition:** fix
**Location:** `skills/varde-review/references/fix-pass.md:75`

### Summary

fix.md:82 records a chosen fix and dispatches bounded build. The build gate rejects always-triage categories again and clears disposition. Eval case 3 expressly expects rejection even after parent triage. No terminal implementation branch honors the approval.

Value/cost: The broken branch matters, but its remedy changes a shared policy or execution contract.

### Solutions

1. **Recommended:** Distinguish approved bounded fixes from automatic application.
2. Provide a separate human-only implementation route.
3. Declare permanent manual handling and remove dispatch.

**Status:** **Fixed:** option 1. Selected bounded fixes carry the concrete solution and traceable user approval; missing approval still defers. Automatic restrictions and scope/spec/independent gates remain. Approved/unapproved eval cases and routing regression pass.

**Decision:** User selected option 1. Keep automatic application of human-decision categories blocked, but honor explicit user approval for a selected bounded fix through normal independent review and verification. Preserve the recorded decision instead of clearing it, and update the contradictory eval expectation.

## [CORRECTNESS-007] Prototype verifier cannot see external artifacts

**Severity:** medium
**Label:** triage
**Disposition:** fix
**Location:** `skills/varde-prototype/evals/verify-prototype-eval.sh:15`

### Summary

Visual and logic outputs live under resolved working storage, possibly external. Verifier searches only sandbox cwd (grade.rs:212). An external valid logic.html with a separate verifier cwd produced FAIL logic.html missing. Existing local-path fixture tests pass.

Value/cost: The broken branch matters, but its remedy changes a shared policy or execution contract.

### Solutions

1. **Recommended:** Configure isolated fixture-local memory and explicit artifact paths.
2. Pass working storage through the evaluator contract.
3. Validate artifact paths from captured execution.

**Status:** **Fixed:** option 1. Per-case environment overrides configure fresh sandbox-local storage consistently for setup, harness and verifier; reserved keys fail before launch. Prototype verifiers check exact paths. Mock harness isolation tests, prototype fixtures and full learn tests pass.

**Decision:** User selected option 1. Configure each prototype evaluation with isolated working storage inside its run sandbox and explicit expected artifact paths. Verify only that run’s outputs and do not read or write personal working storage.

## [CORRECTNESS-008] Docs refresh omits indexed-query setup

**Severity:** medium
**Label:** auto-fix
**Disposition:** fix
**Location:** `skills/varde-docs/references/refresh.md:16`

### Summary

Refresh directly invokes context_pack without loading the local varde-code reference. Unlike spec mode, it omits watcher readiness, envelope handling, and source fallback. query/mod.rs:139 reports index_missing without an index.

Value/cost: A bounded correction removes a concrete failure with little maintenance cost.

### Solutions

1. **Recommended:** Load the existing local code reference before queries.
2. Inline readiness and fallback instructions.
3. Use direct source search only.

**Status:** **Fixed:** option 1 applied; targeted checks passed.

## [CORRECTNESS-009] Spec rewrite boundary excludes required provenance

**Severity:** medium
**Label:** auto-fix
**Disposition:** fix
**Location:** `skills/varde-docs/references/spec-format.md:68`

### Summary

The generated-block rule permits only sentinel interior edits, but current sources, hashes, roots, and covered paths must be updated in frontmatter. Stale provenance blocks conclusion.rs:923 and :981.

Value/cost: A bounded correction removes a concrete failure with little maintenance cost.

### Solutions

1. **Recommended:** Explicitly permit provenance edits while preserving the Notes tail.
2. Separate metadata and body update phases.
3. Build a dedicated metadata updater.

**Status:** **Fixed:** option 1 applied; targeted checks passed.

## [CORRECTNESS-010] Codex trigger command lacks required skill path

**Severity:** medium
**Label:** auto-fix
**Disposition:** fix
**Location:** `skills/varde-learn/references/evals.md:59`

### Summary

The universal command omits --skill-path. trigger.rs:186 requires an existing SKILL.md for Codex and errors before launching sessions. Installed help confirms the flag.

Value/cost: A bounded correction removes a concrete failure with little maintenance cost.

### Solutions

1. **Recommended:** Add a Codex-specific invocation with an existing absolute SKILL.md.
2. Require reading help before constructing a command.
3. Implement CLI path discovery.

**Status:** **Fixed:** option 1 applied; targeted checks passed.

## [CORRECTNESS-011] Diagnosis never resolves its report store

**Severity:** medium
**Label:** auto-fix
**Disposition:** fix
**Location:** `skills/varde-learn/references/diagnose.md:80`

### Summary

Diagnosis requires a resolved working store for snapshots and reports (:180), but its independently usable entry point and reference never resolve it.

Value/cost: A bounded correction removes a concrete failure with little maintenance cost.

### Solutions

1. **Recommended:** Resolve paths before intake while preserving caller-supplied paths.
2. Ask for the output location each run.
3. Add a diagnosis output-directory option.

**Status:** **Fixed:** option 1 applied; targeted checks passed.

## [CORRECTNESS-012] Resume assumes every collision has a valid worktree

**Severity:** medium
**Label:** auto-fix
**Disposition:** fix
**Location:** `skills/varde-change/references/orchestrate.md:49`

### Summary

Resume treats worktree-create exit 3 as a recoverable expected path. worktree-create.sh:79 also returns 3 for branch-only collisions. The directory can be absent or unrelated.

Value/cost: A bounded correction removes a concrete failure with little maintenance cost.

### Solutions

1. **Recommended:** Check registered path and expected branch, stopping on mismatch.
2. Reconstruct a missing worktree through a separate recovery decision.
3. Use distinct script collision exit codes.

**Status:** **Fixed:** option 1 applied; targeted checks passed.

## [CORRECTNESS-015] Storage fixture contradicts shared worktree memory

**Severity:** medium
**Label:** auto-fix
**Disposition:** fix
**Location:** `skills/tests/build-finish-storage-brief.sh:14`

### Summary

The fixture configures main and linked worktree stores sequentially and requires distinct results. Current memory.rs:494 and :570 normalize both to the main checkout; memory_paths.rs:783 tests this deliberately shared behavior. The second setting replaces the first. The full skill suite and an isolated direct rerun both failed with “fixture did not give the worktree a distinct memory store.”

Value/cost: a small test correction restores meaningful verification of the intended storage contract.

### Solutions

1. **Recommended:** configure the main checkout once and assert shared root, working, and knowledge; retain parent-brief checks.
2. Use independent clones to test genuinely different project stores.
3. Remove the runtime fixture and retain only structural briefing assertions.

**Status:** **Fixed:** option 1 applied; targeted checks passed.

## [CORRECTNESS-013] Escalated triage points to the wrong step

**Severity:** low
**Label:** auto-fix
**Disposition:** fix
**Location:** `skills/varde-change/references/orchestrate.md:56`

### Summary

Finish points to build-plan-finish step 2, which dispatches review. Step 3 owns triage and application.

Value/cost: A bounded correction removes a concrete failure with little maintenance cost.

### Solutions

1. **Recommended:** Correct the reference to step 3.
2. Name the findings procedure instead of numbering.
3. Add a stable heading and link.

**Status:** **Fixed:** option 1 applied; targeted checks passed.

## [CORRECTNESS-014] Micro-change expectation describes obsolete approval

**Severity:** low
**Label:** auto-fix
**Disposition:** fix
**Location:** `skills/varde-change/evals/evals.json:34`

### Summary

Eval 3 expected_output describes in-memory approval; the current route requires a persisted bounded JSON contract, initialized subject, reviewer-authored record, and checkpoint.

Value/cost: A bounded correction removes a concrete failure with little maintenance cost.

### Solutions

1. **Recommended:** Describe the actual gate mechanism.
2. Refer to the owning route without duplicating mechanics.
3. Create a separate gate-specific eval.

**Status:** **Fixed:** option 1 applied; targeted checks passed.
