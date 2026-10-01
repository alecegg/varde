# Instruction value audit, part A: varde-change + shared references

Scope: `skills/varde-change/{SKILL.md,references/*,assets/*}` and `skills/shared/references/*` (audited once). FLOW.md and evals excluded. Audited words: 13,921 (SKILL 453, references 10,239, assets 489, shared 2,740).
Criteria: `varde-agent-doc-authoring/references/criteria.md`. Rubric 0-5 as specified. Line numbers are the first line of the unit.

## 1. Instruction units

| Score | Verdict | Location | Instruction | Why |
|---|---|---|---|---|
| 0 | cut | `skills/varde-change/references/build-execution.md:44` | "`plan-execution` \| Run this cycle as written." | Default; no behavior. |
| 0 | merge→build-execution.md:83 | `skills/varde-change/references/build-parallel.md:8` | Executors follow shared-checkout rules in build-execution | Orchestrator does not need executor rules restated. |
| 1 | cut | `skills/shared/references/review-gate-plan.md:3` | "Load before initializing a persisted plan or updating a contract/scope." | Caller (review-gates §2) already states load condition. |
| 1 | cut | `skills/shared/references/review-gate-plan.md:21` | "The subject reads the live plan, so an unchanged approved plan covers its declared tasks." | Rationale. |
| 1 | cut | `skills/shared/references/review-gate-record.md:3` | "Load as the independent reviewer... holds every gate step a reviewer takes" | Callers state load condition. |
| 1 | cut | `skills/shared/references/review-gate-record.md:29` | "The CLI rejects unknown fields, approval with unresolved choices, non-low risk without final review" | Describes CLI enforcement; CLI error teaches it. |
| 1 | merge→review-gates.md:118 | `skills/shared/references/review-gate-record.md:42` | "Implementation review runs at completion regardless of this field or tier." | Stated in review-gates §5 and review-gate-worktree. |
| 1 | cut | `skills/shared/references/review-gate-record.md:46` | "it binds evidence to observed files, not correctness" | Rationale. |
| 1 | cut | `skills/shared/references/varde-code-cli.md:55` | Planning section: nav_map then context_pack; signals not replacement | Restates catalog descriptions. |
| 1 | cut | `skills/shared/references/varde-code-cli.md:63` | Documentation section | Not used by varde-change; restates catalog. |
| 1 | cut | `skills/shared/references/varde-code-cli.md:69` | Exploration section | Not used by varde-change; restates catalog. |
| 1 | cut | `skills/shared/references/varde-code-cli.md:75` | Build section: survey modifies, get_symbol, tests_for_file, detect_changes | Restates catalog. |
| 1 | cut | `skills/shared/references/varde-workflow-cli.md:60` | inspect returns version/fingerprints/baseline | Describes CLI output. |
| 1 | cut | `skills/shared/references/varde-workflow-cli.md:62` | record needs inspected version and reviewer evidence | Restates review-gate-record. |
| 1 | cut | `skills/shared/references/varde-workflow-cli.md:68` | readiness planning_ready vs implementation_ready | Third copy (review-gate-plan:30, build.md:89). |
| 1 | cut | `skills/shared/references/varde-workflow-cli.md:70` | Outside approval checkout, follow worktree procedure | Routing exists in review-gates §2. |
| 1 | cut | `skills/shared/references/varde-workflow-cli.md:76` | Concept search: bundle/slug definition and commands | Irrelevant to varde-change; belongs to varde-knowledge only. |
| 1 | cut | `skills/shared/references/varde-workflow-cli.md:89` | Concept maps: read index.md, regenerate | Irrelevant to varde-change. |
| 1 | cut | `skills/varde-change/assets/PLAN-TEMPLATE.md:77` | "No `## Tasks`: build writes task files; evidence lives in task Progress." | Omission is self-evident from skeleton. |
| 1 | merge→plan-decomposition.md:48 | `skills/varde-change/assets/TASK-TEMPLATE.md:12` | YAML comments restating ownership rules | Duplicate of plan-decomposition §3; one place suffices. |
| 1 | cut | `skills/varde-change/references/build-execution.md:3` | "Every executor reads this before its first tool call; it is the cycle..." | Routing already sends executors here; self-description changes nothing. |
| 1 | cut | `skills/varde-change/references/build-execution.md:9` | "The parent passes the plan subject id and resolved memory paths." | Descriptive; the brief itself shows what was passed. |
| 1 | merge→review-gates.md | `skills/varde-change/references/build-finish.md:35` | Tell reviewer to use paths without re-resolving | Repeated in 5+ places; one shared subagent-brief rule suffices. |
| 1 | cut | `skills/varde-change/references/build-finish.md:81` | "The copies are visible follow-up work and do not block completion" | Rationale; exit-code rule already says what blocks. |
| 1 | shorten | `skills/varde-change/references/build-finish.md:130` | "Keep as is: leave the checkout, branch, and worktree in place." | Option label self-explains; keep label only. |
| 1 | merge→SKILL.md:28 | `skills/varde-change/references/build-micro-change.md:3` | Task under persisted plan uses build-execution; dependent outcomes go to build.md | Duplicates SKILL.md routing table. |
| 1 | cut | `skills/varde-change/references/build-micro-change.md:35` | "Edit only the approved scope and run its checks." | Default; restates gate. |
| 1 | cut | `skills/varde-change/references/build-micro-change.md:49` | "Final review and the complete checkpoint cover source and review edits." | Implied by scoping the artifact. |
| 1 | cut | `skills/varde-change/references/build-micro-change.md:50` | "Plan-owned findings use their task flow." | Implied by routing. |
| 1 | cut | `skills/varde-change/references/build-parallel.md:3` | "follow the section for its wave_mode" | Section headings make this obvious. |
| 1 | cut | `skills/varde-change/references/build-posture-debug.md:55` | Prefer failing test, diffed CLI run, harness, fuzz, manual repro | Generic debugging craft a frontier model knows. |
| 1 | cut | `skills/varde-change/references/build-posture-debug.md:57` | Pin time, seed RNG, isolate filesystem, freeze network | Generic determinism advice. |
| 1 | cut | `skills/varde-change/references/build-posture-debug.md:58` | For non-deterministic bug, raise the reproduction rate | Generic; no failure evidence. |
| 1 | merge→build-posture-debug.md:60 | `skills/varde-change/references/build-posture-debug.md:72` | Without loop, state how trace supports symptom and limits | Third statement of unreproduced rule. |
| 1 | cut | `skills/varde-change/references/build-posture-debug.md:80` | Add ranked alternatives when evidence doesn't isolate cause | Restates the hypotheses field definition (L24). |
| 1 | cut | `skills/varde-change/references/build-posture-debug.md:86` | Each probe tests one prediction, one variable at a time | Generic method. |
| 1 | cut | `skills/varde-change/references/build-posture-debug.md:88` | Performance regression: baseline before bisecting | Generic; no evidence of failure. |
| 1 | cut | `skills/varde-change/references/build-retry-reassessment.md:3` | "Load only at the stopping point specified by dispatch or debug posture." | Callers already state when to load. |
| 1 | cut | `skills/varde-change/references/build-retry-reassessment.md:21` | Keep the caller's retry budget and blocked-task controls | Default; nothing here overrides them. |
| 1 | cut | `skills/varde-change/references/build-worktree.md:3` | "Mechanics for editing in a separate git worktree... caller decides whether; read-only never does" | File purpose statement; callers already gate loading. |
| 1 | cut | `skills/varde-change/references/build-worktree.md:15` | Keep as is / Push: follow Release | Repeated at L85 and L126. |
| 1 | cut | `skills/varde-change/references/build-worktree.md:126` | "Keep as is or Push and open PR: follow Release." | Third repetition. |
| 1 | cut | `skills/varde-change/references/build.md:3` | "This route runs one plan in dependency order... orchestrator owns the wave loop" | Purpose statement; SKILL.md routing covers. |
| 1 | cut | `skills/varde-change/references/build.md:30` | "When interactive, ask per SKILL.md `## Asking questions`." | SKILL.md already loaded; restatement. |
| 1 | cut | `skills/varde-change/references/build.md:58` | "Execution loads the matching posture file automatically" | Explains executor behavior orchestrator doesn't act on. |
| 1 | cut | `skills/varde-change/references/orchestrate.md:3` | "Children are nested plan.md; id <group-id>/<child-slug>" | Dup of plan.md split section. |
| 1 | merge→review-gates.md | `skills/varde-change/references/orchestrate.md:41` | Pass explicit paths and resolved <working>/<knowledge> without re-resolving | Repeated brief rule. |
| 1 | cut | `skills/varde-change/references/plan-decomposition.md:11` | "Check these even for a planned change, since ad-hoc work skipped planning" | Rationale. |
| 1 | cut | `skills/varde-change/references/plan.md:3` | "Planning grows one plan.md defining scope, design, and acceptance criteria." | Purpose statement; template shows it. |
| 1 | cut | `skills/varde-change/references/plan.md:14` | "Resume. Continue per Later turns." | Obvious flow. |
| 1 | cut | `skills/varde-change/references/plan.md:20` | "Use this file for planning." | No behavior. |
| 1 | cut | `skills/varde-change/references/plan.md:44` | Later turns: follow growth loop until exit then Finalize | Restates section structure. |
| 1 | cut | `skills/varde-change/references/plan.md:51` | "The first turn seeds plan.md; run this loop every later turn to sharpen it." | Restates L44. |
| 1 | merge→plan.md:133 | `skills/varde-change/references/plan.md:55` | Run External interface check when consumers touched | Section itself states its trigger. |
| 1 | merge→review-gates.md | `skills/varde-change/references/plan.md:118` | Research subagents get resolved paths, no re-resolving | Repeated brief rule. |
| 1 | cut | `skills/varde-change/references/plan.md:143` | "Internal-only changes skip this." | Implied by the "if consumers" condition. |
| 1 | cut | `skills/varde-change/references/plan.md:228` | "Boundaries come from the full spec, not a pre-spec guess." | Rationale. |
| 1 | cut | `skills/varde-change/references/verify.md:15` | "Incomplete plans still receive partial verification." | Default behavior. |
| 2 | merge→review-gates.md:81 | `skills/shared/references/review-gate-plan.md:15` | Pass reviewer subject id, repository, memory paths | Subset of review-gates §3 list. |
| 2 | merge→build-execution.md:25 | `skills/shared/references/review-gate-plan.md:38` | Tasks may be done while aggregate review pending | Duplicate of build-execution:25. |
| 2 | merge→build-finish.md:9 | `skills/shared/references/review-gate-plan.md:40` | Finish source/docs/spec/changelog/verification before final review | Duplicate of build-finish §1 and review-gates §5.1. |
| 2 | merge→review-gates.md:114 | `skills/shared/references/review-gate-plan.md:52` | Material changes need fresh independent verdict | Stated in review-gates §4 and micro-change. |
| 2 | keep | `skills/shared/references/review-gate-record.md:10` | Resolve code-answerable questions yourself | Default-ish. |
| 2 | shorten | `skills/shared/references/review-gate-record.md:18` | record_template pre-fills listed fields | Describes CLI output internals; "fill remaining placeholders" suffices. |
| 2 | merge→build-worktree.md:93 | `skills/shared/references/review-gate-worktree.md:24` | Abandonment: abandon-worktree; keeps source; can't resume or conclude | Duplicate of build-worktree Abandon. |
| 2 | keep | `skills/shared/references/review-gates.md:34` | Exception: inspect diff, run targeted checks, report why | Default. |
| 2 | keep | `skills/shared/references/review-gates.md:38` | Existing subjects keep checkpoints; growth takes full gate | Guard; dup micro-change:14. |
| 2 | shorten | `skills/shared/references/review-gates.md:71` | Missing tier evidence, open_choices, shared contracts default to high | CLI behavior description; partly useful. |
| 2 | keep | `skills/shared/references/review-gates.md:95` | A finding is not approval of its fix | Short guard. |
| 2 | shorten | `skills/shared/references/varde-code-cli.md:27` | Command catalog (14 entries) | --help lists commands; keep names + key caveats only. |
| 2 | keep | `skills/shared/references/varde-code-cli.md:82` | Review: batch tests_for_file+dependents example | Concrete batch syntax is useful; not varde-change's. |
| 2 | keep | `skills/shared/references/varde-code-cli.md:92` | Simplify: include untracked files via git ls-files | detect_changes omits untracked; real trap. |
| 2 | keep | `skills/shared/references/varde-code-cli.md:105` | Grep-check implausible results like zero dependents | Cheap guard. |
| 2 | shorten | `skills/shared/references/varde-workflow-cli.md:4` | CLI purpose; Write/Edit for artifacts; review commands require CLI | Last clause is the value; duplicated at L96. |
| 2 | shorten | `skills/shared/references/varde-workflow-cli.md:28` | readiness reports actions/blockers | Describes output. |
| 2 | keep | `skills/shared/references/varde-workflow-cli.md:31` | workflow_blocked lists legal states, changes nothing | Recovery hint. |
| 2 | merge→build-finish.md:86 | `skills/shared/references/varde-workflow-cli.md:34` | Run conclude after criteria/specs pass; conclusion-* follow-ups | Owned by build-finish §6. |
| 2 | merge→review-gates.md:63 | `skills/shared/references/varde-workflow-cli.md:39` | Review init commands (without --tier-evidence) | Duplicates review-gates with a stale flag set. |
| 2 | merge→review-gate-record.md:9 | `skills/shared/references/varde-workflow-cli.md:48` | init returns subject_id/version; reviewer inspects and records | Owned by review-gate-record. |
| 2 | merge→review-gates.md:103 | `skills/shared/references/varde-workflow-cli.md:52` | inspect/record/check/contract/expand command block | Each command already given where used. |
| 2 | merge→review-gate-plan.md:49 | `skills/shared/references/varde-workflow-cli.md:64` | contract/expand may invalidate approval | Stated with more precision in review-gate-plan. |
| 2 | merge→varde-code-cli.md:5 | `skills/shared/references/varde-workflow-cli.md:109` | Never build or install the binary | Same rule in varde-code-cli; fine but duplicate. |
| 2 | merge→user CLAUDE.md | `skills/varde-change/SKILL.md:39` | One topic per turn; up to three facets; wait | Same rule in user's global CLAUDE.md; needed only for other users. |
| 2 | merge→user CLAUDE.md | `skills/varde-change/SKILL.md:43` | Recommend one option with one-sentence reason | Same as global CLAUDE.md. |
| 2 | shorten | `skills/varde-change/SKILL.md:48` | Numbered-menu question template | Format preference; overlaps CLAUDE.md numbered options. |
| 2 | keep | `skills/varde-change/assets/TASK-TEMPLATE.md:40` | Progress comment: owner only; end with `- evidence:` | Format hint. |
| 2 | shorten | `skills/varde-change/references/build-execution.md:25` | Task may be done while aggregate review pending; not plan completion | Guards premature "plan done" claims; one clause suffices. |
| 2 | shorten | `skills/varde-change/references/build-execution.md:52` | Benign drift: note and proceed; invalidating drift: blocker | Reasonable default; examples in parentheses cuttable. |
| 2 | keep | `skills/varde-change/references/build-execution.md:57` | Use pre-edit-approved verification approach; record alternatives | Helpful; deviation is visible at review. |
| 2 | shorten | `skills/varde-change/references/build-execution.md:62` | Profile table tdd/regression/characterization/smoke/not-applicable | Names are template vocabulary; methods are model defaults. |
| 2 | keep | `skills/varde-change/references/build-execution.md:70` | Map each check to coverage; uncoverable check means mis-scoped, block | Cheap default; block rule is the useful half. |
| 2 | keep | `skills/varde-change/references/build-execution.md:76` | Outside refactor posture, leave refactoring to finish simplify pass | Limits scope creep; cheap if violated. |
| 2 | shorten | `skills/varde-change/references/build-execution.md:81` | Check shared surface dependents first (varde-code or grep) | Default-ish; also owned by plan.md External interface check. |
| 2 | merge→build-execution.md:104 | `skills/varde-change/references/build-execution.md:108` | "In a parallel wave, do not edit the task file" | Third statement of the same rule (L104, build-parallel:40). |
| 2 | keep | `skills/varde-change/references/build-execution.md:110` | Run configured lint; findings are candidates, not a gate | Default; "candidates" guard is mildly useful. |
| 2 | shorten | `skills/varde-change/references/build-execution.md:124` | "Undo a completed implementation task with `git revert`." | Rarely needed at completion; move to a gotcha or cut. |
| 2 | keep | `skills/varde-change/references/build-finish.md:12` | Update a module changelog when it exists | Cheap default; often forgotten. |
| 2 | keep | `skills/varde-change/references/build-finish.md:42` | Commit report folder when plan storage tracked | Minor bookkeeping. |
| 2 | shorten | `skills/varde-change/references/build-finish.md:46` | Agent-document findings: bounded change, record in Progress, no review folder | Edge route; could point to review-gates. |
| 2 | shorten | `skills/varde-change/references/build-finish.md:60` | Fix: bounded build task with finding_ids, solution, decision evidence | Restates varde-review fix Parent workflow it cites. |
| 2 | keep | `skills/varde-change/references/build-finish.md:63` | Dismissal: parent records reason | Default. |
| 2 | merge→review-gates.md | `skills/varde-change/references/build-finish.md:67` | Fix plans pass pre-edit gate; changed covered files need fresh full-subject record | Gate rule owned by review-gates. |
| 2 | shorten | `skills/varde-change/references/build-finish.md:72` | Rerun only AC checks covering fix-changed files; unconfirmed blocks | Optimization detail; "rerun affected AC checks" suffices. |
| 2 | keep | `skills/varde-change/references/build-finish.md:99` | Record obstacles via varde-learn, decisions via varde-knowledge, only when present | Useful routing; cheap to miss. |
| 2 | keep | `skills/varde-change/references/build-parallel.md:50` | Collect every result before integrating | Mostly default. |
| 2 | shorten | `skills/varde-change/references/build-posture-debug.md:21` | Field definitions: reproduction, hypotheses, experiments, cause, verification | Field names suffice; definitions are mostly self-evident. |
| 2 | shorten | `skills/varde-change/references/build-posture-debug.md:34` | diagnose may leave cause uncertain; state evidence limit | Overlaps L39 unreproduced labeling. |
| 2 | merge→build-posture-debug.md:60 | `skills/varde-change/references/build-posture-debug.md:39` | Label unreproduced symptoms **unreproduced**, state limits | Stated again in Phase 1 and Phase 2 step 3. |
| 2 | shorten | `skills/varde-change/references/build-posture-debug.md:70` | Minimize to smallest red scenario, rerun after each cut | Good craft; one clause. |
| 2 | shorten | `skills/varde-change/references/build-posture-debug.md:77` | State falsifiable hypothesis before testing, with template sentence | Useful; template sentence cuttable. |
| 2 | keep | `skills/varde-change/references/build-posture-debug.md:82` | "An untested hypothesis is not evidence for a fix." | Short guard; overlaps L32 but cheap. |
| 2 | keep | `skills/varde-change/references/build-posture-debug.md:96` | Watch it fail, fix, watch it pass; rerun Phase 1 loop | TDD default; short. |
| 2 | keep | `skills/varde-change/references/build-posture-debug.md:111` | Commit message states the proven hypothesis | Mild preference. |
| 2 | keep | `skills/varde-change/references/build-posture-refactor.md:7` | Reuse an unchanged approved plan verdict supplied by caller | Prevents redundant review; cheap. |
| 2 | keep | `skills/varde-change/references/build-posture-refactor.md:8` | Bounded refactor without task: use contract scope and stable change ID | Mapping rule for taskless route. |
| 2 | keep | `skills/varde-change/references/build-posture-refactor.md:13` | Find varde-knowledge pattern notes for target paths | Useful default. |
| 2 | shorten | `skills/varde-change/references/build-posture-refactor.md:15` | Target selection order: explicit, review findings, structural goal, else ask | Order mostly default; "else ask" is the value. |
| 2 | keep | `skills/varde-change/references/build-posture-refactor.md:42` | Run suite first; record pre-existing failures | Default-ish baseline. |
| 2 | keep | `skills/varde-change/references/build-posture-refactor.md:54` | Count real callers before inlining | Useful craft; cheap failure. |
| 2 | keep | `skills/varde-change/references/build-posture-refactor.md:56` | Rename only when the rename is the change | Scope discipline; cheap failure. |
| 2 | shorten | `skills/varde-change/references/build-posture-refactor.md:64` | Verify with approved checks; full suite only for new failures/concerns | Long; condense to one rule. |
| 2 | keep | `skills/varde-change/references/build-posture-refactor.md:92` | End with `File \| Change \| Verification` table | Output format; low stakes. |
| 2 | keep | `skills/varde-change/references/build-retry-reassessment.md:8` | Summarize failed attempts and results | Structure of the reassessment. |
| 2 | keep | `skills/varde-change/references/build-retry-reassessment.md:22` | Escalate to human only for unresolved choices or scope changes | Limits needless interruptions. |
| 2 | shorten | `skills/varde-change/references/build-retry-reassessment.md:24` | Revised plan returns to pre-edit gate; no routine review cycle | Gate rule owned by review-gates. |
| 2 | shorten | `skills/varde-change/references/build-worktree.md:70` | Binding authorizes only start/resume; renewed approval never revives stale worker | CLI enforces this; prose is explanation. |
| 2 | keep | `skills/varde-change/references/build-worktree.md:100` | Handle retained source via separately approved change | Gate reminder. |
| 2 | keep | `skills/varde-change/references/build.md:31` | Read varde-code-cli only for discovery questions | Conditional load; saves tokens. |
| 2 | shorten | `skills/varde-change/references/build.md:35` | Default to current checkout; stage only task-owned paths | Default; staging half dup of build-execution. |
| 2 | keep | `skills/varde-change/references/build.md:66` | Read each task file; id is the filename | Minor convention. |
| 2 | merge→build.md:72 | `skills/varde-change/references/build.md:126` | Repeat until done/blocked/empty; remaining todo as blocked_by_dep | Duplicates step 5.4 wording. |
| 2 | keep | `skills/varde-change/references/build.md:137` | Announce each wave's strategy and task ids | User visibility; cheap. |
| 2 | keep | `skills/varde-change/references/build.md:212` | Typed review blocker holds implementation; not a dependency result | Clarifies reporting category. |
| 2 | keep | `skills/varde-change/references/orchestrate.md:75` | Commit activation when tracked | Bookkeeping. |
| 2 | merge→build.md:224 | `skills/varde-change/references/orchestrate.md:98` | Stop when statuses and commits disagree | Same rule as build Resume check. |
| 2 | keep | `skills/varde-change/references/plan-decomposition.md:20` | research kind only for lasting external output; doc task only when asked | Prevents task bloat. |
| 2 | keep | `skills/varde-change/references/plan-decomposition.md:70` | Schema change names schema file found by reading | Guards analogy guessing. |
| 2 | keep | `skills/varde-change/references/plan.md:20` | Include context_pack with feature terms; scan reviews/deferred in same call | Batching hint plus deferred scan. |
| 2 | keep | `skills/varde-change/references/plan.md:46` | If tracked isolation created, offer merge/cleanup after finalizing | Rare but otherwise forgotten. |
| 2 | keep | `skills/varde-change/references/plan.md:52` | Research what the repo can answer each turn | Mild; dup of Routing unknowns first bullet. |
| 2 | keep | `skills/varde-change/references/plan.md:53` | Load varde-code-cli only when on PATH and scope unknown | Conditional load saves tokens. |
| 2 | keep | `skills/varde-change/references/plan.md:61` | Code can answer → research, don't list | Default-ish; short. |
| 2 | shorten | `skills/varde-change/references/plan.md:83` | Design It Twice: constraints, two alternatives, recommend, log loser | Useful technique; could be one line. |
| 2 | keep | `skills/varde-change/references/plan.md:112` | Ask highest-value OQ; solution-shape before spelling | Ordering hint; cheap. |
| 2 | keep | `skills/varde-change/references/plan.md:163` | Criteria are plan-level, true after ship | Clarifies scope. |
| 2 | shorten | `skills/varde-change/references/plan.md:214` | Plan id change: rename, validate, rerun review, replace subject id | Rare edge case; long. |
| 2 | keep | `skills/varde-change/references/plan.md:223` | Announce `Plan <id> is ready; ask to build it.` | Fixed phrase; low stakes. |
| 2 | keep | `skills/varde-change/references/plan.md:230` | clusters on affected files as starting point | Optional heuristic. |
| 2 | shorten | `skills/varde-change/references/status.md:10` | Handoffs table: open, newest 5, columns, empty message | Format detail; model would do similar. |
| 2 | keep | `skills/varde-change/references/status.md:16` | Mode mapping plan/build/orchestrate/verify | Short routing hints. |
| 2 | keep | `skills/varde-change/references/verify.md:13` | Ambiguous slug: list and ask once; state resolved id/status | Default. |
| 2 | keep | `skills/varde-change/references/verify.md:23` | Read task status/Progress; don't re-grade task Verification | Scope limit. |
| 2 | keep | `skills/varde-change/references/verify.md:30` | retrieve: read only named files; record supporting line | Scope limit. |
| 2 | keep | `skills/varde-change/references/verify.md:37` | Report each criterion with evidence; counts and status | Output format. |
| 2 | keep | `skills/varde-change/references/verify.md:45` | Recommend `varde-change build` when fixes needed | Handoff hint. |
| 3 | keep | `skills/shared/references/review-gate-plan.md:27` | Start/resume check before dispatch; planning_ready vs implementation_ready | Distinguishes readiness fields. |
| 3 | keep | `skills/shared/references/review-gate-plan.md:44` | conclude requires current final evidence and passing complete | Explains conclude precondition; dup build-finish §6. |
| 3 | keep | `skills/shared/references/review-gate-plan.md:53` | Expand never retro-authorizes; recomputes baseline so prior approval goes stale | Non-obvious CLI side effect. |
| 3 | keep | `skills/shared/references/review-gate-record.md:6` | Reuse same reviewer agent for both phases, continuing context | Cost preference; not inferable. |
| 3 | keep | `skills/shared/references/review-gate-record.md:38` | Behavior changes default to failing test unless concrete alternative approved | Encodes test-first preference. |
| 3 | keep | `skills/shared/references/review-gate-record.md:41` | implementation_review_required true when structural_risk above low | Field semantics (CLI enforces half). |
| 3 | keep | `skills/shared/references/review-gate-record.md:45` | Review every subject change incl. external artifacts; record fingerprint | Coverage contract. |
| 3 | keep | `skills/shared/references/review-gate-record.md:47` | tier_confirmed semantics; false blocks complete | Non-obvious field effect (dup review-gates:122). |
| 3 | keep | `skills/shared/references/review-gate-record.md:53` | Low tier lightweight checks: scope, results, no extra behavior | Defines low-tier review content. |
| 3 | keep | `skills/shared/references/review-gate-worktree.md:3` | Subject bound to approval checkout; shared git dir/artifact never authorizes elsewhere | Prevents unauthorized writes in other checkouts. |
| 3 | merge→build-worktree.md:51 | `skills/shared/references/review-gate-worktree.md:7` | Bind: bind-worktree for owned scope; stale bindings stop | build-worktree has exact commands. |
| 3 | merge→build-worktree.md:62 | `skills/shared/references/review-gate-worktree.md:10` | Worker checks need three flags; low tier accepts missing pre-edit | Duplicate of build-worktree and build-execution. |
| 3 | merge→build-worktree.md:75 | `skills/shared/references/review-gate-worktree.md:14` | Integration: parents own state; inspect/release before cleanup | Duplicate of build-worktree Release. |
| 3 | keep | `skills/shared/references/review-gate-worktree.md:19` | Completion at approval checkout; live bindings pending; archive stale only if covered | Unique rule on archiving. |
| 3 | keep | `skills/shared/references/review-gate-worktree.md:28` | Bindings never record approval or conclude a parent | Boundary. |
| 3 | keep | `skills/shared/references/review-gates.md:7` | Coordinators read this; executors run brief checkpoints; reviewers use record | Reader routing; dup SKILL.md:10. |
| 3 | keep | `skills/shared/references/review-gates.md:36` | Skill edits still get doc-authoring length check + diff inspection | User preference (CLAUDE.md skill review rule). |
| 3 | keep | `skills/shared/references/review-gates.md:69` | Repository-relative --scope; --artifact for external files, no dirs | Non-obvious flag semantics. |
| 3 | keep | `skills/shared/references/review-gates.md:96` | Persist unresolved choices; ask only when blocking; don't reopen decisions | User preference. |
| 3 | keep | `skills/shared/references/review-gates.md:114` | Material contract changes need fresh verdict | Owner of this rule. |
| 3 | keep | `skills/shared/references/review-gates.md:120` | Finish, reviewer inspects implementation incl. tier_confirmed, complete check | Sequence contract. |
| 3 | keep | `skills/shared/references/review-gates.md:131` | Risky review fixes need fresh approval; others targeted verification | Proportionality rule. |
| 3 | keep | `skills/shared/references/review-gates.md:132` | Do not recursively invoke unrelated reviews once resolved | Prevents review loops (user preference). |
| 3 | keep | `skills/shared/references/varde-code-cli.md:16` | Branch on ok; read data.error; toz handle for truncation; fullMatches | JSON envelope contract. |
| 3 | keep | `skills/shared/references/varde-code-cli.md:36` | symbol_blast_radius partial coverage cannot prove containment | Prevents false "no consumers" conclusions. |
| 3 | keep | `skills/shared/references/varde-code-cli.md:98` | Sandbox denial retry once; index_missing/stale → Read/Grep, report degraded | Degrade contract (dup AGENTS.md sandbox rule). |
| 3 | keep | `skills/shared/references/varde-code-cli.md:103` | Read-only Explore agent never builds; queries after parent confirms | Subagent boundary. |
| 3 | keep | `skills/shared/references/varde-workflow-cli.md:11` | Unknown status (draft, task backlog) makes later calls fail | Concrete, observed trap. |
| 3 | keep | `skills/shared/references/varde-workflow-cli.md:29` | graph on a sibling, not the parent | Non-obvious trap. |
| 3 | keep | `skills/shared/references/varde-workflow-cli.md:33` | `recover --root` finishes interrupted transition | Non-inferable recovery command. |
| 3 | keep | `skills/shared/references/varde-workflow-cli.md:65` | check exit codes 4/3/1; transitions and conclude enforce same checks | Exit 1 infra code only stated here. |
| 3 | keep | `skills/shared/references/varde-workflow-cli.md:107` | ok:false validation is a result; fix cause | Prevents routing around validation. |
| 3 | keep | `skills/varde-change/SKILL.md:8` | "Never ask the user which mode to use." | User preference; agents otherwise ask plan-vs-build. |
| 3 | keep | `skills/varde-change/SKILL.md:45` | Wait for explicit answer; silence leaves decision open | Prevents assuming consent. |
| 3 | merge→build.md:85 | `skills/varde-change/SKILL.md:62` | Draft = backlog plan with -draft id or live OQ bullet | Restated in build.md Select a plan. |
| 3 | keep | `skills/varde-change/assets/PLAN-TEMPLATE.md:9` | depends_on holds sibling dir names, never `<group>/<child>` | Non-obvious schema rule. |
| 3 | keep | `skills/varde-change/assets/PLAN-TEMPLATE.md:14` | Writing style: only Problem/Solution prose; rest one fact per line | User style preference. |
| 3 | keep | `skills/varde-change/assets/TASK-TEMPLATE.md:24` | Test approach / Out of scope / Verification / Progress sections | Sections executor and orchestrator parse. |
| 3 | keep | `skills/varde-change/references/build-execution.md:22` | Material drift from approved scope returns to caller for fresh verdict | Prevents executor silently widening approved scope. |
| 3 | keep | `skills/varde-change/references/build-execution.md:40` | research task: write `creates` doc from primary sources, cite each claim | Output contract for research tasks; not inferable. |
| 3 | merge→build-execution.md:119 | `skills/varde-change/references/build-execution.md:43` | spike: revert own edits; skip Completion commit | Duplicated at Completion step 4; keep one. |
| 3 | keep | `skills/varde-change/references/build-execution.md:48` | Drift check: modifies/creates/renames vs working tree before editing | Prevents building on stale task assumptions. |
| 3 | keep | `skills/varde-change/references/build-execution.md:59` | Run lint and only the task's Verification checks; orchestrator runs suites | User preference (executors run task checks only). |
| 3 | keep | `skills/varde-change/references/build-execution.md:73` | Take expected values from independent source, never recomputed like the code | Prevents tautological tests, a common agent failure. |
| 3 | keep | `skills/varde-change/references/build-execution.md:99` | Stop after two failed attempts at one approach; report blocked | Prevents retry loops burning turns. |
| 3 | keep | `skills/varde-change/references/build-execution.md:113` | Verify every check: assert matches expectation, retrieve output read | Prevents unverified "done". |
| 3 | keep | `skills/varde-change/references/build-execution.md:125` | Paste raw git log/status/task status output | Evidence contract the orchestrator verifies. |
| 3 | keep | `skills/varde-change/references/build-execution.md:131` | Reproduce any "pre-existing" failure at base commit | Blocks false pre-existing claims. |
| 3 | keep | `skills/varde-change/references/build-finish.md:9` | Finish all source/doc edits before final implementation review | Later edits stale the review fingerprint. |
| 3 | script | `skills/varde-change/references/build-finish.md:15` | Run simplify only when diff >150 lines or adds files/abstractions | User-set threshold; the shortstat test could live in a script. |
| 3 | keep | `skills/varde-change/references/build-finish.md:18` | Run every acceptance-criteria assert/retrieve check | Prevents concluding on unchecked AC. |
| 3 | merge→review-gate-plan.md | `skills/varde-change/references/build-finish.md:27` | Reviewer payload list (plan id, subject, goal, AC, tasks, location, paths) | Near-duplicate of review-gate-plan payload; name once. |
| 3 | keep | `skills/varde-change/references/build-finish.md:57` | Parent presents one triage table in fix.md format; records user choices | User-decision boundary for deferred findings. |
| 3 | keep | `skills/varde-change/references/build-finish.md:64` | Action-item: parent creates nested companion plan | Non-inferable routing. |
| 3 | keep | `skills/varde-change/references/build-finish.md:95` | Commit plan status change when tracked | Prevents lost completion state. |
| 3 | keep | `skills/varde-change/references/build-finish.md:103` | Top-level: `varde-knowledge reflect`; nested run writes no handoff | Prevents duplicate handoffs under orchestrate. |
| 3 | keep | `skills/varde-change/references/build-finish.md:107` | Record each outcome via `conclusion-action`; skipped gets `--output "none..."` | CLI bookkeeping contract. |
| 3 | keep | `skills/varde-change/references/build-micro-change.md:7` | No plan/task files, worktrees, handoffs, commits unless escalation or asked | Prevents over-ceremony and unrequested commits. |
| 3 | merge→review-gates.md | `skills/varde-change/references/build-micro-change.md:36` | Complete any required independent implementation review | Owned by review-gates. |
| 3 | keep | `skills/varde-change/references/build-micro-change.md:41` | Standalone finding: contract fields, artifact scope, Disposition, triage_status | Cross-skill format contract. |
| 3 | keep | `skills/varde-change/references/build-parallel.md:16` | Commit each task's paths separately, bookkeeping separately | Revertability contract. |
| 3 | shorten | `skills/varde-change/references/build-parallel.md:40` | Workers commit on branch w/o task-file edits; report fields list | Report fields duplicate build-execution:125. |
| 3 | keep | `skills/varde-change/references/build-parallel.md:64` | Never transition/edit task files in integration worktree | Prevents bookkeeping in wrong checkout. |
| 3 | keep | `skills/varde-change/references/build-parallel.md:86` | Bookkeeping failure: keep refs, report step, resume without re-merge | Prevents double merges. |
| 3 | keep | `skills/varde-change/references/build-parallel.md:92` | Resume: confirm branches/paths exist; missing worktree is blocker | Prevents recreating state wrongly. |
| 3 | keep | `skills/varde-change/references/build-posture-debug.md:5` | Run exactly one mode and name it to the user | Makes diagnose-only boundary visible; prevents surprise edits. |
| 3 | keep | `skills/varde-change/references/build-posture-debug.md:36` | Missing field: stop before mutation; smoke check no substitute | Prevents fixes without evidence. |
| 3 | keep | `skills/varde-change/references/build-posture-debug.md:44` | Standalone no numeric budget; on repeat failure load retry-reassessment | Routing to the reassessment stop. |
| 3 | keep | `skills/varde-change/references/build-posture-debug.md:51` | Build a fast deterministic pass/fail command asserting exact symptom; show output | Evidence-first core; agents often skip reproduction. |
| 3 | keep | `skills/varde-change/references/build-posture-debug.md:60` | No local repro: bounded trace labeled unreproduced; else stop and ask | Prevents speculative fixes; ask boundary. |
| 3 | keep | `skills/varde-change/references/build-posture-debug.md:68` | Confirm loop reproduces the user's failure, not a nearby one | Plausible moderate-cost misdiagnosis. |
| 3 | keep | `skills/varde-change/references/build-posture-debug.md:87` | Tag debug logs with unique prefix (e.g. `[DEBUG-a4f2]`) | Enables the Phase 6 grep cleanup; left logs are moderate-cost. |
| 3 | keep | `skills/varde-change/references/build-posture-debug.md:93` | Regression test at call-site seam; single-caller test gives false confidence | Prevents false-green regression tests. |
| 3 | keep | `skills/varde-change/references/build-posture-debug.md:99` | No test seam: pre-edit-approved alternative or note gap; report unverified | Prevents claiming verified fixes without evidence. |
| 3 | keep | `skills/varde-change/references/build-posture-debug.md:109` | Remove `[DEBUG-...]` instrumentation (grep prefix); delete prototypes | Leaked debug code is a real moderate cost. |
| 3 | keep | `skills/varde-change/references/build-posture-debug.md:113` | Task file: complete via execution Completion; standalone commit only when asked | User preference on commits. |
| 3 | keep | `skills/varde-change/references/build-posture-refactor.md:3` | Behavior preservation definition: stdout, stderr, rc, side effects, APIs, logs, wire formats | Defines the contract checked; narrower than model default. |
| 3 | keep | `skills/varde-change/references/build-posture-refactor.md:35` | Read covering tests; none → characterization test first | Core refactor safety net. |
| 3 | shorten | `skills/varde-change/references/build-posture-refactor.md:58` | Commit once: task per build-execution Completion; taskless with change ID | Pointer suffices for task case. |
| 3 | shorten | `skills/varde-change/references/build-posture-refactor.md:84` | Parent marks done only after integration and release; wave handles merge | Parent-side rule; lives better in build.md/build-parallel. |
| 3 | keep | `skills/varde-change/references/build-posture-refactor.md:87` | Taskless: run complete checkpoint after integration and release | Gate contract. |
| 3 | keep | `skills/varde-change/references/build-retry-reassessment.md:5` | Report in chat; task owner records in Progress; workers report to orchestrator | Where the record goes; state ownership. |
| 3 | keep | `skills/varde-change/references/build-retry-reassessment.md:9` | Assess cause among four classes; repeated failure doesn't prove architecture wrong | Prevents premature redesign escalation. |
| 3 | keep | `skills/varde-change/references/build-retry-reassessment.md:16` | State what must change; a retry names what changed | Prevents identical retries. |
| 3 | keep | `skills/varde-change/references/build-worktree.md:13` | Merge before asking user to open files in original checkout | Prevents user editing stale copy. |
| 3 | keep | `skills/varde-change/references/build-worktree.md:37` | Resolve conflicts against intent; verify; abort and report if guessing | Prevents wrong-intent merges. |
| 3 | keep | `skills/varde-change/references/build-worktree.md:58` | Scope binding to declared writes, both rename sides; taskless omits --task | Mis-scoped binding blocks worker. |
| 3 | keep | `skills/varde-change/references/build-worktree.md:84` | Release fails: keep worktree and binding | Prevents losing recovery state. |
| 3 | keep | `skills/varde-change/references/build-worktree.md:85` | Keep/PR: binding stays live; report source, pending, path; write handoff | Resumability contract. |
| 3 | keep | `skills/varde-change/references/build-worktree.md:104` | Feature checkout is approval checkout; never substitute main subject or copy records | Prevents cross-checkout approval confusion. |
| 3 | shorten | `skills/varde-change/references/build-worktree.md:114` | Isolated run may enter at integration choice; tasks complete before review | Dense; overlaps build-finish:3. |
| 3 | keep | `skills/varde-change/references/build-worktree.md:119` | Present finish choices before parent review; Merge sequence | Ordering contract. |
| 3 | keep | `skills/varde-change/references/build-worktree.md:128` | Caller-owned feature child: return pending, or conclude locally | Ownership routing. |
| 3 | keep | `skills/varde-change/references/build.md:25` | Interactive pauses; unattended runs without pauses | Mode contract used by orchestrate. |
| 3 | keep | `skills/varde-change/references/build.md:39` | Isolate only on request or concrete risk; state reason | User preference against needless worktrees. |
| 3 | keep | `skills/varde-change/references/build.md:47` | Select, state, and pass each task's posture | Brief contract for executors. |
| 3 | keep | `skills/varde-change/references/build.md:51` | Posture selection table | Non-inferable mapping (refactor from review findings). |
| 3 | keep | `skills/varde-change/references/build.md:70` | Resume check; handle blocked task before wave | Ordering contract. |
| 3 | keep | `skills/varde-change/references/build.md:72` | Summarize done/blocked; remaining todo as blocked_by_dep; keep active | Report and state contract. |
| 3 | keep | `skills/varde-change/references/build.md:79` | All tasks done: follow build-finish unless user stops | Routing to finish. |
| 3 | script | `skills/varde-change/references/build.md:84` | Select a plan: discover, filter via readiness/graph, order, present | Deterministic; a `plan-select` script or CLI flag could return the list. |
| 3 | merge→build-worktree.md:51 | `skills/varde-change/references/build.md:150` | Tasks in another checkout: register per build-worktree; parent transitions | Restates build-worktree Register section. |
| 3 | keep | `skills/varde-change/references/build.md:172` | After each wave regenerate listed generated outputs | Non-inferable ownership; executors skip these. |
| 3 | keep | `skills/varde-change/references/build.md:177` | Accept spike: confirm Q/A, evidence, revert; skip commit audit | Spike acceptance contract. |
| 3 | merge→build-execution.md:99 | `skills/varde-change/references/build.md:192` | "An executor stops after two failed attempts..." | Executor-side rule stated in build-execution. |
| 3 | keep | `skills/varde-change/references/build.md:194` | Re-dispatch once with failure, diff, checks, progress; never blind | Prevents blind retries. |
| 3 | keep | `skills/varde-change/references/build.md:196` | Second failure: blocked, reassessment, then blocked-task choice | Escalation sequence. |
| 3 | keep | `skills/varde-change/references/orchestrate.md:17` | Discover groups with non-completed children; present; stop until chosen | Selection contract. |
| 3 | keep | `skills/varde-change/references/orchestrate.md:30` | Current checkout unless user asks for feature worktree | User preference against needless isolation. |
| 3 | keep | `skills/varde-change/references/orchestrate.md:35` | Feature worktree only on ask and tracked storage | Guard on external storage. |
| 3 | merge→build-worktree.md:104 | `skills/varde-change/references/orchestrate.md:44` | Feature checkout is owning approval repo; never copy main approvals | Duplicates build-worktree Feature checkout. |
| 3 | keep | `skills/varde-change/references/orchestrate.md:64` | Group approval doesn't replace child gates; batch reviewer session | Cost optimization + gate rule. |
| 3 | keep | `skills/varde-change/references/orchestrate.md:92` | Resume from first non-completed child | Resume rule. |
| 3 | keep | `skills/varde-change/references/orchestrate.md:94` | worktree-create exit 3: verify registered path+branch before reuse | Recovery contract (see defects re exit code). |
| 3 | keep | `skills/varde-change/references/orchestrate.md:103` | Triage all children's escalated findings in one combined table | User preference: one decision table. |
| 3 | keep | `skills/varde-change/references/orchestrate.md:108` | Review group: aggregate AC, finish edits, entire-group independent review | Gate contract at group level. |
| 3 | keep | `skills/varde-change/references/orchestrate.md:123` | Commit group bookkeeping before Merge/Push; stage only group paths | Preserves unrelated edits. |
| 3 | keep | `skills/varde-change/references/orchestrate.md:130` | varde-knowledge reflect at session boundary | Handoff contract. |
| 3 | shorten | `skills/varde-change/references/plan-decomposition.md:3` | Scope paragraph: when to run; single outcome writes one task, skip edge checks | Long run-on; the skip clause is the value. |
| 3 | keep | `skills/varde-change/references/plan-decomposition.md:15` | Wide refactor: expand/migrate/contract with blast radius | Non-obvious decomposition shape. |
| 3 | keep | `skills/varde-change/references/plan-decomposition.md:16` | Deletion: grep task bodies, tests, dependents | Prevents cross-task breakage. |
| 3 | keep | `skills/varde-change/references/plan-decomposition.md:17` | File pointer: add depends_on for created/renamed paths | Prevents wave misordering. |
| 3 | keep | `skills/varde-change/references/plan-decomposition.md:26` | Per-task required fields list | Template content contract. |
| 3 | keep | `skills/varde-change/references/plan-decomposition.md:36` | Profile authority: user, repo, test-first; alternatives need review | Encodes user preference ordering. |
| 3 | keep | `skills/varde-change/references/plan-decomposition.md:50` | Name external state in verification_resources | Scheduler conflict detection. |
| 3 | keep | `skills/varde-change/references/plan-decomposition.md:52` | Generated outputs owned by plan, not tasks | Prevents ownership conflicts. |
| 3 | keep | `skills/varde-change/references/plan-decomposition.md:65` | One public behavior per task, one outcome, no open choices | Sizing rule. |
| 3 | script | `skills/varde-change/references/plan-decomposition.md:67` | Peak context formula ≤100k; include estimate in table | Arithmetic is deterministic; script from file list. |
| 3 | keep | `skills/varde-change/references/plan-decomposition.md:75` | Interactive: show table, pause once; unattended skip | Pause rule referenced by build.md. |
| 3 | keep | `skills/varde-change/references/plan.md:9` | Find drafts at any depth; nested child id is path | Non-obvious search scope. |
| 3 | keep | `skills/varde-change/references/plan.md:12` | List drafts as numbered `title - plan id`; ask which; none → wait | Selection UX contract. |
| 3 | keep | `skills/varde-change/references/plan.md:23` | Work in current checkout; isolate only on request/caller/collision; probe ignored first | User preference against needless isolation. |
| 3 | keep | `skills/varde-change/references/plan.md:32` | Seed best guesses in template formats; every unknown as OQ or Assumption | Drives the growth loop; prevents blank plans. |
| 3 | keep | `skills/varde-change/references/plan.md:34` | In-scope deferred findings as OQs; match blank Disposition by Location; dedupe | Non-inferable matching rule. |
| 3 | keep | `skills/varde-change/references/plan.md:39` | Tell user plan path, welcome edits; ask one question, wait | Interaction contract. |
| 3 | keep | `skills/varde-change/references/plan.md:59` | Route every unknown instead of blocking; impact beats confidence | Core routing principle for the loop. |
| 3 | keep | `skills/varde-change/references/plan.md:62` | Confident, local impact → Assumptions confidence: high, no turn | User preference: fewer questions. |
| 3 | keep | `skills/varde-change/references/plan.md:68` | Everything else → Open Questions with recommendation, ask | Routing rule. |
| 3 | keep | `skills/varde-change/references/plan.md:72` | Push back; propose smaller shape; offer do-not-build | User preference; agents default to compliance. |
| 3 | keep | `skills/varde-change/references/plan.md:92` | Search <knowledge> for specs/decisions; link, flag stale, record missing | Cross-skill contract with knowledge store. |
| 3 | keep | `skills/varde-change/references/plan.md:107` | Resolve: Design subsection, Decisions log `q -> a`, remove line | Format contract for plan doc. |
| 3 | keep | `skills/varde-change/references/plan.md:120` | Doc-driven mode opt-in; switch on request; stop asking | User preference. |
| 3 | keep | `skills/varde-change/references/plan.md:127` | Self-review when OQ first empty and at Finalize; finalize when nothing new | Exit criteria contract. |
| 3 | keep | `skills/varde-change/references/plan.md:135` | External interface: find consumers, record in Design/AC; fan-out = split signal | Prevents breaking consumers. |
| 3 | keep | `skills/varde-change/references/plan.md:147` | Self-review: empty OQ isn't done; add OQs for placeholders, contradictions, scope, ambiguity | Prevents premature finalization. |
| 3 | keep | `skills/varde-change/references/plan.md:155` | Model generalization shift → one OQ: promote or add alongside | Specific, non-obvious design trap. |
| 3 | keep | `skills/varde-change/references/plan.md:166` | assert: preferred; retrieve only for semantic judgment; self-grading bias | Prevents unverifiable LLM-judged AC. |
| 3 | keep | `skills/varde-change/references/plan.md:173` | Each criterion names its command or file; else rewrite or block | Prevents weakened criteria. |
| 3 | shorten | `skills/varde-change/references/plan.md:195` | Independent reviewer payload and check list | Overlaps review-gate-plan.md payload list. |
| 3 | keep | `skills/varde-change/references/plan.md:203` | Apply findings; material change needs fresh approval, else verdict carries | Gate rule (also in review-gates). |
| 3 | keep | `skills/varde-change/references/plan.md:219` | After confirmation no changes; stays backlog until build | State contract. |
| 3 | keep | `skills/varde-change/references/plan.md:221` | Ignored plans local; else commit only plan dir | Commit scope contract. |
| 3 | keep | `skills/varde-change/references/plan.md:233` | List candidates and order; ask; wait | User-decision boundary. |
| 3 | keep | `skills/varde-change/references/status.md:5` | Plans table: non-completed, newest first, top 5, columns, empty message | Output format contract. |
| 3 | keep | `skills/varde-change/references/verify.md:7` | Target table: id/slug, group, none → most recent completed | Resolution contract. |
| 3 | keep | `skills/varde-change/references/verify.md:19` | Read AC; stop if missing except group parent → verify children | Group handling not inferable. |
| 3 | keep | `skills/varde-change/references/verify.md:21` | Ignore checkbox state; check is a claim | Prevents trusting ticks. |
| 3 | keep | `skills/varde-change/references/verify.md:25` | Run assert exactly as written; no substitution; broad checks only when asked | Prevents substituting easier checks. |
| 3 | keep | `skills/varde-change/references/verify.md:32` | Classify passed/failed/unavailable | Output vocabulary. |
| 4 | keep | `skills/shared/references/review-gate-plan.md:7` | Run risk-tier.py over full scope; missing evidence → high tier | Script contract; drives tier. |
| 4 | keep | `skills/shared/references/review-gate-plan.md:11` | `review init --plan ... --tier-evidence` command | CLI contract. |
| 4 | merge→build.md:203 | `skills/shared/references/review-gate-plan.md:22` | Tasks inherit parent subject; no per-task approvals | Stated in build.md, build-worktree, build-execution too. |
| 4 | keep | `skills/shared/references/review-gate-plan.md:49` | review contract / review expand; tier-evidence optional reverts to high; at inspected version | CLI contract with non-obvious tier effect. |
| 4 | keep | `skills/shared/references/review-gate-record.md:9` | Take id at data.subject.subject_id | JSON path contract. |
| 4 | keep | `skills/shared/references/review-gate-record.md:11` | `review inspect --phase`; copy data.version and record_template | CLI contract. |
| 4 | keep | `skills/shared/references/review-gate-record.md:27` | Implementation record needs coverage entire-subject-change, fingerprint, tier_confirmed | Schema contract. |
| 4 | keep | `skills/shared/references/review-gate-record.md:28` | Submit via `review record --expected-version --file`; pre-edit before any edit | CLI contract. |
| 4 | keep | `skills/shared/references/review-gate-worktree.md:30` | Load review-gate-record only as independent reviewer, never self-approve | Self-approval guard. |
| 4 | keep | `skills/shared/references/review-gates.md:13` | Mechanical exception: only spelling/punctuation/whitespace/formatting | Precise boundary; prevents gate evasion. |
| 4 | keep | `skills/shared/references/review-gates.md:21` | Full gate for commands, paths, conditions, meaning, contracts, config, code, tests | Boundary list. |
| 4 | keep | `skills/shared/references/review-gates.md:45` | Branch: persisted plan → review-gate-plan; other checkout → review-gate-worktree | Routing. |
| 4 | keep | `skills/shared/references/review-gates.md:54` | Contract JSON keys outcome/scope/assumptions/design/open_choices/verification | Schema contract. |
| 4 | keep | `skills/shared/references/review-gates.md:61` | Compute risk tier with script from repo root | Script contract. |
| 4 | keep | `skills/shared/references/review-gates.md:63` | `review init --subject --contract --tier-evidence` command | CLI contract. |
| 4 | keep | `skills/shared/references/review-gates.md:77` | Low tier skips pre-edit; high runs steps | Tier routing. |
| 4 | keep | `skills/shared/references/review-gates.md:81` | Clean-context agent gets subject, repo, paths, outcome, assumptions, verification, risk | Reviewer brief contract. |
| 4 | keep | `skills/shared/references/review-gates.md:89` | Reviewer loads review-gate-record; records verdict before edit | Routing. |
| 4 | keep | `skills/shared/references/review-gates.md:103` | Checkpoints start/resume/complete | CLI contract. |
| 4 | keep | `skills/shared/references/review-gates.md:111` | exit 4 blocker; exit 3 OCC re-inspect and retry | Exit codes. |
| 4 | keep | `skills/shared/references/review-gates.md:118` | Implementation review always required, independent of tier | Core gate rule. |
| 4 | keep | `skills/shared/references/review-gates.md:127` | Reviewer selection: doc-authoring / varde-review report / low-tier clean-context | Cross-skill routing. |
| 4 | keep | `skills/shared/references/varde-code-cli.md:4` | Use when scope/dependents/tests unknown; absent → Read/Grep; never build/install | Degrade rule; prevents install side-trips. |
| 4 | keep | `skills/shared/references/varde-code-cli.md:10` | Main agent runs `watch --ensure`; only watcher writes index; wait ready | Prevents index corruption and stale queries. |
| 4 | keep | `skills/shared/references/varde-code-cli.md:24` | Call as `varde-code <cmd> --json '{"repoRoot"...}'`; --help for shapes | Invocation contract. |
| 4 | keep | `skills/shared/references/varde-workflow-cli.md:14` | State table with legal moves | State-transition contract. |
| 4 | keep | `skills/shared/references/varde-workflow-cli.md:21` | readiness/graph/transition/validate commands | CLI invocations. |
| 4 | keep | `skills/shared/references/varde-workflow-cli.md:104` | Fallback: retry escalated once; else Read/Write, name lost capability | Degrade contract. |
| 4 | keep | `skills/varde-change/SKILL.md:10` | Apply review-gates before implementation edits; carry verdict through completion | Core gate routing. |
| 4 | merge→review-gates.md:7 | `skills/varde-change/SKILL.md:11` | Executor with caller-supplied subject runs only build-execution checks | Also in review-gates:7 and build-execution:8; keep one. |
| 4 | keep | `skills/varde-change/SKILL.md:17` | Explicit intent wins: review → varde-review; exploration → varde-explore; build wins for bug | Cross-skill routing. |
| 4 | keep | `skills/varde-change/SKILL.md:23` | Routing table (11 rows) | Core dispatch. |
| 4 | keep | `skills/varde-change/SKILL.md:64` | Resolve <working>/<knowledge> via `varde-workflow paths --json`; retry escalated; never guess | Path contract; guessing writes to wrong store. |
| 4 | keep | `skills/varde-change/SKILL.md:65` | Denied/erroring varde-workflow: load varde-workflow-cli fallback | Conditional load routing. |
| 4 | keep | `skills/varde-change/assets/PLAN-TEMPLATE.md:4` | Frontmatter fields status/title/type/depends_on/observed_specs | Schema validated by varde-workflow. |
| 4 | keep | `skills/varde-change/assets/PLAN-TEMPLATE.md:18` | Body section skeleton | Sections other steps read and validate. |
| 4 | keep | `skills/varde-change/assets/TASK-TEMPLATE.md:3` | Frontmatter fields status/depends_on/modifies/creates/renames/verification_resources | Schema for resolver and transition. |
| 4 | keep | `skills/varde-change/references/build-execution.md:8` | "These checks are your whole review gate; skip review-gates.md." | Prevents executor re-running full gate or re-initializing the subject. |
| 4 | keep | `skills/varde-change/references/build-execution.md:13` | Run `review check --checkpoint start` before first edit | CLI gate contract; edits without it are unapproved. |
| 4 | merge→build-execution.md:13 | `skills/varde-change/references/build-execution.md:19` | Resume with `--checkpoint resume` | Contract, but fold into step 1 as "start, or resume when continuing". |
| 4 | keep | `skills/varde-change/references/build-execution.md:20` | Exit 3 rerun; exit 4 stop and return blocker | Exit-code contract the agent cannot infer. |
| 4 | keep | `skills/varde-change/references/build-execution.md:30` | Separate checkout: load build-worktree, pass --repository/--worktree/--binding; stop if missing | Binding flags are a CLI contract; wrong checkout breaks approval. |
| 4 | keep | `skills/varde-change/references/build-execution.md:41` | debug posture: load build-posture-debug, keep debug_evidence | Routing to posture reference. |
| 4 | keep | `skills/varde-change/references/build-execution.md:42` | refactor posture: load build-posture-refactor | Routing to posture reference. |
| 4 | keep | `skills/varde-change/references/build-execution.md:87` | Sibling-blocked check: report `waiting: sibling failure` | Status token the orchestrator parses. |
| 4 | keep | `skills/varde-change/references/build-execution.md:90` | Write outside modifies/creates/renames is a blocker | Ownership contract; prevents cross-task collisions. |
| 4 | keep | `skills/varde-change/references/build-execution.md:101` | Blocker table: serial transitions task; parallel reports without editing task file | State-transition contract per execution mode. |
| 4 | keep | `skills/varde-change/references/build-execution.md:115` | Serial: transition todo→in_progress→done; Progress names checks run | State-transition contract. |
| 4 | keep | `skills/varde-change/references/build-execution.md:121` | Commit task paths referencing task ID; task file only in owning checkout; no commit in shared wave | Commit contract per mode. |
| 4 | keep | `skills/varde-change/references/build-finish.md:3` | Isolated/caller-owned child: follow build-worktree Finish first; else enter after tasks done | Routing and entry precondition. |
| 4 | keep | `skills/varde-change/references/build-finish.md:13` | observed_specs: refresh via `varde-docs spec`; conclusion rejects stale specs | Conclude gate contract. |
| 4 | keep | `skills/varde-change/references/build-finish.md:22` | Record risk decision per review-gates; reviewer per §5 | Routing into the gate owner. |
| 4 | keep | `skills/varde-change/references/build-finish.md:38` | Reviewer inspects phase `implementation`, records via `review record` | CLI contract for implementation evidence. |
| 4 | keep | `skills/varde-change/references/build-finish.md:41` | Unavailable reviewer: leave required review pending | Prevents self-review substituting for independent review. |
| 4 | keep | `skills/varde-change/references/build-finish.md:49` | Code findings: one executor round of `fix mode=build` with repoRoot, folder, plan_context, paths | Cross-skill invocation contract. |
| 4 | keep | `skills/varde-change/references/build-finish.md:66` | Under orchestrate, return unresolved findings instead of pausing | Orchestrate contract; pausing stalls the run. |
| 4 | keep | `skills/varde-change/references/build-finish.md:79` | Run escalate-deferred.py before conclude; exit 1 fix and rerun | Script invocation contract. |
| 4 | keep | `skills/varde-change/references/build-finish.md:93` | `varde-workflow conclude`; on failure preserve journal | State-transition contract. |
| 4 | keep | `skills/varde-change/references/build-finish.md:112` | Show diff/state; under orchestrate return facts without offering choices | Orchestrate contract. |
| 4 | keep | `skills/varde-change/references/build-micro-change.md:12` | Mechanical-edit exception follows review-gates' checks instead | Routing to the gate owner. |
| 4 | keep | `skills/varde-change/references/build-micro-change.md:20` | Contract in <working>; `review init` command | CLI contract. |
| 4 | merge→review-gates.md | `skills/varde-change/references/build-micro-change.md:27` | Low tier skips pre-edit verdict; start check must pass | Tier rule owned by review-gates; keep only the check. |
| 4 | keep | `skills/varde-change/references/build-micro-change.md:30` | Material change: `review contract`/`review expand` + fresh verdict | CLI contract for scope change. |
| 4 | keep | `skills/varde-change/references/build-micro-change.md:37` | Run `complete` checkpoint before reporting | Gate contract. |
| 4 | keep | `skills/varde-change/references/build-parallel.md:4` | Load build-worktree for binding authorization/release | Routing. |
| 4 | keep | `skills/varde-change/references/build-parallel.md:11` | Wait for all; confirm single ownership and hashes | Integration integrity check. |
| 4 | keep | `skills/varde-change/references/build-parallel.md:13` | Combined verification incl. waiting reruns; on fail commit nothing | Prevents committing broken waves. |
| 4 | keep | `skills/varde-change/references/build-parallel.md:21` | Failure leaves target SHA unchanged; keep refs until diagnosed | Recovery contract. |
| 4 | keep | `skills/varde-change/references/build-parallel.md:27` | Clean target, record SHA, worktree-create per task; created=false → serial | Script contract and fallback. |
| 4 | keep | `skills/varde-change/references/build-parallel.md:34` | Register worktree against parent subject; dispatch with binding context | Binding contract. |
| 4 | keep | `skills/varde-change/references/build-parallel.md:51` | Ownership check per commit; stray path fails worker; one retry | Prevents cross-task leakage. |
| 4 | keep | `skills/varde-change/references/build-parallel.md:53` | Any failure: merge none of the wave | Atomic-wave contract. |
| 4 | script | `skills/varde-change/references/build-parallel.md:58` | Integration worktree at SHA; merge workers in task-id order; verify | Deterministic sequence; candidate for a wave-integrate script. |
| 4 | script | `skills/varde-change/references/build-parallel.md:78` | Release bindings, record, commit bookkeeping, cleanup only after | Ordered deterministic steps; scriptable. |
| 4 | keep | `skills/varde-change/references/build-posture-debug.md:8` | Mode table: diagnose = phases 1-4 + 6; fix = all | Routing between modes. |
| 4 | keep | `skills/varde-change/references/build-posture-debug.md:18` | Report `debug_evidence` in field order; append under Progress when task exists | Output contract read by orchestrator/reviewers. |
| 4 | keep | `skills/varde-change/references/build-posture-debug.md:32` | fix: reproduction/hypotheses/experiments required before any production edit | Core evidence-first contract (skill description promise). |
| 4 | keep | `skills/varde-change/references/build-posture-refactor.md:19` | Record branch/SHA; dirty target path must be committed first | Prevents mixing user's uncommitted edits into refactor. |
| 4 | script | `skills/varde-change/references/build-posture-refactor.md:23` | Staged-work check → worktree-create; created=true/false ownership; confirm on resume | Deterministic branch; script could decide and print path. |
| 4 | keep | `skills/varde-change/references/build-posture-refactor.md:31` | Different checkout: load build-worktree, bind before editing | Binding contract; dup of build-execution:30. |
| 4 | keep | `skills/varde-change/references/build-posture-refactor.md:44` | One change per attempt; no unstaged changes; don't stage until pass | Staging-checkpoint protocol the rollback depends on. |
| 4 | keep | `skills/varde-change/references/build-posture-refactor.md:52` | Stage verified paths as checkpoint; rollback preserves them | Part of rollback protocol. |
| 4 | keep | `skills/varde-change/references/build-posture-refactor.md:75` | Own worktree: confirm target, don't overwrite edits, merge, release, cleanup | Ordered integration contract with scripts. |
| 4 | keep | `skills/varde-change/references/build-posture-refactor.md:81` | Caller owns worktree: report commit; merge/cleanup belong to owner | Ownership boundary. |
| 4 | keep | `skills/varde-change/references/build-worktree.md:21` | worktree-create/merge/cleanup scripts; cleanup only after merge exit 0 | Script contract; order prevents lost work. |
| 4 | keep | `skills/varde-change/references/build-worktree.md:28` | Merge exit-code table 2/3/4/5 | Exit codes are not inferable. |
| 4 | keep | `skills/varde-change/references/build-worktree.md:45` | Run binding commands from the approval checkout | Wrong checkout breaks binding identity. |
| 4 | keep | `skills/varde-change/references/build-worktree.md:53` | `review inspect` then `review bind-worktree` with expected-version, scope, task | Exact CLI invocation. |
| 4 | keep | `skills/varde-change/references/build-worktree.md:62` | Put checkout, path, subject, binding in brief; worker passes three flags | Brief contract; dup of build-execution:30. |
| 4 | keep | `skills/varde-change/references/build-worktree.md:75` | Capture evidence, integrate, inspect-worktree, release-worktree with version/commit | Exact CLI sequence. |
| 4 | keep | `skills/varde-change/references/build-worktree.md:93` | Abandon: inspect, `abandon-worktree`; source stays | CLI contract for abandonment. |
| 4 | keep | `skills/varde-change/references/build.md:12` | Unattended failure stops immediately; leave state; merge/clean nothing | Prevents compounding damage when no human watches. |
| 4 | keep | `skills/varde-change/references/build.md:18` | Starting action table (select, named, ad-hoc minimal plan, uncertain → plan) | Routing. |
| 4 | keep | `skills/varde-change/references/build.md:36` | `git check-ignore` plan once; ignored plans never committed | Prevents committing local-only plans. |
| 4 | keep | `skills/varde-change/references/build.md:42` | `execution=<serial\|auto\|inline>` default auto | Parameter contract. |
| 4 | keep | `skills/varde-change/references/build.md:46` | No task files: decompose per plan-decomposition | Routing. |
| 4 | keep | `skills/varde-change/references/build.md:63` | Read build-execution when inline or no executor | Routing for the no-subagent case. |
| 4 | keep | `skills/varde-change/references/build.md:67` | backlog→active before first task only; commit transition when tracked | Illegal active→active transition otherwise. |
| 4 | keep | `skills/varde-change/references/build.md:119` | Run resolve-execution-wave.py before each wave; report blocked_by_dep/reasons; exit 3 cycle | Script contract. |
| 4 | keep | `skills/varde-change/references/build.md:124` | requires_signoff task needs explicit sign-off; unattended halts | User-authored approval boundary. |
| 4 | keep | `skills/varde-change/references/build.md:131` | Strategy table parallel/serial/inline | Routing by execution param. |
| 4 | keep | `skills/varde-change/references/build.md:141` | Task-file ownership: serial executor owns; parallel orchestrator records; only orchestrator touches plan.md | Single-writer contract across agents. |
| 4 | keep | `skills/varde-change/references/build.md:156` | Obtain missing pre-edit verdict; material drift returns to gate | Gate routing. |
| 4 | keep | `skills/varde-change/references/build.md:158` | Transition task to in_progress (legal from todo/blocked) | State transition contract. |
| 4 | keep | `skills/varde-change/references/build.md:160` | Executor brief fields list | Executor has no other context; contract. |
| 4 | script | `skills/varde-change/references/build.md:181` | Ownership audit via git diff-tree vs modifies/creates/renames; one corrective re-dispatch | Deterministic compare; ideal script (duplicated in build-parallel:51). |
| 4 | keep | `skills/varde-change/references/build.md:217` | Resume: derive state from frontmatter+Progress; done needs commit | Resume contract. |
| 4 | keep | `skills/varde-change/references/build.md:224` | Unproven done, in_progress, blocked: show and let human decide; unattended halt | Prevents silently accepting unverified work. |
| 4 | keep | `skills/varde-change/references/build.md:235` | Blocked task: unattended stop; interactive Retry/Continue/Abort | Decision contract. |
| 4 | keep | `skills/varde-change/references/orchestrate.md:4` | Orchestrator never edits production source or dispatches tasks | Role boundary; prevents double-execution. |
| 4 | keep | `skills/varde-change/references/orchestrate.md:9` | Route table: group, discover, non-group → build | Routing. |
| 4 | keep | `skills/varde-change/references/orchestrate.md:25` | Readiness per child; skip completed; missing dep blocks; cycle stops | Ordering contract. |
| 4 | keep | `skills/varde-change/references/orchestrate.md:38` | Load build-worktree, id orchestrate-<group-id>, validate reuse | Naming contract used in Resume. |
| 4 | keep | `skills/varde-change/references/orchestrate.md:52` | Confirm group contract matches children; drift needs fresh approval | Aggregate contract integrity. |
| 4 | keep | `skills/varde-change/references/orchestrate.md:57` | Init group subject; reuse on resume, never reset baseline | CLI contract; reset loses approvals. |
| 4 | keep | `skills/varde-change/references/orchestrate.md:69` | Group start/resume check then activate; no active→active | State transitions. |
| 4 | keep | `skills/varde-change/references/orchestrate.md:79` | Children sequential via build named-plan; skip own merge in feature worktree | Delegation contract. |
| 4 | keep | `skills/varde-change/references/orchestrate.md:86` | Child blocks: stop, run no later child, merge nothing, report | Prevents compounding failure. |
| 4 | keep | `skills/varde-change/references/orchestrate.md:106` | Release nested bindings before group completion | Gate contract. |
| 4 | keep | `skills/varde-change/references/orchestrate.md:126` | Offer one finish choice per build-finish; execute only chosen | Outward-action boundary. |
| 4 | keep | `skills/varde-change/references/plan-decomposition.md:18` | Unsettled interface: stop, hand off to plan | Routing. |
| 4 | keep | `skills/varde-change/references/plan-decomposition.md:54` | `[]` for empty; omit unknown so scheduling stays serial | Schema semantics the resolver uses. |
| 4 | keep | `skills/varde-change/references/plan-decomposition.md:56` | spike: kind: spike with empty ownership | CLI transition contract. |
| 4 | keep | `skills/varde-change/references/plan-decomposition.md:77` | Write from template; kebab-case ids unique, no date prefix; readiness never stored | Format contract. |
| 4 | keep | `skills/varde-change/references/plan.md:27` | `plan-path.py draft` creates dir; create plan.md from template; title = prompt | Script and path contract. |
| 4 | keep | `skills/varde-change/references/plan.md:64` | Needs something concrete → [needs prototype], invoke varde-prototype | Cross-skill routing. |
| 4 | keep | `skills/varde-change/references/plan.md:78` | Close do-not-build only on explicit agreement; discard dir | Irreversible deletion needs consent. |
| 4 | keep | `skills/varde-change/references/plan.md:98` | Add domain to observed_specs when a spec covers changed code | Feeds build-finish spec refresh. |
| 4 | keep | `skills/varde-change/references/plan.md:103` | Watch the doc: diff plan.md; user edits count as answers | Prevents overwriting user edits. |
| 4 | keep | `skills/varde-change/references/plan.md:117` | Single writer: only this session edits plan.md; subagents return findings | Prevents concurrent plan corruption. |
| 4 | keep | `skills/varde-change/references/plan.md:180` | Derive slug without asking; `plan-path.py finalize`; record ignored | Script contract. |
| 4 | keep | `skills/varde-change/references/plan.md:185` | `varde-workflow validate` and fix before review | CLI contract. |
| 4 | keep | `skills/varde-change/references/plan.md:187` | Decompose before review per plan-decomposition | Ordering contract. |
| 4 | keep | `skills/varde-change/references/plan.md:188` | Apply review-gates; `review init --plan` command | CLI contract. |
| 4 | keep | `skills/varde-change/references/plan.md:200` | Reviewer records via `review record`; keep subject id in Progress | Resume contract. |
| 4 | keep | `skills/varde-change/references/plan.md:210` | Final completeness check: all unseen assumptions and changes; wait for explicit confirmation | User-consent boundary. |
| 4 | keep | `skills/varde-change/references/plan.md:235` | Nested child path; no children/parent fields; finalize each | Path contract. |
| 4 | keep | `skills/varde-change/references/plan.md:240` | Parent shape: group; aggregate contract outside Progress; commit together | Format contract orchestrate reads. |
| 4 | keep | `skills/varde-change/references/status.md:13` | Use readiness; recommend one mode as `Recommended next mode:`; never run it | Read-only boundary and routing. |
| 5 | keep | `skills/shared/references/review-gate-record.md:22` | Fill from own assessment; never default approval; write outside source scope | Prevents rubber-stamp approvals. |
| 5 | keep | `skills/shared/references/review-gates.md:3` | Gate every implementation change through varde-change; read-only needs none | Cross-skill routing core. |
| 5 | keep | `skills/shared/references/review-gates.md:94` | Coordinators never enter reviewer records or prose approval | Self-approval boundary. |
| 5 | keep | `skills/shared/references/review-gates.md:98` | No reviewer/CLI: stop; no self-approval or manual fallback | Safety boundary. |
| 5 | keep | `skills/shared/references/varde-workflow-cli.md:19` | Change status via `transition`, never edit status directly | Hand edits bypass gate enforcement. |
| 5 | keep | `skills/shared/references/varde-workflow-cli.md:96` | Fallback never applies to review/gated ops; stop; no prose approval | Safety boundary on degraded mode. |
| 5 | keep | `skills/varde-change/references/build-execution.md:10` | "never initialize or record approval yourself" | Stops executor self-approving, which voids the independent review gate. |
| 5 | keep | `skills/varde-change/references/build-execution.md:83` | Shared-checkout wave: owned paths only, no state-changing Git, scoped formatters, report hashes | Prevents clobbering sibling executors' uncommitted work. |
| 5 | keep | `skills/varde-change/references/build-execution.md:93` | UI check needs own browser tool; user credentials only; no real-data forms | Outward-facing safety and false-evidence guard. |
| 5 | keep | `skills/varde-change/references/build-finish.md:86` | Run complete checkpoint; never conclude from stale/missing record | Core gate; false completion is cross-skill. |
| 5 | keep | `skills/varde-change/references/build-finish.md:118` | Merge only run-created worktrees via scripts; never merge caller-owned | Prevents destroying caller-owned worktrees. |
| 5 | keep | `skills/varde-change/references/build-finish.md:125` | Push/PR only after explicit choice; named branch; clean committed | Outward-facing action boundary. |
| 5 | keep | `skills/varde-change/references/build-parallel.md:69` | Confirm clean target at SHA; `git merge --ff-only`, only ref change | Prevents irreversible target-branch damage. |
| 5 | keep | `skills/varde-change/references/build-posture-debug.md:13` | diagnose: production source read-only; no fix, test, or commit | Honors user's no-change request; unrequested edits are outward-facing. |
| 5 | keep | `skills/varde-change/references/build-posture-refactor.md:47` | Restore only attempt paths; never whole-tree clean/checkout/reset | Prevents destroying user's uncommitted work. |
| 5 | keep | `skills/varde-change/references/build-worktree.md:8` | Ownership table: created=true own; created=false never merge or clean up | Prevents destroying a caller's worktree. |
| 5 | keep | `skills/varde-change/references/build-worktree.md:61` | Never initialize a separate subject per task or broaden repository identity | Prevents bypassing plan-level approval. |
| 5 | keep | `skills/varde-change/references/build.md:8` | Runner never edits source; one commit per task; never push or reset --hard | Irreversible/outward git actions. |
| 5 | keep | `skills/varde-change/references/build.md:122` | Run only a subset of one next_wave; never mix resolver runs or pair conflicts | Prevents concurrent edits colliding. |
| 5 | keep | `skills/varde-change/references/build.md:203` | Tasks inherit plan subject; never init per task; start/resume checks | Prevents approval bypass. |
| 5 | keep | `skills/varde-change/references/orchestrate.md:115` | complete check + conclude; never plain-transition to completed; no main-subject vs unmerged source | Prevents false completion and approval misuse. |
| 5 | keep | `skills/varde-change/references/plan-decomposition.md:48` | Declare every written path in modifies/creates/renames | Scheduler and ownership audit depend on it. |
| 5 | keep | `skills/varde-change/references/plan.md:38` | "The user decides; never add a finding automatically." | User-decision boundary. |
| 5 | keep | `skills/varde-change/references/status.md:3` | Read-only: change no plan, task, or handoff | Status must not mutate state. |
| 5 | keep | `skills/varde-change/references/verify.md:3` | Read-only: never fix, change status, or tick criteria | Report-only boundary. |
| 5 | merge→build-execution.md:93 | `skills/varde-change/references/verify.md:40` | UI check needs own browser; else unavailable; user creds; no real-data forms | Safety rule duplicated verbatim in build-execution. |

