| # | Score | Verdict | Location | Instruction | Why | Group |
|---|---|---|---|---|---|---|
| 2 | 0 | cut | `skills/varde-change/references/build-execution.md:44` | "`plan-execution` \| Run this cycle as written." | Default; no behavior. | 0-1 |
| 13 | 0 | merge→build-execution.md:83 | `skills/varde-change/references/build-parallel.md:8` | Executors follow shared-checkout rules in build-execution | Orchestrator does not need executor rules restated. | 0-1 |
| 14 | 1 | cut | `skills/shared/references/review-gate-plan.md:21` | "The subject reads the live plan, so an unchanged approved plan covers its declared tasks." | Rationale. | 0-1 |
| 15 | 1 | cut | `skills/shared/references/review-gate-plan.md:3` | "Load before initializing a persisted plan or updating a contract/scope." | Caller (review-gates §2) already states load condition. | 0-1 |
| 16 | 1 | cut | `skills/shared/references/review-gate-record.md:29` | "The CLI rejects unknown fields, approval with unresolved choices, non-low risk without final review" | Describes CLI enforcement; CLI error teaches it. | 0-1 |
| 17 | 1 | cut | `skills/shared/references/review-gate-record.md:3` | "Load as the independent reviewer... holds every gate step a reviewer takes" | Callers state load condition. | 0-1 |
| 18 | 1 | cut | `skills/shared/references/review-gate-record.md:46` | "it binds evidence to observed files, not correctness" | Rationale. | 0-1 |
| 19 | 1 | cut | `skills/shared/references/varde-code-cli.md:55` | Planning section: nav_map then context_pack; signals not replacement | Restates catalog descriptions. | 0-1 |
| 20 | 1 | split per skill (revised) | `skills/shared/references/varde-code-cli.md:63` | Documentation section | Keep in shared source; install only to skills that use this section (MANIFEST split). | 0-1 |
| 21 | 1 | split per skill (revised) | `skills/shared/references/varde-code-cli.md:69` | Exploration section | Keep in shared source; install only to skills that use this section (MANIFEST split). | 0-1 |
| 22 | 1 | cut | `skills/shared/references/varde-code-cli.md:75` | Build section: survey modifies, get_symbol, tests_for_file, detect_changes | Restates catalog. | 0-1 |
| 23 | 1 | cut | `skills/shared/references/varde-workflow-cli.md:60` | inspect returns version/fingerprints/baseline | Describes CLI output. | 0-1 |
| 24 | 1 | cut | `skills/shared/references/varde-workflow-cli.md:62` | record needs inspected version and reviewer evidence | Restates review-gate-record. | 0-1 |
| 25 | 1 | cut | `skills/shared/references/varde-workflow-cli.md:68` | readiness planning_ready vs implementation_ready | Third copy (review-gate-plan:30, build.md:89). | 0-1 |
| 26 | 1 | cut | `skills/shared/references/varde-workflow-cli.md:70` | Outside approval checkout, follow worktree procedure | Routing exists in review-gates §2. | 0-1 |
| 27 | 1 | split per skill (revised) | `skills/shared/references/varde-workflow-cli.md:76` | Concept search: bundle/slug definition and commands | Keep in shared source; install only to skills that use this section (MANIFEST split). | 0-1 |
| 28 | 1 | split per skill (revised) | `skills/shared/references/varde-workflow-cli.md:89` | Concept maps: read index.md, regenerate | Keep in shared source; install only to skills that use this section (MANIFEST split). | 0-1 |
| 42 | 1 | cut | `skills/varde-change/assets/PLAN-TEMPLATE.md:77` | "No `## Tasks`: build writes task files; evidence lives in task Progress." | Omission is self-evident from skeleton. | 0-1 |
| 43 | 1 | cut | `skills/varde-change/references/build-execution.md:3` | "Every executor reads this before its first tool call; it is the cycle..." | Routing already sends executors here; self-description changes nothing. | 0-1 |
| 44 | 1 | cut | `skills/varde-change/references/build-execution.md:9` | "The parent passes the plan subject id and resolved memory paths." | Descriptive; the brief itself shows what was passed. | 0-1 |
| 45 | 1 | cut | `skills/varde-change/references/build-finish.md:81` | "The copies are visible follow-up work and do not block completion" | Rationale; exit-code rule already says what blocks. | 0-1 |
| 46 | 1 | cut | `skills/varde-change/references/build-micro-change.md:35` | "Edit only the approved scope and run its checks." | Default; restates gate. | 0-1 |
| 47 | 1 | cut | `skills/varde-change/references/build-micro-change.md:49` | "Final review and the complete checkpoint cover source and review edits." | Implied by scoping the artifact. | 0-1 |
| 48 | 1 | cut | `skills/varde-change/references/build-micro-change.md:50` | "Plan-owned findings use their task flow." | Implied by routing. | 0-1 |
| 49 | 1 | cut | `skills/varde-change/references/build-parallel.md:3` | "follow the section for its wave_mode" | Section headings make this obvious. | 0-1 |
| 50 | 1 | cut | `skills/varde-change/references/build-posture-debug.md:55` | Prefer failing test, diffed CLI run, harness, fuzz, manual repro | Generic debugging craft a frontier model knows. | 0-1 |
| 51 | 1 | cut | `skills/varde-change/references/build-posture-debug.md:57` | Pin time, seed RNG, isolate filesystem, freeze network | Generic determinism advice. | 0-1 |
| 52 | 1 | cut | `skills/varde-change/references/build-posture-debug.md:58` | For non-deterministic bug, raise the reproduction rate | Generic; no failure evidence. | 0-1 |
| 53 | 1 | cut | `skills/varde-change/references/build-posture-debug.md:80` | Add ranked alternatives when evidence doesn't isolate cause | Restates the hypotheses field definition (L24). | 0-1 |
| 54 | 1 | cut | `skills/varde-change/references/build-posture-debug.md:86` | Each probe tests one prediction, one variable at a time | Generic method. | 0-1 |
| 55 | 1 | cut | `skills/varde-change/references/build-posture-debug.md:88` | Performance regression: baseline before bisecting | Generic; no evidence of failure. | 0-1 |
| 56 | 1 | cut | `skills/varde-change/references/build-retry-reassessment.md:21` | Keep the caller's retry budget and blocked-task controls | Default; nothing here overrides them. | 0-1 |
| 57 | 1 | cut | `skills/varde-change/references/build-retry-reassessment.md:3` | "Load only at the stopping point specified by dispatch or debug posture." | Callers already state when to load. | 0-1 |
| 58 | 1 | cut | `skills/varde-change/references/build-worktree.md:126` | "Keep as is or Push and open PR: follow Release." | Third repetition. | 0-1 |
| 59 | 1 | cut | `skills/varde-change/references/build-worktree.md:15` | Keep as is / Push: follow Release | Repeated at L85 and L126. | 0-1 |
| 60 | 1 | cut | `skills/varde-change/references/build-worktree.md:3` | "Mechanics for editing in a separate git worktree... caller decides whether; read-only never does" | File purpose statement; callers already gate loading. | 0-1 |
| 61 | 1 | cut | `skills/varde-change/references/build.md:30` | "When interactive, ask per SKILL.md `## Asking questions`." | SKILL.md already loaded; restatement. | 0-1 |
| 62 | 1 | cut | `skills/varde-change/references/build.md:3` | "This route runs one plan in dependency order... orchestrator owns the wave loop" | Purpose statement; SKILL.md routing covers. | 0-1 |
| 63 | 1 | cut | `skills/varde-change/references/build.md:58` | "Execution loads the matching posture file automatically" | Explains executor behavior orchestrator doesn't act on. | 0-1 |
| 64 | 1 | cut | `skills/varde-change/references/orchestrate.md:3` | "Children are nested plan.md; id <group-id>/<child-slug>" | Dup of plan.md split section. | 0-1 |
| 65 | 1 | cut | `skills/varde-change/references/plan-decomposition.md:11` | "Check these even for a planned change, since ad-hoc work skipped planning" | Rationale. | 0-1 |
| 66 | 1 | cut | `skills/varde-change/references/plan.md:143` | "Internal-only changes skip this." | Implied by the "if consumers" condition. | 0-1 |
| 67 | 1 | cut | `skills/varde-change/references/plan.md:14` | "Resume. Continue per Later turns." | Obvious flow. | 0-1 |
| 68 | 1 | cut | `skills/varde-change/references/plan.md:20` | "Use this file for planning." | No behavior. | 0-1 |
| 69 | 1 | cut | `skills/varde-change/references/plan.md:228` | "Boundaries come from the full spec, not a pre-spec guess." | Rationale. | 0-1 |
| 70 | 1 | cut | `skills/varde-change/references/plan.md:3` | "Planning grows one plan.md defining scope, design, and acceptance criteria." | Purpose statement; template shows it. | 0-1 |
| 71 | 1 | cut | `skills/varde-change/references/plan.md:44` | Later turns: follow growth loop until exit then Finalize | Restates section structure. | 0-1 |
| 72 | 1 | cut | `skills/varde-change/references/plan.md:51` | "The first turn seeds plan.md; run this loop every later turn to sharpen it." | Restates L44. | 0-1 |
| 73 | 1 | cut | `skills/varde-change/references/verify.md:15` | "Incomplete plans still receive partial verification." | Default behavior. | 0-1 |
| 123 | 1 | merge→review-gates.md:118 | `skills/shared/references/review-gate-record.md:42` | "Implementation review runs at completion regardless of this field or tier." | Stated in review-gates §5 and review-gate-worktree. | 0-1 |
| 127 | 1 | merge→plan-decomposition.md:48 | `skills/varde-change/assets/TASK-TEMPLATE.md:12` | YAML comments restating ownership rules | Duplicate of plan-decomposition §3; one place suffices. | 0-1 |
| 128 | 1 | merge→review-gates.md | `skills/varde-change/references/build-finish.md:35` | Tell reviewer to use paths without re-resolving | Repeated in 5+ places; one shared subagent-brief rule suffices. | 0-1 |
| 129 | 1 | merge→SKILL.md:28 | `skills/varde-change/references/build-micro-change.md:3` | Task under persisted plan uses build-execution; dependent outcomes go to build.md | Duplicates SKILL.md routing table. | 0-1 |
| 130 | 1 | merge→build-posture-debug.md:60 | `skills/varde-change/references/build-posture-debug.md:72` | Without loop, state how trace supports symptom and limits | Third statement of unreproduced rule. | 0-1 |
| 131 | 1 | merge→review-gates.md | `skills/varde-change/references/orchestrate.md:41` | Pass explicit paths and resolved <working>/<knowledge> without re-resolving | Repeated brief rule. | 0-1 |
| 132 | 1 | merge→review-gates.md | `skills/varde-change/references/plan.md:118` | Research subagents get resolved paths, no re-resolving | Repeated brief rule. | 0-1 |
| 133 | 1 | merge→plan.md:133 | `skills/varde-change/references/plan.md:55` | Run External interface check when consumers touched | Section itself states its trigger. | 0-1 |
| 154 | 1 | shorten | `skills/varde-change/references/build-finish.md:130` | "Keep as is: leave the checkout, branch, and worktree in place." | Option label self-explains; keep label only. | 0-1 |
| 165 | 2 | merge→review-gates.md:81 | `skills/shared/references/review-gate-plan.md:15` | Pass reviewer subject id, repository, memory paths | Subset of review-gates §3 list. | A: merge within skill |
| 166 | 2 | merge→build-execution.md:25 | `skills/shared/references/review-gate-plan.md:38` | Tasks may be done while aggregate review pending | Duplicate of build-execution:25. | A: merge within skill |
| 167 | 2 | merge→build-finish.md:9 | `skills/shared/references/review-gate-plan.md:40` | Finish source/docs/spec/changelog/verification before final review | Duplicate of build-finish §1 and review-gates §5.1. | A: merge within skill |
| 168 | 2 | merge→review-gates.md:114 | `skills/shared/references/review-gate-plan.md:52` | Material changes need fresh independent verdict | Stated in review-gates §4 and micro-change. | A: merge within skill |
| 169 | 2 | reverse merge (revised) | `skills/shared/references/review-gate-worktree.md:24` | Abandonment: abandon-worktree; keeps source; can't resume or conclude | Shared file installs into 5 skills; cut the duplicate from build-worktree instead. | A: merge within skill |
| 171 | 2 | merge→build-finish.md:86 | `skills/shared/references/varde-workflow-cli.md:34` | Run conclude after criteria/specs pass; conclusion-* follow-ups | Owned by build-finish §6. | A: merge within skill |
| 172 | 2 | merge→review-gates.md:63 | `skills/shared/references/varde-workflow-cli.md:39` | Review init commands (without --tier-evidence) | Duplicates review-gates with a stale flag set. | A: merge within skill |
| 173 | 2 | merge→review-gate-record.md:9 | `skills/shared/references/varde-workflow-cli.md:48` | init returns subject_id/version; reviewer inspects and records | Owned by review-gate-record. | A: merge within skill |
| 174 | 2 | merge→review-gates.md:103 | `skills/shared/references/varde-workflow-cli.md:52` | inspect/record/check/contract/expand command block | Each command already given where used. | A: merge within skill |
| 175 | 2 | merge→review-gate-plan.md:49 | `skills/shared/references/varde-workflow-cli.md:64` | contract/expand may invalidate approval | Stated with more precision in review-gate-plan. | A: merge within skill |
| 183 | 2 | merge→user CLAUDE.md | `skills/varde-change/SKILL.md:39` | One topic per turn; up to three facets; wait | Same rule in user's global CLAUDE.md; needed only for other users. | A: merge within skill |
| 184 | 2 | merge→user CLAUDE.md | `skills/varde-change/SKILL.md:43` | Recommend one option with one-sentence reason | Same as global CLAUDE.md. | A: merge within skill |
| 185 | 2 | merge→build-execution.md:104 | `skills/varde-change/references/build-execution.md:108` | "In a parallel wave, do not edit the task file" | Third statement of the same rule (L104, build-parallel:40). | A: merge within skill |
| 186 | 2 | merge→review-gates.md | `skills/varde-change/references/build-finish.md:67` | Fix plans pass pre-edit gate; changed covered files need fresh full-subject record | Gate rule owned by review-gates. | A: merge within skill |
| 187 | 2 | merge→build-posture-debug.md:60 | `skills/varde-change/references/build-posture-debug.md:39` | Label unreproduced symptoms **unreproduced**, state limits | Stated again in Phase 1 and Phase 2 step 3. | A: merge within skill |
| 188 | 2 | merge→build.md:72 | `skills/varde-change/references/build.md:126` | Repeat until done/blocked/empty; remaining todo as blocked_by_dep | Duplicates step 5.4 wording. | A: merge within skill |
| 189 | 2 | merge→build.md:224 | `skills/varde-change/references/orchestrate.md:98` | Stop when statuses and commits disagree | Same rule as build Resume check. | A: merge within skill |
| 221 | 2 | shorten | `skills/shared/references/review-gate-record.md:18` | record_template pre-fills listed fields | Describes CLI output internals; "fill remaining placeholders" suffices. | B: cut prose restating script/CLI; may move a needed fix hint into that script message |
| 222 | 2 | shorten | `skills/shared/references/review-gates.md:71` | Missing tier evidence, open_choices, shared contracts default to high | CLI behavior description; partly useful. | B: cut prose restating script/CLI; may move a needed fix hint into that script message |
| 223 | 2 | shorten | `skills/shared/references/varde-code-cli.md:27` | Command catalog (14 entries) | --help lists commands; keep names + key caveats only. | B: cut prose restating script/CLI; may move a needed fix hint into that script message |
| 224 | 2 | shorten | `skills/shared/references/varde-workflow-cli.md:28` | readiness reports actions/blockers | Describes output. | B: cut prose restating script/CLI; may move a needed fix hint into that script message |
| 225 | 2 | shorten | `skills/shared/references/varde-workflow-cli.md:4` | CLI purpose; Write/Edit for artifacts; review commands require CLI | Last clause is the value; duplicated at L96. | A: merge within skill |
| 231 | 2 | shorten | `skills/varde-change/references/build-execution.md:25` | Task may be done while aggregate review pending; not plan completion | Guards premature "plan done" claims; one clause suffices. | C: shorten to one clause, keep direction |
| 232 | 2 | shorten | `skills/varde-change/references/build-execution.md:52` | Benign drift: note and proceed; invalidating drift: blocker | Reasonable default; examples in parentheses cuttable. | C: shorten to one clause, keep direction |
| 233 | 2 | shorten | `skills/varde-change/references/build-execution.md:62` | Profile table tdd/regression/characterization/smoke/not-applicable | Names are template vocabulary; methods are model defaults. | C: shorten to one clause, keep direction |
| 234 | 2 | shorten | `skills/varde-change/references/build-execution.md:81` | Check shared surface dependents first (varde-code or grep) | Default-ish; also owned by plan.md External interface check. | C: shorten to one clause, keep direction |
| 235 | 2 | shorten; keep "no review folder" | `skills/varde-change/references/build-finish.md:46` | Agent-document findings: bounded change, record in Progress, no review folder | Edge route; could point to review-gates. | D (user decided) |
| 236 | 2 | shorten | `skills/varde-change/references/build-finish.md:60` | Fix: bounded build task with finding_ids, solution, decision evidence | Restates varde-review fix Parent workflow it cites. | B: cut prose restating script/CLI; may move a needed fix hint into that script message |
| 237 | 2 | shorten | `skills/varde-change/references/build-finish.md:72` | Rerun only AC checks covering fix-changed files; unconfirmed blocks | Optimization detail; "rerun affected AC checks" suffices. | C: shorten to one clause, keep direction |
| 238 | 2 | shorten | `skills/varde-change/references/build-posture-debug.md:21` | Field definitions: reproduction, hypotheses, experiments, cause, verification | Field names suffice; definitions are mostly self-evident. | C: shorten to one clause, keep direction |
| 239 | 2 | shorten | `skills/varde-change/references/build-posture-debug.md:34` | diagnose may leave cause uncertain; state evidence limit | Overlaps L39 unreproduced labeling. | C: shorten to one clause, keep direction |
| 240 | 2 | shorten | `skills/varde-change/references/build-posture-debug.md:70` | Minimize to smallest red scenario, rerun after each cut | Good craft; one clause. | C: shorten to one clause, keep direction |
| 241 | 2 | shorten | `skills/varde-change/references/build-posture-debug.md:77` | State falsifiable hypothesis before testing, with template sentence | Useful; template sentence cuttable. | C: shorten to one clause, keep direction |
| 242 | 2 | shorten | `skills/varde-change/references/build-posture-refactor.md:15` | Target selection order: explicit, review findings, structural goal, else ask | Order mostly default; "else ask" is the value. | C: shorten to one clause, keep direction |
| 243 | 2 | shorten | `skills/varde-change/references/build-posture-refactor.md:64` | Verify with approved checks; full suite only for new failures/concerns | Long; condense to one rule. | C: shorten to one clause, keep direction |
| 244 | 2 | shorten | `skills/varde-change/references/build-retry-reassessment.md:24` | Revised plan returns to pre-edit gate; no routine review cycle | Gate rule owned by review-gates. | A: merge within skill |
| 245 | 2 | shorten | `skills/varde-change/references/build-worktree.md:70` | Binding authorizes only start/resume; renewed approval never revives stale worker | CLI enforces this; prose is explanation. | B: cut prose restating script/CLI; may move a needed fix hint into that script message |
| 246 | 2 | shorten | `skills/varde-change/references/build.md:35` | Default to current checkout; stage only task-owned paths | Default; staging half dup of build-execution. | C: shorten to one clause, keep direction |
| 247 | 2 | shorten; keep all four steps | `skills/varde-change/references/plan.md:214` | Plan id change: rename, validate, rerun review, replace subject id | Rare edge case; long. | D (user decided) |
| 248 | 2 | shorten | `skills/varde-change/references/plan.md:83` | Design It Twice: constraints, two alternatives, recommend, log loser | Useful technique; could be one line. | C: shorten to one clause, keep direction |
| 249 | 2 | shorten | `skills/varde-change/references/status.md:10` | Handoffs table: open, newest 5, columns, empty message | Format detail; model would do similar. | C: shorten to one clause, keep direction |
