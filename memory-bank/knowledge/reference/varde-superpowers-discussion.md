---
type: reference
description: Decisions and remaining discussion topics from the Varde and Superpowers comparison.
status: draft
generated: { by: codex/gpt-6, at: 2026-09-26T20:00:58Z }
paths:
  - skills/varde-change/references/review-gates.md
  - agents/capabilities.json
  - clis/code/crates/varde-code/src/query/symbol_impact.rs
---

# Varde and Superpowers discussion

Last updated: 2026-09-27.

This is the ongoing discussion record. Read it before resuming this comparison.
Update it after each resolved topic: record the decision, reason, implementation
status, and next topic. Discuss one topic at a time. Ask numbered options with a
recommendation. Do not implement an open proposal until the user selects it.

The original numbered comparison was not preserved. The remaining topics below
are candidates grounded in the comparison evidence and current code, not a
recovered original list or verified Varde defects. Operational complexity is
excluded at the user's request.

## Decisions agreed and implemented

1. **Bounded changes can span multiple files.** Keep an in-memory plan when
   scope and verification are settled; do not add another workflow tier or
   force persisted planning merely because several files change.
2. **Every implementation change gets independent pre-edit plan review.**
   Review at least an in-memory plan for unstated assumptions, unresolved human
   decisions, verification, and structural risk. Investigate code/doc-answerable
   questions; persist and escalate blocking human choices. Stop before editing
   when independent review is unavailable. An approved plan covers its tasks
   until material scope, assumption, design, or verification drift.
3. **Behavior changes default to test-first.** The independent reviewer may
   approve a concrete alternative with a recorded reason and expected result.
   Documentation and packaging use appropriate structural or smoke checks.
4. **Implementation review follows structural risk.** Shared contracts, module
   boundaries, security-sensitive behavior, or broad downstream impact trigger
   independent review. Blast radius supports the decision; no numeric cutoff.
   For persisted plans, default to one aggregate review at finish. Verified
   tasks may become done with review pending; the plan cannot complete before
   required review passes. Previous per-task review made plan runs too slow.
5. **Review fixes get targeted verification.** Another independent
   implementation review is required if a fix changes behavior or introduces
   structural risk. Local corrections otherwise need targeted verification.
6. **Blast radius means downstream impact.** File impact excludes upstream
   dependencies and the seed. Symbol impact follows a unique declaration's
   resolved calls and inheritance, rather than its whole file. Ambiguity is
   explicit; coverage remains partial. Empty results do not prove isolation.
7. **Install affected local CLI binaries after completed CLI work.** The root
   AGENTS.md records build/install and PATH verification requirements.

The review policy is encoded in self-contained review-gates.md copies in
varde-change, varde-review, varde-agent-doc-authoring, varde-docs, and
varde-prototype. A vendored-copy check keeps them identical. Planner and executor
instructions were regenerated and installed for Codex, Claude, and OpenCode.
Updated skills were installed. The affected varde-code binary was rebuilt,
installed, and checked on full and incremental indexing. No commits were made
as part of this discussion.

## Remaining discussion agenda

| # | Topic | Question | Status |
|---|---|---|---|
| 1 | Mechanical enforcement | Which approved gates should the CLI enforce, and what evidence should it require before execution or completion? | Implemented, independently reviewed and installed |
| 2 | Context recovery | How reliably do interrupted or compacted runs recover decisions, approved assumptions, and pending reviews? | Existing mechanisms cover this; no new ledger recommended |
| 3 | Workflow outcome testing | How should realistic agent scenarios prove policy compliance beyond structural checks? | Runner and focused cases implemented; live runs pending |
| 4 | Debugging escalation | When repeated fixes fail, should Varde explicitly require reconsidering the design? | Implemented and locally verified |
| 5 | Activation consistency | How do we verify each harness actually loads and follows the installed workflow? | Native V2 adapters implemented; runtime discovery unverified |
| 6 | Transcript diagnosis | Can an existing real agent session be investigated for workflow failures and wasted work? | Completed, independently reviewed and installed |

Current state: the authorized topic-6 build is completed. The saved plan is authoritative for task, review and installation status. Mechanical enforcement is completed. Live Luna evaluations and OpenCode runtime discovery remain unverified. Do not assume Superpowers mechanically enforces every instruction; its inspected hooks also primarily inject guidance.

## Comparison evidence and limits