## 2. Correctness defects

1. **`--tier-evidence` missing from three init commands.** `review-gates.md:66` and `review-gate-plan.md:12` require `--tier-evidence <risk-tier.json>`, and missing evidence forces high tier. But `varde-change/references/build-micro-change.md:24`, `plan.md:192`, `orchestrate.md:61`, and `shared/references/varde-workflow-cli.md:44-45` show `review init` without it and without the `risk-tier.py` step. An agent that copies the nearest command gets every subject pinned to high tier, so micro-change's "Low tier skips the pre-edit verdict" (`build-micro-change.md:27`) never applies.
2. **Implementation review: "always" vs "when required".** `review-gates.md:118`, `review-gate-record.md:42`, and `review-gate-worktree.md:22` say implementation review is always required. `build-finish.md:24` says "When independent implementation review is required", and `build-micro-change.md:36` says "any required". That wording invites skipping it.
3. **Reviewer context: reuse vs clean.** `review-gate-record.md:6` says to reuse the same reviewer agent across pre-edit and implementation, continuing its context. `review-gates.md:81` and `:128` specify "an agent with a clean, independent context". State which one applies to the implementation phase.
4. **Stale spike pointer.** `assets/TASK-TEMPLATE.md:17` says `kind: spike` works "per references/build-execution.md", but build-execution only defines a `spike` *posture* (`:43`). The `kind: spike` ownership rule is in `plan-decomposition.md:56`.
5. **Decision-log arrow mismatch.** `plan.md:109` says to append `<question> -> <answer>`. `PLAN-TEMPLATE.md:51` uses `<question> → <answer>`.
6. **Cross-skill pointer in a shared file.** `varde-workflow-cli.md:63` points to "the varde-change review procedure", but this file is also copied into `varde-knowledge`, which does not have it. The real owner is `review-gate-record.md`.
7. **Draft definition stated twice.** `SKILL.md:62` and `build.md:85-86` both define a draft. They agree today but will drift. Keep one.
8. **Inconsistent reference prefixes (minor).** `build-micro-change.md:4`, `build-parallel.md:8,36,51`, and `build-posture-refactor.md:59` write `build-execution.md` and `build.md` without the `references/` prefix that the rest of the skill uses.

