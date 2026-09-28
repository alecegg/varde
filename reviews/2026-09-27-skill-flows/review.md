---
type: review
date: 2026-09-27
target: all ten repository skills and their CLI/agent consumption paths
status: complete
categories: [CORRECTNESS, ARCHITECTURE, CODE]
triage_status: complete
---

# Skill flow and integration review

15 confirmed findings: 3 high, 10 medium, 2 low. All 15 are fixed and verified. Ten bounded findings were fixed in the first pass; the user selected option 1 for each of the five remaining decisions before their combined implementation. Independent final review and the completion gate passed. Changes remain uncommitted.

[Findings and proposed solutions](CORRECTNESS.md). [Architecture notes](ARCHITECTURE.md). [Code notes](CODE.md).

## Categories

| Category | Status | Findings |
|---|---|---|
| CORRECTNESS | complete | 15 |
| ARCHITECTURE | complete | Cross-contract defects recorded under correctness |
| CODE | complete | Verifier defects recorded under correctness |

## Scope and method

Reviewed the current checkout as a complete skill-flow audit, rather than a diff. Three independent audits covered all ten skills; the coordinator checked installers, generated agent capabilities, shared reference contracts, and test wiring. Read entry dispatch, all routed references, scripts, assets, eval declarations and validators. Compared handoffs with CLI help and relevant implementation/tests in code, workflow, learn, and toz. The starting tree was clean.

Applied `varde-agent-doc-authoring` adversarial review to agent instructions: evaluated correctness, loading cost, concise wording, and terminal outcomes. Used `varde-review` for finding persistence and `varde-change` for fixes. Knowledge flow, schema, conclusion, shared-memory and review-gate references under memory-bank/knowledge informed integration checks. Source and tests took precedence where instructions disagreed.

## Branch coverage

| Skill / integration | Branches followed to terminal outcome | Evidence and limits |
|---|---|---|
| Change | Entry precedence; status; plan start/resume/interview/growth/criteria/split; bounded and persisted build; decomposition; inline/parallel/auto; task testing; debug diagnose/fix; refactor; spike; retry/signoff/usage; verify; orchestrate discovery/order/resume/finish; worktree create/merge/cleanup | All routed documents, templates, scripts and evals; actual workflow gate/transition code; reproduced worktree identity and group activation rejection |
| Review | Report scope/budget/categories/rollup; fix standalone/build/eligibility/rollback/triage; PR intake; simplify; scan candidates; visual platform/interactions/evidence | References, evals, agent capability contracts, CLI scan/query/gate source; authenticated GitHub and live UI branches inspected only |
| Agent doc authoring | Author/revise; independent review; triggering; frontmatter errors; workflow layout; reference checks | Instructions, validator, fixtures; deterministic authoring suite and all ten frontmatter validations |
| Docs | Refresh one/module/multiple; proposal versus write; spec incremental/full/domain/architecture/orphans/index; boundaries/provenance/staleness | References, setup/evals and workflow conclusion validation; sentinel/provenance contradiction verified against code |
| Prototype | Visual rounds/variants/navigation; logic states/walkthrough; resolved storage; feedback/handoff; verifier branches | References and eval tooling; reproduced external artifact false FAIL; local verifier fixtures pass |
| Explore | Explanation/options/code tracing; chat/HTML; target ambiguity; PR; indexed queries/partial results/fallback | Entry/reference/eval inspection plus code help/source; no live PR intake |
| Knowledge | Search CLI/fallback; create/update/sign-off/deprecate/delete; reconcile; reflect skip/write; Git/non-Git handoff; resume zero/one/multiple; link current/modified/missing/legacy | References, fixtures, CLI search; reproduced no-session static verifier PASS and assertion-name mismatch |
| Learn | Capture CLI missing/denial/duplicate/new/pagination; reconcile; distill insufficient/approval/decline/eval/adoption; recurrence; diagnosis live/frozen/current/past/unknown/cutoff/delegation/capture; trigger/output/judge | CLI declarations/source/help and all routes; no paid sessions, private transcript intake, or friction/adoption mutations |
| Manage | Checkout discovery/sync/subset/unowned; settings/privacy/paths; pattern/SQL rule authoring/test/deploy; declarative/script profiles/trust/fixture/production match | References and actual installer/CLI declarations; installation tests use disposable targets, production adapters unchanged |
| Toz | Search/list/chunk/line/raw/records; command/read/mixed batching; partial streams; sandbox retry; doctor; Learn/Manage handoffs | Skill and CLI/API inspection; used capture/query in this review; production raw/profile and OS backend permutations not executed |
| Agents and packaging | Plan/executor/review/explore role handoffs; review evidence write exception; selected finding dispatch; generated harness adapters; managed/unowned/subset/migration; flat/self-contained installed references | Agent integration scripts, consolidated test, skills install-catalogue/check-refs/vendored-copy checks |