Superpowers comparison axes included approval latency, process escalation,
fresh-agent and review cost, activation, prompt versus mechanical enforcement,
behavior evaluations, persistent execution ledgers, and transcript diagnosis.
Our bounded-change and review decisions address the first three in part.
The initial capability assessment found an ordinary-session intake gap; topic 6
now implements the approved diagnosis route. Its policy and build state appear below.

Prior local adoption plans were already completed for parallel execution,
bootstrap, debugging/TDD entry points, finish flow, assumption checks, and visual
QA. Do not describe these as missing simply because they appeared in an older
comparison. Remaining topics require checking their current behavior.

Useful source paths:

- skills/varde-change/references/review-gates.md (current review contract).
- skills/varde-change/references/build-micro-change.md (bounded route).
- skills/varde-change/references/build-dispatch.md and build-plan-finish.md
  (approved verdict handoff and aggregate review).
- skills/varde-change/references/build-posture-debug.md (debugging behavior).
- skills/varde-learn/references/evals.md (existing outcome evaluation workflow).
- agents/capabilities.json (generated agent source).
- Superpowers repository: `skills/executing-plans/SKILL.md`
  (persistent ledger and recovery).
- Superpowers repository: `skills/subagent-driven-development/SKILL.md`
  (fresh context and review cadence).

## Topic 1: mechanical enforcement (policy agreed)

Current code: workflow transitions validate legal states and dependency blockers
(clis/workflow/varde-workflow/src/commands/transition.rs). Conclusion checks
acceptance-criteria checkboxes and declared knowledge outputs
(clis/workflow/varde-workflow/src/conclusion.rs). These paths do not yet enforce
the newly agreed independent-review evidence contract.

First proposed decision: enforce evidence at workflow start/completion
checkpoints, or intercept editing tools through harness-specific hooks.
Recommendation: workflow checkpoints, including lightweight local records for
bounded changes without requiring a persisted Markdown plan. Such checks can
reject missing/stale approval and completion evidence, but cannot prevent direct
filesystem edits or independently prove who performed a review.

Decision agreed: use workflow checkpoints that validate an approval record,
not merely a required `reviewed: true` field. The record identifies reviewed
plan/scope, verdict, unresolved questions, and freshness against the current
plan; required implementation review must cover final changes. This catches
missing or stale evidence but does not prove reviewer independence without
trustworthy harness provenance. No tool interception selected.

Decision agreed: the independent reviewer creates the approval record directly.
The coordinating agent consumes that record instead of transcribing its verdict.
Direct recording reduces transcription mistakes but is not authenticated proof
of independence. Approval freshness follows already agreed material changes to
scope, assumptions, design, or verification; routine Progress/status updates
must not cause repeated review.

Decision agreed: existing incomplete plans without an approval record require
independent review before further implementation. No grandfathering. Completed
plans need no retrospective approval.

Mechanical-enforcement policy choices are settled. CLI implementation remains
pending. Code-grounded draft plan 2026-09-26-mechanical-review-gates is in
the configured working store and passes structural validation. Independent
draft review identified a freshness tradeoff; the user chose automatic normalized
approval-relevant content fingerprints, accepting conservative invalidation for
wording edits. Formatting, Progress/status, and checkbox state do not invalidate
approval. The separate explicit contract-revision alternative was not selected.

Code investigation: CLI create/update/set-field can start or complete managed
core plans/tasks without workflow checks. Gate those state writes at the CLI
layer while preserving generic library/knowledge CRUD and custom artifacts;
classify old/new content to avoid type/status bypass. Transition protects only
its root revision; conclusion preparation and journal staging have separate
reads. Relevant approval/source revisions need commit and recovery preconditions.
The completed proposed design uses normalized contract fingerprints, immutable
scoped filesystem baselines (commits do not reset coverage), reviewer-written
versioned JSON evidence, shared checkpoint checks and journal prerequisites.
Cooperative locking and conflict detection preserve recovery without claiming
filesystem-wide atomicity. Task semantic containment remains an agent judgment.
Independent final review approved plan revision 95d0ab0d1e7eade0. Approval is
preserved alongside the plan; aggregate implementation review is required for
the shared workflow/transaction changes. The user confirmed finalization as written; validation passed with no diagnostics.
The user authorized build. The plan is active; serial implementation slices are
review evidence, checkpoint/recovery enforcement, then instruction routing.
The evidence CLI foundation is committed (64d6950). Full-suite verification exposed an existing temporary-file collision in md-core; its deterministic regression and repair are committed (2815a51), and the workflow workspace passes. Checkpoint/recovery enforcement is committed (b581ad4), and the full workspace passes with actual review records in redirected-storage fixtures. Three independently reproduced foundation defects are repaired in 8efabd6: inline-code whitespace normalization, escaping baseline/blob-root symlinks, and silently omitted explicit special-file scope. Their focused tests, strict Clippy and the workspace pass. Independent aggregate review identified bounded follow-ups for artifact_type aliases, overlapping journals, legacy conclusion recovery, transaction-created directories under root scope, fixture isolation, and heading/nested-checkbox normalization. These are approved and queued before routing. Aggregate implementation review, instruction routing, and installed-binary checks remain required before completion.