## 3. Structural observations

- **The shared `varde-code-cli.md` carries sections for other skills** (Documentation, Exploration, Review, and much of Planning/Build). They restate the command catalog. varde-change needs the setup, envelope, catalog, and fallback. Collapse the per-use sections into one short "Which command" line per skill, or drop them: saves about 180 words in every skill that receives the copy.
- **The shared `varde-workflow-cli.md` carries Concept search and Concept maps**, which only varde-knowledge uses. Its Review evidence section restates review-gates and review-gate-record (and has the stale init flags). varde-change loads this file only on CLI failure. Cut Concept sections from varde-change's copy (split the manifest entry) and replace Review evidence with a pointer: saves about 330 words, and fixes defect 1 in this file.
- **`review-gate-worktree.md` duplicates build-worktree's "Review authorization" section almost bullet for bullet.** Both load on the same route (build-worktree points to it). Keep only its unique rules (bound-checkout scope, stale-source archiving, "bindings never approve") in about 80 words: saves about 165 words per isolated run.
- **The "resolved absolute `<working>`/`<knowledge>` paths, used without re-resolving" rule is written 7 times** (build-finish:33,35,52; build.md:166; orchestrate:41,82; plan.md:118; plan.md:196). Define it once as a subagent-brief rule in SKILL.md Gotchas: saves about 100 words.
- **Ownership audits are deterministic and should be scripted.** Both `build.md:181` (diff-tree vs `modifies`/`creates`/`renames`) and `build-parallel.md:51` describe the same audit. A `scripts/check-task-ownership.py <task.md> <commit>` removes about 90 words and a fragile manual comparison. Other script candidates:
  - `build.md:84` Select a plan (discover, readiness, graph, order), about 150 words.
  - The worktree-wave integrate, advance, and release sequence (`build-parallel.md:58-84`), about 200 words.
  - The `plan-decomposition.md:67` context estimate.
  - The simplify threshold in `build-finish.md:15`.