This is a complete static traversal of documented routes, with targeted runtime reproductions. It is not exhaustive runtime proof of every model, OS, UI, authentication, tool failure, or input permutation. Paid evaluations were not run. The five shared-contract remedies were discussed individually; the user selected option 1 for each before combined implementation began.

## Retained behavior and cost judgment

Kept the entry-point dispatchers, independent review gates, source-grounded claims, optional query fallbacks, per-finding rollback, Notes-tail preservation, visual evidence rules, knowledge/friction ownership, scoped worktree cleanup, and local storage privacy. Conditional references usually prevent irrelevant loading; there was no demonstrated reason to merge or rewrite whole flows. Tiny wording fixes address actual failures rather than stylistic uniformity.

## Verification

Before fixes: check-refs passed; all agent integration scripts and consolidated agent checks passed. Full skills benchmark suite failed only build-finish-storage-brief.sh, reproduced directly; its expectation contradicts the shared-memory CLI contract. Remaining skill checks passed, including authoring, change eval fixtures, docs scope, all ten frontmatters, parallel scheduler, prototype verifier, review selection, review gates, diagnosis structure, storage guard, vendored copies and worktree merging. Initial toz-store and watcher sandbox access failed; unchanged escalated retries succeeded. A direct system-Python validation attempt in an audit lacked PyYAML; the supported uv only-system validation in the full suite passed.

Fixes use bounded subject `skill-flow-fixes-20260927` with reviewer-authored CLI evidence. The first-pass contract and gate records are in the configured local working store. That pass changed no CLI source or installed binaries.

## Applied fixes

Ten findings fixed through nine corrections: knowledge cases 8/9 now defer behavioral assertions to the judge; Codex trigger commands supply the required skill file; diagnosis resolves private storage; refresh loads query readiness/fallback; spec generation allows current provenance; orchestration validates resumed worktree identity and points to the right triage step; micro-change eval text matches the mechanical gate; the storage fixture asserts intentionally shared linked-worktree memory. A new regression prevents fixture-only handoff grading.

The five changed instruction references grew from 3,879 to 4,016 words (+137). This adds missing operational contracts; removing static behavioral grading shrank the knowledge verifier by 130 lines. No whole-flow restructuring was justified.

## Decisions selected for the combined fix

1. Worktree authorization: explicitly bind isolated execution to approved subjects and preserve trustworthy change coverage (CORRECTNESS-001).
2. Group authorization: define aggregate gate semantics and legal resume/completion transitions (CORRECTNESS-002).
3. Spike dispatch, human-approved always-triage fixes, and isolated prototype eval output paths (CORRECTNESS-005, 006, 007).

The decision log below records the selected solution for each finding.

Post-fix: `bash skills/tests/benchmark-foundation.sh` passed the complete skill suite and packaged-reference checks. `bash agents/test-consolidated-skills.sh` and every `agents/tests/*.sh` passed. The new knowledge regression, corrected shared-storage fixture, eval JSON parsing, and `git diff --check` passed. No paid harness/judge sessions ran; judge fallback was verified in grader source rather than claiming model accuracy.