## Topic 2: context recovery (existing coverage)

The user pointed out that plan documents and handoffs already provide recovery.
Source inspection supports this:

- Plans/task Progress retain decisions, state, and verification evidence.
- build-dispatch.md Resume check compares completed tasks with commits and
  completion evidence, and surfaces interrupted/blocked tasks before resuming.
- reflect-handoff.md records done/remaining work, decisions, open questions,
  repository anchors, and links to plans/reviews/knowledge. Link content hashes
  detect subsequent edits, additions, removals, and renames.
- Handoff resume reads the record, checks its links, summarizes context and
  flags, and proposes next steps. Plan build already runs its own resume check.

Assessment: context recovery was overstated as a gap. Keep existing mechanisms;
no separate execution ledger or new resume-summary layer is justified by the
comparison alone. This is source-level coverage, not measured proof of every
compaction scenario. A missing update is a workflow-compliance problem to test,
not evidence that another storage mechanism is needed.

When topic 1 approval records are implemented, include them in existing recovery
paths, respecting approval freshness. Treat that as integration of the new gate,
not a separate recovery system. No context-recovery code change proposed.

## Topic 3: workflow outcome testing (implemented; live runs pending)

Decision: update stale policy expectations and add focused regression scenarios,
using the existing output evaluator. Do not build a broad cross-harness suite.
Use Codex `gpt-6-luna` through the official client and existing authentication;
do not silently fall back to another client or model.

Implemented:

- Output evaluations now default to Codex/Luna. `--harness claude` remains
  explicit. `--model` selects the evaluated model; `--judge-model` overrides
  the judge, which otherwise inherits that model.
- Codex JSONL is retained and normalized for existing verifiers. Tool lifecycle
  ordering and captured outputs remain available. Invalid, incomplete, failed,
  or nonzero-exit sessions cannot receive passing grades.
- Evaluation sessions use fresh sandboxes with ambient instructions and skills
  disabled. Codex judges run read-only. Authentication stays in the official
  client. Token counts are captured; unavailable monetary cost stays unknown.
- Existing cases now reflect independent pre-edit review, aggregate finish
  review, and behavior-changing fix re-review. New cases cover unavailable
  reviewers and unresolved human choices. Mechanical checks inspect actual
  source/state; trace-based assertions require captured independent-agent
  evidence, not coordinator claims. Missing evidence must not imply a pass.

Verification: the learn workspace suite, five mock Codex integration tests,
policy verifier fixtures, reference checks, and vendored-copy checks passed.
Independent final review passed after corrections. The rebuilt varde-learn was
installed, matched against the release artifact, and passed an installed mock
session. Updated varde-change, varde-review, and varde-learn skills were synced.

Verification limitation: initial adapter implementation preceded its tests.
Later regression tests demonstrated failures before their fixes. Independent
review accepted the final mock verification as an alternative; this is not a
claim that the initial implementation followed test-first development.

Live Luna account access and actual agent policy compliance remain untested.
No billed evaluation ran. Live runs require explicit approval of scope and cost
under varde-learn evaluation guidance. Mechanical review gates from topic 1
remain separate, pending implementation.

Source: clis/learn/crates/varde-learn-core/src/output/adapter.rs,
clis/learn/crates/varde-learn/tests/output_codex.rs, and
skills/varde-change/evals/evals.json.

## Topic 4: debugging escalation (implemented)

Source evidence:

- Varde already requires reproductions, ranked falsifiable hypotheses, experiments,
  and a regression check (build-posture-debug.md).