- **About 150 words of `build-posture-debug.md` Phases 1-4 are generic debugging craft** (repro preference order, determinism tips, one-variable probes, perf baselines). Keep the evidence contract, the diagnose read-only rule, unreproduced labeling (once, not three times), the `[DEBUG-…]` prefix, and the call-site seam rule.
- **Conditional loading.** `build.md` loads "Select a plan" (about 150 words) on every build, but it is needed only when no plan is named. Move it to its own section file or into status.md's selection logic. In `plan.md`, Finalize and Split (about 600 words) could load at exit criteria, but they sit on the same route, so the gain is marginal.
- **Rules repeated three or more times.**
  - Task files are not edited in parallel waves: build-execution:104,108, build-parallel:40, build.md:143.
  - Tasks inherit the plan subject: build.md:203, build-worktree:61, review-gate-plan:22, build-execution:10.
  - Tasks may be done while aggregate review is pending: build-execution:25, review-gate-plan:38.
  - UI browser rule: build-execution:93, verify:40.
  - Unattended/blocked halts: build.md:12,235, orchestrate:86.
- **SKILL.md Asking questions (about 120 words)** duplicates the user's global CLAUDE.md. Keep it only if the skill ships to users without that file. It is already short.

Estimated savings: about 984 words in score 0-1 units, plus about 970 words from shorten/merge verdicts on higher-scored units. Total about 1,950 words (14% of 13,921), before the script extractions (about 450 more words).

## 4. Totals

| Score | Units |
|---|---|
| 0 | 2 |
| 1 | 56 |
| 2 | 97 |
| 3 | 159 |
| 4 | 139 |
| 5 | 26 |
| **Total** | **479** |

Verdicts on units scored 2+: keep 349, merge 33, shorten 32, script 7.
Words in score 0-1 units: **984**.