Independent pre-edit and entire-subject implementation reviews were approved and recorded directly by the reviewer. The final `varde-workflow review check --checkpoint complete` passed with no blockers. Required `varde-agent-doc-authoring` review covered every edited skill reference, eval expectation, and verifier script; no further defects were found in the changed scope.

First-pass outcome: 10 fixed, 0 reverted; 5 deferred for discussion. Changes remain uncommitted in this checkout. No CLI rebuild was required for that first pass.

## Decision log

- CORRECTNESS-001: option 1 chosen by the user. Explicit parent-subject worktree authorization with scoped registration, separate change evidence, and combined final review. Selected before implementation; included in the combined fix.

- CORRECTNESS-002: option 1 chosen by the user. Aggregate group approval and checkpoints before activation and completion, with combined-result review and legal resume transitions. Selected before implementation; included in the combined fix.

- CORRECTNESS-005: option 1 chosen by the user. Run spikes serially, skip source-commit auditing, and preserve findings, verification evidence, and the no-source-commit contract. Selected before implementation; included in the combined fix.

- CORRECTNESS-006: option 1 chosen by the user. Honor explicit approval for selected bounded fixes while retaining automatic-application restrictions and normal review/verification gates; update the contradictory eval. Selected before implementation; included in the combined fix.

- CORRECTNESS-007: option 1 chosen by the user. Isolated working storage inside each prototype eval sandbox, with explicit expected artifact paths and no personal-storage access. All five decisions are settled; combined implementation is now authorized.

## Combined implementation result

All five option-1 decisions are implemented under bounded subject `remaining-flow-fixes-20260927`. Independent pre-edit review approved the combined contract as high risk. Three disjoint implementation areas cover explicit workflow worktree authority, output-eval environment isolation, and group/spike/approved-fix skill flows. Cross-review fixes addressed unreachable feature/isolated finish branches, isolated blocker bookkeeping, and missing selected-solution decision evidence.

Current checks: full skill benchmark (including updated recovery instructions), all agent shell integration checks and consolidated adapters passed. Learn workspace tests and formatting passed. Strict Clippy fails on three pre-existing warnings (unchanged execute_run argument count and two store.rs nested conditionals); baseline inspection confirmed they predate these changes. No paid evaluation sessions were run. Workflow formatting, strict Clippy and all 397 workspace tests pass (39 review-gate integration tests). Both affected binaries are rebuilt and installed from this checkout with the required locked/forced commands; PATH and new command help are verified. The installed group approval fixture passes. Independent entire-subject code and agent-document review is approved; the current completion gate passes with no blockers. Independent recovery review additionally required non-destructive abandonment, read-only stale/missing-worker inspection, and a combined final review for every archived binding. Renewed pre-edit approval and start checkpoint are recorded for this recovery contract.

Final cost review: agent instructions and supporting resources grew from 19,209 to 23,324 words (+4,115, including generated adapters, eval declarations and regression scripts). Most added cost is the explicit authorization/recovery contract and executable coverage. Independent review found no useful wording cut that preserved the required boundaries and terminal outcomes.

Final outcome: 15 fixed, 0 deferred, 0 reverted. The five selected fixes cover scoped worktree authorization and recovery, aggregate group gates, serial spikes, explicitly approved bounded fixes, and sandbox-local prototype evaluation. Both affected CLIs are installed. The complete skill benchmark passes against the installed workflow binary; agent integration and generated-adapter checks pass. No paid model evaluations ran.

Final gate subject: `remaining-flow-fixes-20260927`; change fingerprint `sha1-v1:172b475cbe24861e7c702f39711368541aa173d3`. Reviewer-authored pre-edit and entire-subject implementation records live in the configured private working store. `review check --checkpoint complete` returned `ready: true`, with no blockers. No covered files changed after final approval.

Verification limit: learn strict Clippy still fails on three confirmed pre-existing warnings (the unchanged `execute_run` argument count and two nested conditionals in `store.rs`). Learn tests and formatting pass; workflow tests, formatting and strict Clippy pass. These baseline warnings were reviewed and left outside the selected fixes.