- Persisted task execution stops an approach after two failures, permits one
  evidence-informed re-dispatch, then leaves the task blocked. Unattended runs
  halt; interactive runs offer Retry/Continue/Abort (build-dispatch.md).
- Superpowers requires architectural discussion after three failed fixes
  (systematic-debugging/SKILL.md). Repeated failures are not proof that the
  architecture is wrong, so do not adopt that claim literally.

Decision agreed: retain the existing retry limit and require a short
evidence-based reassessment at exhaustion. Distinguish a wrong hypothesis,
inadequate reproduction, environment/test limitations, and evidence of a design
problem. State what must change before another attempt. Repeated failures alone
do not establish that the architecture is wrong.

Escalate to the human only for unresolved choices or scope changes requiring
their input. Apply existing independent pre-edit review when the plan materially
changes; do not add another routine review cycle.

Implemented in varde-change: persisted dispatch loads a shared reassessment
reference when its final re-dispatch fails. Standalone debug loads it when
progress is blocked or another fix would repeat a failed approach; no numerical
standalone budget was added. Reports go to chat and task-owner Progress;
parallel workers report to the orchestrator. Existing retry controls remain.

Independent pre-edit and final document reviews completed. The ownership
clarification received targeted verification. Reference/install checks,
vendored-copy checks, and existing policy evaluation fixtures passed. The
updated varde-change skill was installed and its changed files matched source.
This verifies instruction structure and existing fixtures; live agent behavior
was not evaluated. No CLI changes or binary rebuild were needed.

## Topic 5: activation consistency (native V2 update implemented)

Decision: audit current activation before adding a broad cross-harness suite.
This audit inspected source wiring, local installed artifacts, relevant config
keys, official discovery documentation, and existing tests. No live model
session was invoked; actual workflow compliance remains unmeasured.

| Surface | Evidence | Assessment |
|---|---|---|
| Skills installation | Eight canonical real directories under ~/.agents/skills, correctly linked into all three harness roots | Local files present; links resolve |
| Agent installation | Four generated profiles in each configured destination; generated-adapter/install tests pass | Source generation and copying agree; this does not prove runtime discovery |
| Codex | CLI 0.155.1; documented canonical skill and personal TOML agent roots match; current session exposes all eight skills and four custom roles | Current-session discovery evidence; live compliance untested |
| Claude | CLI 2.1.280; documented personal skill/agent roots match; variants preload backing skills through skills field | Wiring matches documentation; fresh-session discovery and behavior untested |
| OpenCode | CLI 2.0.12; installer uses ~/.config/opencode/agent; V2 documents ~/.config/opencode/agents and new permissions schema | Initially flagged documentation mismatch; exact release source also accepts both legacy forms (see correction below) |
| Startup guidance | All three local global instruction files route changes through varde-change; sync adds no Varde startup hook | Existing local routing guidance; no missing-hook defect established |
| Install freshness | Two shared references and review variants in all three harnesses differ from current source | Stale artifacts observed during audit, then refreshed; no automatic freshness report |
| Sync regression test | tests/varde-sync-test.sh exits 1: Cargo absent on intentionally restricted PATH while fixture invokes default CLI install | Test fixture drift repaired with --no-cli for wiring fixtures; separate CLI install checks pass |

Stale artifacts observed at audit time: varde-explore/references/varde-code.md,
varde-knowledge/references/reflect-handoff.md, and installed review agent variants.
All skills remain visible in this session; drift is not proof of discovery loss.

Isolated temporary-home sync with --no-cli passed: eight canonical skills,
eight links per harness, four agents per harness, no startup configuration
created. It validates Varde's intended destinations, not the clients' loaders.
OpenCode debug agents returned [] with the real local configuration. An isolated
comparison probe hung and was stopped before comparing plural vs singular paths;
therefore the empty result's cause is not experimentally established. No client
permissions or safety effects from legacy fields were proven at runtime.

Source anchors: varde skills_dir/detected_agents and installer loop,
agents/install.sh default targets, agents/templates/claude.md.tpl,
agents/review/opencode.md, tests/varde-sync-test.sh, and
agents/tests/generated-adapters.sh. Relevant official sources:

- [Codex skill discovery](https://learn.chatgpt.com/docs/build-skills)
- [Codex custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Claude skills](https://code.claude.com/docs/en/skills)
- [Claude subagents and preload](https://code.claude.com/docs/en/sub-agents)
- [OpenCode V2 agents](https://opencode.ai/v2/docs/agents)
- [OpenCode V2 skills](https://opencode.ai/v2/docs/skills)

Decision: implement the focused OpenCode V2 adapter update and refresh managed
installs. Generated adapters now use native ordered permissions; default install
uses plural agents/. Preserve existing IDs: plan/explore intentionally override
built-ins. Explicit rules preserve the profile capabilities, allow skill loading,
and deny child delegation. V2 combines write and edit: review permits edit to
write artifacts, while its source-write boundary remains prose. Broad shell
access is not a hard read-only sandbox. V1 adapters are no longer generated.

Migration removes only selected, marked regular legacy files after their matching
replacement installs successfully. Preserve unowned destinations and legacy
files, leaf/directory symlinks, and files whose replacement fails. Explicit -d
installs do not clean the global legacy directory. Dry runs preview these rules.

Correction to the initial audit: exact OpenCode v2.0.12 source accepts BOTH
singular agent/ and plural agents/ and migrates legacy fields. The earlier
format/directory mismatch did not establish discovery failure. This change
aligns with documented native V2 conventions; it is not proven to resolve the
empty client registry.

Exact release source: v2.0.12 commit
2670273ff17da96f85c5826ced57aa1b368754fa:

- [Discovery and decoding](https://github.com/anomalyco/opencode/blob/2670273ff17da96f85c5826ced57aa1b368754fa/packages/core/src/config/plugin/agent.ts)
  scans both directories, decodes native fields or migrates legacy fields, and
  registers profiles through opencode.config.agent.
- [Native schema](https://github.com/anomalyco/opencode/blob/2670273ff17da96f85c5826ced57aa1b368754fa/packages/schema/src/config/agent.ts)
  accepts ordered permission rules.
- [Frontmatter parser](https://github.com/anomalyco/opencode/blob/2670273ff17da96f85c5826ced57aa1b368754fa/packages/core/src/config/markdown.ts)
  uses gray-matter; JSON flow sequences are valid YAML for the permissions list.

Verification: permission and migration regressions failed before implementation,
then passed. Symlink-directory preservation also failed before its guard, then
passed. Consolidated adapter checks, role/model/write-boundary contracts, sync
wiring and CLI-install fixtures, and diff whitespace checks passed. Independent
pre-edit and final code/document reviews passed. All eight managed skills and
12 installed agent variants were refreshed and compared against source;
symlinks resolve to the canonical skills. No CLI module changed or needed a
binary rebuild. No commits or paid model calls were made.

Runtime limit: isolated official-client agent.list still returned an empty list,
including no built-ins. plugin.list was also empty. Exact-version parser source
supports the generated format, but installed discovery and effective permission
enforcement remain unverified. An initialization/registry limitation is a
possible explanation, not an established cause. Independent review approved
source-grounded verification as the alternative with this limitation disclosed.

A read-only installation health command, broad activation/live behavior tests,
and a startup bootstrap have not been approved. Do not infer model compliance
from file checks or describe this migration as fixing a demonstrated loader bug.

## Resume here

Topic 1 mechanical-enforcement policy and plan 2026-09-26-mechanical-review-gates are approved. Automatic fingerprint freshness is accepted. No scoped deferred findings need inclusion. The plan is completed. Mechanical review evidence, checkpoint enforcement, audit repairs, and skill/agent routing are committed and independently approved. Full workflow workspace and structural checks pass. The installed workflow binary matches this checkout and missing/valid/stale smoke checks return 4/0/4. Skills and agents are installed for Claude, Codex, and OpenCode. Unrelated local changes are preserved.
Topic 2 existing recovery is sufficient. Topic 3 Luna output support and focused
cases are implemented; live evaluations remain pending approval. Topic 4 retry
reassessment is implemented and locally verified. Topic 5 native V2 adapters,
managed migration, fixture repair, and local refresh are implemented. The audit's
legacy-format diagnosis was corrected against exact release source; empty
OpenCode runtime registries remain unexplained. No further topic-5 implementation
or paid run is approved. Mechanical review-gate implementation from topic 1 is complete. The subsequent topic-6 build authorization supersedes the earlier implementation hold. Paid evaluations remain outside that build; resume from the current topic-6 progress and saved plan.

## Mechanical review gate completion (2026-09-27)

Plan 2026-09-26-mechanical-review-gates is completed. Final routing commit: 61293a44c7ca143c1eccce0530319e2454a32f83. Independent reviewers wrote current implementation evidence directly for both the main plan and atomic repair. All twelve acceptance criteria pass, including the full workflow workspace, 65 routing assertions, agent contracts, installed binary hash comparison and installed missing/valid/stale smoke. Supported CLI checkpoints enforce current evidence; direct filesystem editing and authenticated reviewer identity remain outside that guarantee. Remaining comparison decisions and evaluation authorization stay in this discussion record.

## Topic 6: transcript diagnosis (approved build in progress)

The assessment and policy decisions below predate the build. Current progress is
recorded at the end of this topic and in its saved plan.

The user selected assessment of existing capabilities before proposing additions.

Varde already retains raw evaluation events, stderr, normalized transcripts, timing and available usage (clis/learn/crates/varde-learn-core/src/output/run.rs:143). Its evaluator grades declared assertions using final text, sandbox files and ordered tool events (output/grade.rs:285). Friction workflows capture observed obstacles, reconcile evidence, distill recurring issues and check recurrence (skills/varde-learn/SKILL.md:13). Product debugging has reproduction/hypothesis/experiment requirements (skills/varde-change/references/build-posture-debug.md:17). These are useful components, but the inspected public CLI and skill routes expose no intake/report workflow for an existing ordinary agent session. This is a routing capability gap, not evidence that current grading or debugging is broken.

Superpowers has skills/diagnosing-superpowers/SKILL.md:3 for current or past sessions. It verifies transcript identity and children, runs seven analyst dimensions, and produces path:line observations with confidence and coverage limits. All seven analysts always run (:74). This is prompt-driven, read-only investigation, not an automatic parser or repair engine; its report explicitly excludes fix advice (:96).

Recommendation for discussion: consider a bounded, on-demand, read-only session-diagnosis route under existing varde-learn, focused on the stated complaint and supported trace evidence. Retain the distinction between observations, hypotheses and missing evidence. Existing evaluation artifacts and searchable tool captures may help, but native real-session formats require investigation; the evaluation Codex normalizer requires a single successful terminal turn and must not be assumed suitable for failed or multi-turn session history unchanged (output/adapter.rs:111).

Decision agreed: add an on-demand, read-only existing-session diagnosis route under varde-learn, focused on the stated complaint and supported trace evidence. Report observations, uncertainty and evidence limits; analyze relevant dimensions without always dispatching seven analysts. This selects the direction, not implementation authorization.

Decision agreed: diagnosis reports include evidence, ranked causal hypotheses and bounded recommendations. Observations, hypotheses and proposals remain distinct; recommendations do not authorize applying changes.

Decision agreed: retain the full diagnosis report in local working storage, and link confirmed observed obstacles to the existing friction lifecycle with concise evidence and report anchors. Search for matching items; do not count an already-recorded incident again. Unverified hypotheses remain in the report. Preserve the original session timestamp and repository context: current friction add captures the diagnosing process context and current time, so historical, idempotent ingestion must be investigated rather than assumed supported (clis/learn/crates/varde-learn-core/src/store.rs:805). Recurrence/adoption handling must not treat a newly diagnosed old incident as a fresh recurrence.

Decision agreed: a requested diagnosis automatically captures evidence-backed, distinct observed friction events whose original session context can be established. Leave speculative causes, uncertain duplicates and unverifiable historical events in the report. Capture does not authorize source changes or item status promotion. This is the selected future behavior; no actual diagnosis or friction capture is being run during design discussion.

Decision agreed: accept the current session, a named session ID, or an explicit transcript path. Locate and verify the actual session transcript and relevant child sessions; ask when identification is ambiguous or unavailable rather than guessing. Harness-specific discovery feasibility must be investigated before implementation, and missing history or unsupported formats must be disclosed.

Decision agreed: when no specific complaint is supplied, run bounded general triage for failed tools, repeated work, workflow deviations and available time/token signals. Focus deeper analysis on observed evidence; do not require seven analyst passes or infer absent measurements.

Policy choices are settled. Next step: offer a code-grounded implementation plan that investigates verified native session discovery, incomplete/failed traces, report evidence links and historical idempotent friction ingestion before implementation. Preserve existing evaluation and friction compatibility. No source implementation, paid evaluation, automatic skill repair, issue submission, session export or actual diagnosis is authorized during this design discussion.

Decision agreed: prepare the code-grounded implementation plan before building. The plan is stored locally at `<working>/plans/2026-09-27-session-diagnosis/plan.md`. Implementation and paid evaluations require a subsequent explicit instruction.

Decision agreed: diagnosis of the current session requires an independent analyst subagent, including an explicit ID or path resolving to that same session. The coordinator supplies verified bounded evidence and handles report persistence and eligible friction capture; past-session analysis may use the invoking agent. If independent delegation is unavailable, disclose the blocker rather than substituting self-analysis.

Decision agreed: finalize plan 2026-09-27-session-diagnosis as written, including independent current-session analysis. Independent pre-edit review approved the current contract and validation passed; the plan remains backlog, ready for an explicit build instruction.

Build authorized: plan 2026-09-27-session-diagnosis is active. Codex intake is implemented in 2e56d5edf3ddf35980a95848617a51172def9597 with frozen bounded evidence, verified cutoffs and historical anchor revalidation. Its scoped tests and independent synthetic smoke pass; Claude intake is in progress. Historical capture, remaining adapters, workflow guidance, installation and aggregate review are pending. The plan records three independently approved pre-existing Clippy style exceptions. Paid evaluations and actual user-session diagnosis remain outside this build.

Build progress: native intake tasks are complete (Codex 2e56d5e, Claude af92a55, OpenCode ddb4ab0). Latest diagnosis integration tests pass 22/22 and core tests 12/12; independent synthetic Codex/Claude/WAL-only OpenCode smokes preserve source files and leave the friction store unopened. Historical provenance/storage is in progress; capture CLI, workflow guidance, full verification, aggregate review and installation remain pending. Saved plan/task evidence is authoritative for resuming.

Build progress (capture verification at 79c27d1): native Codex/Claude/OpenCode intake, schema-3 historical storage, capture CLI and workflow guidance are implemented. Capture repair commit 79c27d1ffa5989b0089d4c7ec5dc4d1bdfffcddb passed 37 diagnosis, 23 friction-store, 7 help and 22 core tests; 123 guidance assertions, references, formatting and approved supplemental Clippy also passed. Strict Clippy retains only the three independently approved baseline warnings. The original fourteen review findings are independently verified fixed.

Two additional bounded findings remain: CORRECTNESS-010 enforces the existing normalized-record budget during collection rather than after inherited metadata has been copied into the full vector; CORRECTNESS-011 accepts a legitimate child selected as the investigation root while retaining raw ancestry and inherited-history checks. Both are independently pre-edit approved in the active diagnosis-repair-normalized-budget task, with no open human choices. Full final workspace verification, aggregate implementation approval and installation remain pending. Paid/live evaluations and actual user-session diagnosis have not been run. Resume from plan 2026-09-27-session-diagnosis rather than treating this progress snapshot as completion evidence.

Build progress (final source at 6cc5694): all ten tasks are done. The incremental normalized-record budget and selected-child capture boundary repairs are implemented. Final offline workspace verification passed 137 tests; strict Clippy reports only the three approved existing warnings, and supplemental Clippy passes. The updated CLI and seven shipped skill files are installed and verified against repository output across Codex, Claude and OpenCode. Installed synthetic checks preserve native sources, retain original context on idempotent no-ID capture, and preserve legacy records during schema-2 migration. Independent final implementation approval and plan conclusion remain pending; the saved plan is authoritative. Paid/live evaluations and actual user-session diagnosis remain unrun.

Build completed: independent whole-subject implementation review approved all 25 changed manifest entries and verified all sixteen findings Fixed. The complete review gate passed with no blockers, and plan 2026-09-27-session-diagnosis concluded successfully. The repository remains on main with local commits; nothing was pushed. Follow-up discussion can resume from the topic table. Live Luna evaluations and OpenCode runtime discovery remain unverified and require their own authorized work.

Follow-up decision: connect session diagnosis and Toz through skills. Diagnosis
uses verified bounded capture links to investigate output inefficiency, records
eligible historical friction, and recommends Toz improvements. Current-session
analysis remains independent. Authorized profile work routes to varde-manage
with representative evidence and explicit measurements or unknowns; core Toz
changes route to varde-change. Recommendations do not authorize filter edits,
and missing captures do not establish savings. The skill update passes 123
diagnosis assertions, isolated reference checks and Toz frontmatter validation.
Review evidence is stored under subject session-toz-skill-connection in the
configured working store.
