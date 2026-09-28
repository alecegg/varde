# Adversarial audit, pass 2: varde skills (2026-09-24)

Scope: every file under `skills/`, audited as it stands after commit `7afcac2`, which applied items 1–168 of the first pass. The scope covers all seven skills (SKILL.md, references, assets, scripts, evals) and the shared infrastructure (`README.md`, `install.sh`, `check-refs.sh`, `tests/`, `eval-tools/`). Three auditors each took one partition. Each checked CLI claims against the installed `varde-workflow`, `varde-code` and `docwatch` binaries and scratch repos, and checked the first-pass report so it would not reopen decisions already made. I spot-checked the headline correctness claims against source; see "Verification" below.

## How to read this

Every item was tested against four questions:

1. Is it worth doing at all, or worth handing to an agent? Would a capable model do it unprompted? Is the time it costs at run time worth it?
2. Does it earn its token cost at the frequency it loads?
3. Could the same behaviour be stated accurately in fewer words? If so, that counts as a defect.
4. Is it correct?

**Ranking.** Item **1** is the strongest candidate to cut. Numbers rise toward the **most valuable, non-removable** items at the bottom. Each auditor gave every item a cut-score from 0 to 100. Ties are broken by verdict (CUT, then MERGE, COMPRESS, FIX, KEEP) and then by words saved. A correctness defect is ranked with the feature it breaks. If the broken feature is worth keeping, it ranks low with verdict FIX: keep it and fix it. If the feature is not worth having, it ranks high: cut it. **So several of the most urgent fixes sit deep in the list.** The "Fix first" section pulls them out.

**Load column.** `always` means the frontmatter description, loaded every session. `trigger` is the SKILL.md body. `mode` is a routed reference. `rare` is a rarely routed reference. `—` means the file is not read by an agent; it costs only maintenance or CI time.

**Words** were measured with `wc -w`; tokens ≈ words × 1.35. **IDs:** `C` = varde-change, `R` = varde-review/docs/agent-doc-authoring, `K`/`E`/`P` = knowledge/explore/prototype, `I` = shared infrastructure, `D` = descriptions.

## Baseline and projection

| Partition | Agent-read words now | Projected | Change |
|---|---:|---:|---:|
| varde-change | 9,024 | ~8,100 | −~930 |
| varde-review + varde-docs + agent-doc-authoring | 8,672 | ~7,580 | −~1,090 |
| knowledge + explore + prototype + README/eval docs | 5,936 | ~5,120 | −~820 |
| **All agent-read prose** | **~23,630 (~31.9k tok)** | **~20,800** | **−~2,830 (~12%, ~3.8k tok)** |
| Descriptions (always loaded, 7 skills) | 172 | ~162 | −10 per session |

The first pass cut about 29%. This pass saves less (about 12%), and **its main finding is correctness, not size**: 51 FIX rows. Several are regressions from the first pass or agreed changes that never landed. A good share of the remaining savings is in **load per run**, which a per-file word count understates: files that get read on runs that never use them.

## Fix first (correctness, ordered by harm)

These are ranked low in the main list because the features they break are worth keeping. They are the urgent work.

| Rank | IDs | Defect |
|---:|---|---|
| 3, 4 | K1, C2 | **Following the docs corrupts notes and plans.** Both `varde-workflow-cli.md` copies (knowledge and change) point to `inspect`/`migrate`. `inspect` flags every valid OKF note and every template-made plan as `migration_required`, and `migrate --apply` rewrites them into workflow-artifact envelopes. Cut both sections. |
| 161 | I17 | **Regression from 7afcac2.** `eval-tools/run-evals.sh` calls `fail()` at lines 169–203, but `def fail` was deleted, so every Codex error path raises a NameError and the reason is lost. Restore it and assert on the message in `trigger-evals.sh`. *(Verified.)* |
| 194, 196, 199 | C54, C60, C61 | **The plan-graph model is wrong.** Discovery and status glob only one directory level, so nested companion plans, which build-plan-finish creates and then waits on, are never found. Orchestrate orders children from one child's `graph`, so unrelated siblings are left out. The `group/child` form of `depends_on` fails with `dependency_missing`. |
| 191, 197, 195 | C56, C57, C55 | **Resume and retry.** A task left `in_progress` by a crash is never re-dispatched: the wave resolver only picks up `todo` *(verified)*. Moving `todo→done` directly is illegal, and nothing guarantees the task passes through `in_progress` first. build-dispatch says a second failure halts the run, but build-plan-run offers Retry/Skip/Abort. |
| 9 | R6 | **spec-plan incremental scoping doesn't work.** `map_file` returns graph-cluster nodes, not spec domains. Replace steps 1–2 with "recompute provenance + git-diff for files that no spec's `sources` list includes". Cut the dead "Spec scoping" section in varde-docs `varde-code.md`. |
| 192, 157 | C58, C48 | **Parallel-wave safety.** The plan folder isn't tracked by default, so a task's worktree has no copy of its task file, and nothing tells the executor where the real one is. `worktree-merge.sh` runs `add -A` and commits any leftovers under a placeholder message before merging, even if the task never passed its checks *(verified, lines 53–54)*. |
| 2, 128, 169 | R1, R50, R73 | **The reference is loaded by the wrong mode.** Refresh mode loads it but can use none of it. Spec mode needs it but never loads it, and inline spec generation never loads `spec-format.md` either. |
| 201, 126 | I1, I13 | **Broken cross-references.** `skills/README.md:74-78` says every session boundary writes a handoff, which contradicts `reflect.md`. `eval-tools/README.md:7-9` sends query-set authoring to `optimizing-descriptions.md`, which no longer covers it. |
| 228, 177, 140, 129/141/149 | R87, R75, R56, R53/R58/R63 | **Evals that contradict the skill.** Review eval 2 contradicts `varde-review/SKILL.md:8`. Review eval 1 hard-codes a different folder path than `report-format.md`. The doc-authoring assertions grade terms from the deleted `vocabulary.md`. The docs evals still assert `docs:v1` and worktree behaviour. |

## Highest-value size and load changes

1. **Finish what the first pass agreed but didn't land** (#1 C1, #32 C9, the doc-authoring leftovers #156/#44/#136, explore fixtures #83, judge input #96). The duplicate "Routing unknowns" paragraph still sits next to its replacement and loads on every plan turn. The 65-word micro-change rewrite was never applied. About −500 words, plus evals that can actually be measured.
2. **Stop loading files a run doesn't use** (C53, C33, C8). The orchestrator reads `build-execution.md` (517 words) but never executes tasks. Every unattended orchestrate child reads `interview.md` but never asks questions. `build.md` is a three-row router that costs a Read on every build and every executor dispatch; fold it into the SKILL.md table.
3. **Say each rule once.** "The root is a run sheet, references are one hop away" appears four times in doc-authoring (#5 R4). "When to load varde-code" appears three times in varde-explore (#84 E2, E6–E10: −145 words per explain run). Commit-per-task appears three times in varde-change (#11 C4).
4. **Restructure fix-pass** (#42 R20, #175 R77). Merge step 4 with the gate's closing paragraphs, which repeat it. Make "confirm the defect is gone" a precondition of step 10, before the disposition is set to `fix`. About −150 words.
5. **Delete tests that only check prose** (#10 C3). `grep -Fq 'Stop until the user selects one'` pins wording, not behaviour, and makes every compression fail CI.

## Verification

I checked these against source myself: I17 (`def fail` is missing; `fail(` is called at lines 169–203), K1 (the section is present at `varde-knowledge/references/varde-workflow-cli.md:28`), C56 (`resolve-execution-wave.py:127,132` treats only `todo` as ready), C48 (`worktree-merge.sh:53-54`), R6 (`spec-plan.md:16` uses `map_file`; per `varde-code --help` it returns "persisted node info"), and the review eval contradiction (`varde-review/SKILL.md:8`). The auditors verified the other CLI claims by running `validate`, `graph`, `readiness`, `transition`, `conclude` and `migrate` in scratch repos; I did not re-run those. The auditors could not read the installed descriptions under `~/.pi/agent/skills` because the sandbox denied access. The Claude, Codex and opencode copies match the repo.

---

## Inventory, from cut-first to most valuable

### Band A — cut or merge (score ≥70)

| # | ID | Item | Where | Load | Words | Verdict | Score | Case against → fix | Saved |
|---:|---|---|---|---|---:|---|---:|---|---:|
| 1 | C1 | Duplicate "Routing unknowns" paragraph | references/plan-grow-doc.md:13-19 | mode (every plan turn) | 78 | CUT | 92 | Prior #55 added the compressed rule (:21-26) but left the old version (:13-19) in place, so the same routing rule appears twice with different wording ("anything guessed" vs "confident **and** contained → Assumptions"). Delete :13-19 and keep :21-26. | 75 |
| 2 | R1 | varde-docs `varde-code.md` "Spec scoping" section | varde-docs/references/varde-code.md:16-23 | mode (via refresh only) | 40 | CUT | 88 | Dead where it is loaded and missing where it would matter: only refresh.md routes to this file, and refresh does no spec scoping. spec.md and spec-plan.md, the spec path, never point to it. Its `map_file` bucketing is also wrong (see spec-plan row). Delete the section. | 40 |
| 3 | K1 | knowledge CLI ref "Legacy artifacts" + "legacy migration" in preamble | varde-knowledge/references/varde-workflow-cli.md:4,28-31 | mode | 18 | CUT | 88 | **Wrong, and harmful if followed.** `inspect --json` returns `legacy: true, migration_required: true` for *every* valid OKF note (verified on memory-bank/knowledge/reference/varde-init.md). `migrate` then rewrites the note into a workflow-artifact envelope (`artifact_type`, `id: legacy-…`, `provenance`, `relationships`). It is plan-artifact machinery, not note upgrade. Prior #66 kept it as "rare", but that decision did not know this. Delete the section and the word "legacy migration" at :4. | 18 |
| 4 | C2 | `inspect`/`migrate` line in the CLI reference | references/varde-workflow-cli.md:44-45 | mode | 30 | CUT (FIX) | 85 | **Misleading.** A plan written from PLAN-TEMPLATE comes back from `validate --json` as `legacy: true, migration_required: true` (verified). So this line invites an agent to "migrate" every plan it writes, which adds `id: legacy-<hash>`, `provenance`, and other fields. `transition` and `conclude` work fine on unmigrated plans. Prior #95 decided to cut this line, but the cut was never applied. Delete it. If anything stays, make it "Ignore `migration_required`; never migrate unless asked." | 30 |
| 5 | R4 | specification.md "Loading and references" | varde-agent-doc-authoring/references/specification.md:15-17 | rare | 19 | CUT | 85 | The fourth copy of "root is a run sheet, references one hop": authoring.md:28-32, reviewing.md:39-40, and workflow-skills.md:24-26 carry it too. A frontmatter spec file is the wrong home. Delete it; the 500-line soft budget is already checked by the validator (BODY_LINE_BUDGET). | 22 |
| 6 | R2 | optimizing-descriptions.md preamble | varde-agent-doc-authoring/references/optimizing-descriptions.md:3-4 | rare | 21 | CUT | 85 | Background the model already knows ("vague descriptions miss tasks; broad ones over-trigger"). Delete it. | 21 |
| 7 | R3 | authoring.md "Write skill metadata and descriptions" | varde-agent-doc-authoring/references/authoring.md:46-49 | mode | 15 | CUT | 85 | Restates the SKILL.md routing table (row 15 already routes frontmatter to specification.md) and creates the reference chain that specification.md:17 forbids. Delete it. | 19 |
| 8 | R5 | workflow-skills.md opener | varde-agent-doc-authoring/references/workflow-skills.md:3 | rare | 7 | CUT | 85 | "Read this for work with ordered steps" restates the SKILL.md table's load condition. Delete it. | 7 |
| 9 | R6 | spec-plan incremental steps 1-2 (`detect_changes` + `map_file`/`clusters` to find a file's domain) | varde-docs/references/spec-plan.md:8-23 | mode | 103 | FIX | 82 | **Incorrect.** `map_file` returns `community_id`/`community_label` (checked: `{"churn":3,"community_id":114,...}`). Those are graph clusters, not spec domains, so step 2 cannot resolve a spec domain. Step 3 (recompute every document's provenance) already catches every stale existing doc, which makes steps 1-2 redundant. The one thing they add, spotting new files that belong to no domain, needs only git. Replace the section with: "Recompute every document's provenance; a mismatch is stale. For missing domains, list `git diff --name-only <source_commit>..HEAD` plus untracked files; a file in no document's `sources` is a candidate missing domain. Diff from `source_commit`, never `source_hash`; an unresolvable watermark means a Full scan." This also drops the spec path's only need for varde-code during planning. | 50 |
| 10 | C3 | Prose-grep and eval-shape snapshot checks | tests/change-output-eval-fixtures.sh:72-77, 78-82, 265-275 | — | ~120 | CUT | 80 | `grep -Fq 'Stop until the user selects one'` / `'stop immediately'` check prose wording, and the `jq` checks require eval 7 to have exactly 4 assertions and eval 8 to have exactly 5. These are the prose-grep and snapshot checks that prior #11 decided to cut, and they survived. The comment at :78-82 also cites the "consolidated-workflows check", which #82 deleted. Keep only the seeded-fixture tests and the state guard. | ~120 (—) |
| 11 | C4 | "Commit-per-task" section | references/build-dispatch.md:50-53 | mode | 22 | CUT | 80 | Restates build-plan-run.md:10-12 (one commit per task) and build-execution.md:66-68. | 22 |
| 12 | R7 | doc-authoring SKILL.md preamble | varde-agent-doc-authoring/SKILL.md:8-9 | trigger | 20 | CUT | 80 | "Grounded, procedural, lean" and "read only the detail needed" are slogans the table and references operationalize. Delete them. | 20 |
| 13 | R9 | spec.md step 1 "Work in place" | varde-docs/references/spec.md:9-10 | mode | 17 | CUT | 80 | "Write … with Write/Edit. Read and grep existing specs directly" is the default. Renumber the steps. | 17 |
| 14 | R8 | varde-docs SKILL.md "Read only the reference… Then read its required supporting files" | varde-docs/SKILL.md:15-16 | trigger | 13 | CUT | 80 | The prior audit (#148) removed this progressive-loading default from varde-review SKILL.md but left it here, so the two skills now disagree. Delete it. | 13 |
| 15 | R10 | report.md closing paragraph | varde-review/references/report.md:65-67 | mode | 30 | CUT | 75 | "Report only" duplicates SKILL.md:8, the eval, and step 8. "Repository-relative paths" duplicates report-format.md:77. "Report a hard error and stop" is the default. Delete all three. | 30 |
| 16 | C5 | "Answer a readiness question" route | SKILL.md:22; references/plan-start.md:31-32 | trigger + mode | 25 | CUT | 75 | "Readiness sections" exist nowhere (PLAN-TEMPLATE has none). The phrase also collides with status.md's `varde-workflow readiness`. A readiness question about an existing plan belongs to status or verify, not to starting a new plan. Delete both mentions. | 25 |
| 17 | C6 | Resume-evidence restatement | references/build-plan-run.md:43-44 | mode | 13 | CUT | 75 | "Report inconsistent commit or Progress evidence rather than inferring an outcome" repeats build-dispatch.md:71-73, which this same file names as the owner of the resume check. | 13 |
| 18 | R11 | scan.md parenthetical on rules_list | varde-review/references/scan.md:14 | mode | 10 | CUT | 75 | "(Triage reads rule definitions through `rules_list`, not this reference.)" duplicates step 4's second bullet. Delete it. | 10 |
| 19 | C7 | `build-research-task.md` as its own file | references/build-research-task.md | rare | 122 | MERGE | 72 | One more hop for three default-ish steps. Fold it into build-execution "Choose the task kind": "`kind: research`: write the `creates` doc from primary sources outside the repo, citing each claim (URL, spec section, file:line); a decision ends with one recommendation. Then run Completion." Delete the file and update the TASK-TEMPLATE comment. | ~75 + 1 hop |
| 20 | R12 | refresh.md step 1 routes to varde-docs `varde-code.md` | varde-docs/references/refresh.md:13-15 | mode | 22 | FIX | 72 | Loading that 229-word file gives a refresh no usable command. It covers spec scoping, `get_symbol`, and Acceptance Criteria tests, but not `context_pack`, the mode that actually maps a doc's subject to source. "Write changes with Write/Edit" is the default. Replace with: "Many `docs/` files and `varde-code` on PATH → `varde-code context_pack --json '{\"repoRoot\":…,\"query\":\"<doc subject>\"}'` maps each doc to source." Move the pointer to spec.md (row: spec path never loads varde-code.md). | 5 |
| 21 | C11 | Breakdown-pause duplicate | references/build-plan.md:39-41 vs build-decomposition.md:69-71 | mode | 22 | CUT | 70 | The rule "present the breakdown once when interactive; unattended skips the pause" appears in both files. Keep it in decomposition. | 22 |
| 22 | C10 | Refactor-posture duplicate | references/build-plan.md:10 and :42-43 | mode | 20 | CUT | 70 | "A request to refactor a named target fixes the refactor posture for the whole run" repeats the table row at :10. Delete :42-43. | 20 |
| 23 | R13 | refresh.md "Inputs" section | varde-docs/references/refresh.md:6-9 | mode | 20 | CUT | 70 | `repoRoot` is implicit and `docPath` is already handled in step 2 ("or only `docPath`"). Delete the section. | 20 |
| 24 | R16 | reviewing.md Token economy harness-loading caveat | varde-agent-doc-authoring/references/reviewing.md:62-63 | mode | 15 | CUT | 70 | "Confirm harness loading … do not assume frontmatter is always loaded" duplicates authoring.md:24-26. Prior #7 kept only the authoring copy. A review loads both. Delete the second sentence. | 15 |
| 25 | R15 | report-format "An `auto-fix` finding still records its disposition after the automated pass" | varde-review/references/report-format.md:63-64 | mode | 11 | CUT | 70 | Report mode never acts on it, and fix-pass.md step 10 already sets `Disposition: fix`. Delete it. | 11 |
| 26 | C12 | interview.md opener | references/interview.md:3 | mode | 9 | CUT | 70 | "Shared rules for skills that ask the user questions": only this skill reads its own copy. | 9 |
| 27 | R17 | simplify "Work beyond the listed ranges is reported as unapplied" | varde-review/references/simplify.md:10-11 | mode (every build task) | 9 | CUT | 70 | Duplicates step 6 ("List worthwhile improvements outside scope as unapplied") and step 3 ("edit only inside them"). Delete it. | 9 |
| 28 | R18 | review `varde-code.md` pointer to scan.md | varde-review/references/varde-code.md:31 | mode | 9 | CUT | 70 | SKILL.md already routes scan triage to scan.md, so this pointer only adds a reference chain. Delete it. | 9 |
| 29 | E6 | Workflow step 1 "Resolve the shape with the table above" | explain.md:24 | mode | 8 | CUT | 70 | The preceding section *is* that step. Renumber. | 8 |
| 30 | R14 | docs eval 2 assertion "No docs:v1 or other bookkeeping marker" | varde-docs/evals/evals.json (id 2) | — | 12 | CUT | 70 | Tests the absence of a retired feature. No current reference mentions `docs:v1`. Drop the assertion. | 0 |
| 31 | C8 | `build.md` as a router file | references/build.md (all) | mode (every build) | 84 | MERGE | 70 | A three-row table plus prose. Lines 11-13 restate micro-change's own gate. Replace SKILL.md:24 with three rows: micro-change → build-micro-change.md; "one task file assigned by an orchestrator (executor)" → build-execution.md (put it first so "bounded" in the executor's own description doesn't match micro); plan / ad-hoc / refactor / spike → build-plan.md. Move `execution=<auto\|serial\|inline>` to build-plan.md step 3. Saves one Read on every build, including every executor dispatch. | ~50 + 1 hop per build |
| 32 | C9 | `build-micro-change.md` verbosity | references/build-micro-change.md:1-23 | mode | 159 | COMPRESS | 70 | Prior #15 (65-word rewrite) was not applied. Steps 1, 4, 6 and the six-line varde-code paragraph are default behaviour. Replacement: "Only for one concrete behavior whose check result you can state before editing; otherwise use `build-plan.md`. Inspect the target and its narrowest check together (one `varde-code batch` for symbols + covering tests when several files matter). State the check and expected result, edit only that behavior, run it, compare, and report files and evidence. No plans, tasks, worktrees, handoffs, or commits unless asked." | 95 |
| 33 | C13 | Interview restatement in the growth loop | references/plan-grow-doc.md:73-75 | mode (every plan turn) | 27 | COMPRESS | 70 | The parenthetical "(one topic per turn, with a recommendation)" restates interview.md. Replacement: "**Ask** the highest-value Open Question per `references/interview.md`, solution-shape questions before spelling ones." | 12 |

### Band B — strong compress/cut candidates (50–69)

| # | ID | Item | Where | Load | Words | Verdict | Score | Case against → fix | Saved |
|---:|---|---|---|---|---:|---|---:|---|---:|
| 34 | R19 | optimizing-descriptions.md as a separate file | varde-agent-doc-authoring/references/optimizing-descriptions.md; SKILL.md:17 | rare | 100 | MERGE | 68 | About 55 useful words: the outcome verbs, `Not for <sibling>`, and one double-quoted line. It points to specification.md for the length limit anyway. Fold it into specification.md's `description` row plus a "Description wording" subsection, delete the file, and route "Improve triggering" to specification.md. | 45 |
| 35 | E8 | explore copy of varde-code.md "When to use it" | varde-explore/references/varde-code.md:11-14 | rare | 26 | CUT | 65 | Restates SKILL.md:17-18 and explain.md:25-26, and every reader arrives already routed. The section is not pinned by vendored-copies. | 26 |
| 36 | C14 | build-plan Gotchas | references/build-plan.md:63-64 | mode | 25 | CUT | 65 | "Task files follow TASK-TEMPLATE" repeats decomposition:73. "There is no `index.md`" is sediment from a retired layout. Keep only the plan-wide vs task blocker bullet (:65-66). | 25 |
| 37 | R21 | fix-pass "If verification fails, continue… Report each result" | varde-review/references/fix-pass.md:32-33 | mode | 17 | CUT | 65 | Step 9 already handles failure, and fix.md Closing reports the counts. Delete it. | 17 |
| 38 | C16 | `map_path` in the command catalogue | references/varde-code.md:30 | mode | 15 | CUT | 65 | No varde-change procedure uses it (grep: only this file). The other entries are each cited by a procedure. | 15 |
| 39 | P4 | Workflow step 1 "Ask what the user wants to prototype, unless a plan already supplies it" | SKILL.md:28-29 | trigger | 13 | CUT | 65 | Default behaviour. Keep the slug, the storage path, and "ask only if that path exists". | 13 |
| 40 | R22 | docs eval 1 assertion "creates no worktree" | varde-docs/evals/evals.json (id 1) | — | 10 | CUT | 65 | refresh.md says nothing about worktrees, so the assertion checks default behavior. Drop it (and "in the current checkout" in expected_output). | 0 |
| 41 | C15 | `build-edge-cases.md` as its own file | references/build-edge-cases.md; build-decomposition.md:7-15 | rare | 134 + 66 | MERGE | 65 | Decomposition already spends 66 words stating the triggers before routing to a 134-word file. Inline both sections under the trigger bullets (wide refactor: expand, then N migrate batches, then contract, with an integrate task if batches can't stay green; deletion: the three greps). About 130 words total, one fewer hop. | ~70 + 1 hop |
| 42 | R20 | fix-pass step 4 vs the gate's trailing paragraphs | varde-review/references/fix-pass.md:14-17,64-70 | mode | 110 | MERGE | 65 | The on-reject action is stated twice: step 4 says "send to human pass, relabel, blank, record reason", and :64-67 says "send to human pass, add Escalated, values…". The value list also repeats report-format.md:71. :69-70 repeats :4-5. Step 4 becomes: "In build mode, run the gate below. On rejection, relabel `triage`, add `**Escalated:**` after `Location` (values: report-format), leave `Disposition: blank`, and move on." Delete :64-70. | 70 |
| 43 | K2 | knowledge CLI ref preamble | varde-knowledge/references/varde-workflow-cli.md:1-7 | mode | 57 | COMPRESS | 62 | The Grep fallback and "name the lost capability once" appear three times in one note run: here, in note.md:6-9, and in the pinned Fallback rule at :37-38. Replace with: "Optional; adds ranked search and lint over the same files. Write notes with Write/Edit whether or not it is installed." | 37 |
| 44 | R24 | authoring.md scripts paragraph | varde-agent-doc-authoring/references/authoring.md:34-39 | mode | 60 | COMPRESS | 62 | Merging using-scripts.md (#8) brought back the generic CLI hygiene (`--help`, stdout/stderr, exit codes, dry run) that #8 had judged default. Replace with: "Bundle a script only to replace repeated parsing or validation; name its exact skill-root-relative invocation where it runs, and pin dependencies inline (PEP 723)." | 32 |
| 45 | R23 | doc-authoring SKILL table: "Improve triggering" row | varde-agent-doc-authoring/SKILL.md:17 | trigger | 16 | FIX | 62 | Prior #156 (route straight to the description reference, drop repeated `references/` prefixes) was **not applied**. The row still loads authoring.md (385 words) first. "to check trigger overlap" also mislabels the target file, which has no overlap procedure. Row: `\| Improve triggering \| specification.md (after the merge above) \| — \|`. Strip `references/` from all seven cells. | 10 |
| 46 | C19 | Duplicated plan-start "Later turns" pointers | references/plan-start.md:36-39 | mode | 25 | CUT | 60 | "Continuing without asking once the final completeness check is confirmed" repeats plan-fundamentals Finalize 4. "Read varde-code.md before using its planning operations" repeats plan-grow-doc:7. Keep "Follow plan-grow-doc every turn until its exit criteria pass, then plan-fundamentals Finalize." | 25 |
| 47 | C17 | Repeated "outside repo = ignored / plain mv" asides | references/build-plan.md:30-31; plan-fundamentals.md:27-28 | mode | 20 | CUT | 60 | SKILL.md:33-34 already says a location outside the repo skips git ops and uses plain file ops. Drop the asides. | 20 |
| 48 | C18 | `command -v` preamble in the CLI reference | references/varde-workflow-cli.md:3-7 | mode | 20 | CUT | 60 | Checking presence is default behaviour, and the "without it" paragraph (:9-13) already covers absence. Prior #66 cut the same block from the knowledge copy. | 20 |
| 49 | R27 | review `varde-code.md` "`tests_for_file` (above) also scopes the verify run" | varde-review/references/varde-code.md:47-48 | mode | 20 | CUT | 60 | simplify.md:32 already says "only the `tests_for_file` set when the runner can target files". Delete it. | 20 |
| 50 | R28 | refresh.md opener "Every change is proposed and applied only after the user approves it" | varde-docs/references/refresh.md:3-4 | mode | 12 | CUT | 60 | Step 3 states the approval flow in full. Keep the first sentence only. | 12 |
| 51 | C20 | TASK-TEMPLATE `parent:` field | assets/TASK-TEMPLATE.md:4 | mode | 2/task | CUT | 60 | Nothing reads it: the CLI derives ids from the path, and the resolver reads only status, depends_on, modifies, and creates. It also contradicts plan-splitting:14-15, where nesting replaces `parent:`. Drop it and the eval fixtures' copies. | 2 per task file |
| 52 | R25 | authoring.md "Keep reading focused" + "Spend tokens deliberately" | varde-agent-doc-authoring/references/authoring.md:22-32,41-44 | mode | 95 | COMPRESS | 60 | Prior #44's roughly 30-word target was not applied. The cross-reference is also **wrong**: "state each rule once (`reviewing.md` Token economy)", but that rule lives in reviewing.md:43-44 "Loading and references". Replace with: "Confirm what the target harness loads at startup, on activation, and by reference. Make the entry file a run sheet; move detailed procedures, tables, and long templates to references, each with a load condition. A portable skill loads only its own files. Weight detail by load frequency; state each rule once (`reviewing.md`)." | 45 |
| 53 | R26 | workflow-skills.md "Reference fan-out" bullets | varde-agent-doc-authoring/references/workflow-skills.md:22-33 | rare | 122 | COMPRESS | 60 | "Merge files always read together" (:25) duplicates reviewing.md:41; prior #136 said to drop it, which was not done. :27-28 and :31-33 both say "split only if it helps". Replace with 3 bullets: "Map one step to one self-contained reference; no step reads several cross-referencing peers. · Split only to improve routing, never to hit a size target or by dropping directives. · Premature completion (a step ends before its criterion is met): make completion observable; split by sequence only when later work repeatedly prompts early completion and evidence shows a handoff helps." | 45 |
| 54 | K23 | "body does not repeat links / timestamp / git anchor" | reflect-handoff.md:67-69 | mode | 34 | COMPRESS | 60 | Replace with: "The body does not restate frontmatter." | 28 |
| 55 | P11 | visual Rounds | visual-track.md:44-49 | mode | 41 | COMPRESS | 60 | All four steps restate the Files table (v<N> increments, latest is highest) and the SKILL rules. Replace with: "Each round: ask one targeted question, then write `v<N+1>.html`." | 28 |
| 56 | K14 | note-friction "Record a real problem" + capture steps + body list | varde-knowledge/references/note-friction.md:3-26,39-40 | mode | 175 | COMPRESS | 58 | "Real event, not impression" is said three times (:3, :7-8, :11-12). "Once per distinct event" (:24-26) restates reflect.md:12. The body list at :39-40 repeats step 1. Replace :5-13 with: "Record only a real event from this session (a command failed on stale docs, a workaround repeated, a tool surprised) in `<working>/friction/`. If there is none, say so and write nothing. A reusable technique is a `pattern` note instead. `source` is the current task or skill." Reduce :24-26 to "One item per distinct event; a repeat of an open item is a new occurrence." Drop :39's body list. | 70 |
| 57 | R29 | doc-authoring gotcha "every reference it loads is its own" vs authoring.md:30-32 | varde-agent-doc-authoring/SKILL.md:28; authoring.md:30-32 | trigger+mode | 30 | COMPRESS | 58 | Stated in three places (with reviewing.md:42). Keep the gotcha and delete authoring.md's "For portable skill bundles…" sentence, or the last sentence of the Keep-reading rewrite above. | 20 |
| 58 | P1 | prototype description (longest, 34) | varde-prototype/SKILL.md:3 | always | 34 | COMPRESS | 58 | Replace with: "Build a throwaway HTML prototype to answer a design question — a visual mockup, or a clickable walkthrough of a state model or data shape. Not for comparing options in chat." | 7 |
| 59 | I10 | install.sh directory-mode preservation | install.sh:81-88,120-133,198; tests/install-catalogue.sh:33,92,99 | — | ~120 | CUT | 55 | About 30 lines keep a `751` *directory* mode that no harness reads. File exec bits already survive `cp -p`. Delete `portable_mode`, `preserve_skill_directory_modes`, and the 751 assertion. | 120 (code) |
| 60 | C23 | Resolver `--strategy auto\|parallel` mode | scripts/resolve-execution-wave.py:17-18, 228-233 | — | ~60 | CUT | 55 | No prose uses it. Agents read the JSON. Only the tests use it, as a shortcut (8 call sites → `jq -r .strategy`). | ~60 (—) |
| 61 | R34 | scan-author gotcha (one pack, several `[[rule]]`) | varde-review/references/scan-author.md:39-40 | rare | 23 | CUT | 55 | scan-rule-format.md:6 and :84-85 (separate entries per form, see `hardcoded-credential-*`) already cover it, and step 3 points to the same example. Delete it with its heading. | 25 |
| 62 | R33 | reviewing.md "Do all local paths resolve inside the skill?" | varde-agent-doc-authoring/references/reviewing.md:42 | mode | 8 | CUT | 55 | Duplicates SKILL.md gotcha 2, and `check-refs.sh` enforces it mechanically. Delete it. | 8 |
| 63 | R37 | tests/agent-doc-authoring-evals.sh prompt-wording guards | skills/tests/agent-doc-authoring-evals.sh:22-32 | — | 90 | COMPRESS | 55 | The jq checks pin substrings of eval prompts (`contains("markdown report")`, not `~/.claude`). They guard eval prose, not behavior. Keep the fixture-exists check (:18-20) and the verifier smoke runs; delete :22-32. | 90 |
| 64 | I14 | evaluating-skills generic advice | eval-tools/evaluating-skills.md:13-17,43-46 | rare | 110 | COMPRESS | 55 | "Avoid vague assertions like 'output is good'", "review with a human", and "stop when feedback plateaus" are default practice. Keep "start with 2-3 cases incl. an edge case" and "review outputs before writing assertions". | 70 |
| 65 | C21 | Wave-resolution prose restating the resolver docstring | references/build-dispatch.md:15-24 | mode | 99 | COMPRESS | 55 | Conflict semantics already live in the script and in decomposition:37-41. Replacement: "Before each wave run `scripts/resolve-execution-wave.py --repo-root <checkout> <plan-dir>`; dispatch its `wave` with its `strategy`, report `blocked_by_dep`; exit 3 = cycle, a hard failure. Recalculate after each wave until every task is `done` or `blocked`." | 50 |
| 66 | R31 | report-categories auto-fix rule | varde-review/references/report-categories.md:7-12 | mode | 60 | COMPRESS | 55 | "A fix pass auto-resolves only…" is fix-pass step 3's selection rule, and "Escalate anything needing judgment…" restates the always-triage list below it. Replace with: "**Auto-fix rule:** `auto-fix` only when the fix is precisely describable and mirrors a pattern already in the file or its siblings; otherwise `triage` (a standalone fix run skips it)." | 30 |
| 67 | R35 | authoring.md "Scope and content" | varde-agent-doc-authoring/references/authoring.md:51-59 | mode | 62 | COMPRESS | 55 | "Templates/verification loops" duplicates reviewing.md:57, "positive instructions + alternative" duplicates reviewing.md:55, and "gotchas" duplicates workflow-skills.md:17-18. Keep: "Avoid skills too small to use alone or too broad to select precisely. Cut generic background and stale environment facts; reserve prohibitions for hard boundaries, with the alternative." | 30 |
| 68 | R40 | fix.md preamble | varde-review/references/fix.md:3-11 | mode | 80 | COMPRESS | 55 | "Which findings each mode automates… : fix-pass.md" duplicates step 3's pointer, and "If a finding is malformed… stop" pairs with step 2's validation. Keep: "Standalone is the default. `varde-change build` passes `mode=build` with `plan_context`; without it, stop (hard error). Read and edit the review's Markdown directly (format: report-format.md)." Move "malformed → report category + id, stop" into step 2 in place of "Validate quietly…". | 30 |
| 69 | K22 | handoff template "Key decisions" placeholder | reflect-handoff.md:56 | mode | 51 | COMPRESS | 55 | A 51-word placeholder. Replace with: "<one line per call: chose X over Y because Z (else the next session re-litigates it); link the plan, commit, or review for detail>". | 26 |
| 70 | C22 | Write-set paragraph | references/build-decomposition.md:37-41 | mode | 45 | COMPRESS | 55 | Repeats TASK-TEMPLATE:9 and the resolver rule. Replacement: "Declare every written file in `modifies`/`creates`; if unknown, leave both empty (the task never runs in parallel)." | 25 |
| 71 | R30 | fix-pass gate intro | varde-review/references/fix-pass.md:49-51 | mode | 35 | COMPRESS | 55 | "Step 4 checks this gate using the caller's `plan_context`, which contains the plan goal, plan-level acceptance criteria, and `creates`/`modifies` scope. Before applying…" → "Check against `plan_context` (goal, plan-level criteria, `creates`/`modifies`):" | 22 |
| 72 | R32 | report-format Calibration bullet | varde-review/references/report-format.md:52-53 | mode | 25 | COMPRESS | 55 | "If findings are repeatedly dismissed" has nothing to act on, because a report run keeps no dismissal history. "Scope the review to the change…" is scoping, not evidence. Cut the bullet; add "and its consumption path" to report.md step 1. | 20 |
| 73 | C24 | Pinned sandbox fallback aside | references/varde-workflow-cli.md:49-50 | mode | 15 | COMPRESS | 55 | varde-change never touches the Personal vault. The section is pinned by tests/vendored-copies.sh, so edit every copy together: "Sandbox denial: retry once with escalated access, unchanged; …". | 15 |
| 74 | C25 | Pre-selection prohibitions in orchestrate | references/orchestrate.md:21-22 | mode | 15 | COMPRESS | 55 | "Stop until the user selects one" is enough. The prohibition list after it is implied. | 12 |
| 75 | R39 | simplify step 1 Load + step 4 double pointer | varde-review/references/simplify.md:15,24 | mode (every build task) | 12 | COMPRESS | 55 | Two pointers to the same file. Drop step 1; step 4 keeps "With `varde-code`, per `references/varde-code.md`". | 12 |
| 76 | E7 | Workflow step 2 "Explore the target…" | explain.md:25-26 | mode | 24 | COMPRESS | 55 | The third statement of when to load varde-code (see E8). Replace with: "Load `references/varde-code.md` for unknown scope or several targets." | 12 |
| 77 | E1 | explore description | varde-explore/SKILL.md:3 | always | 23 | COMPRESS | 55 | "as a self-contained HTML explanation" → "as an HTML page". Self-containment is a mode rule, not a routing cue. | 3 |
| 78 | R36 | review eval 3 ("banana" category) | varde-review/evals/evals.json (id 3) | — | 70 | COMPRESS | 55 | Tests the cheapest behavior: ask when a category doesn't match. Meanwhile simplify (run on **every build task** per build-execution.md:56), scan triage, human triage, and the build escalation gate have **zero** evals. Replace it with a build-mode escalation eval (a finding in the always-triage list gets `Escalated: human-only`) or a scan eval (`ok:true` with `gate.status` failing). | 0 |
| 79 | K3 | knowledge CLI ref `lint` line | varde-workflow-cli.md:21-22 | mode | 12 | FIX | 55 | No knowledge step ever runs lint. On this repo's bundle, `lint --vault project --okf` reports 32 "no other Concept in the bundle links to X" errors, and note.md never asks for inbound links. An agent that runs it gets noise that contradicts the skill. Either cut the line, or add "orphan-link errors are advisory". | 12 |
| 80 | C26 | Eval 7 as a dry-run walkthrough | evals/evals.json id 7 | — | ~80 | FIX | 55 | "Show how you would run… Do not execute" grades narration, not behaviour, and no mode supports a dry run. "Delegates sequentially" and "stops after a failed child" cannot be observed this way. The prompt also says "the named group" without naming one. Fix: really run it with the `schema` child's task pre-set to `blocked`, and assert that `delivery` stays untouched and nothing merges. | 0 |
| 81 | R38 | verify-release-skill.sh | varde-agent-doc-authoring/evals/verify-release-skill.sh | — | 77 | FIX | 55 | Checks only that the file exists, which assertion 5 already makes the grader check. The deterministic check that would pay is assertion 3: run `validate-frontmatter.py` on the output and compare `name` to `deploy-release`. Upgrade it to that, or delete the verifier and its smoke test (tests/…:60-66). | 0 |
| 82 | K13 | note.md "When not to write" vs Write-notes line 30 | note.md:30-31,92-95 | mode | 38 | MERGE | 52 | Two do-not-store lists sit 60 lines apart. Merge into one line at :30: "Never store session narrative, tool output, logs, temporary task state, secrets, or unverified guesses; an obstacle is friction (`references/note-friction.md`)." | 15 |
| 83 | P12 | logic page: "opens by double-click and survives being emailed or committed as-is" | logic-track.md:7-9 | mode | 42 | COMPRESS | 52 | "Self-contained, no external deps" already implies it. Cut the last sentence. | 12 |
| 84 | E2 | explore table row 1 + `## Explore` section | varde-explore/SKILL.md:12,15-18 | trigger | 55 | MERGE | 50 | The section is a single 21-word pointer; the README itself calls it "nearly contentless". Fold it into the row: "\| An open question — problem, design, tradeoff, or how code works (default) \| Answer in chat. For structure (what exists, what depends on what, blast radius), load `references/varde-code.md`. \|" | 25 |
| 85 | I23 | tests/vendored-copies.sh header rationale | tests/vendored-copies.sh:4-19,28-30 | — | ~200 | COMPRESS | 50 | Commit-history narrative and audit item numbers ("#28+#50 inlined…") are sediment; README:107-115 already explains the model. Keep a 2-line purpose statement and the manifest format. | 100 (—) |
| 86 | C29 | Worktree workflow restating script `--help` | references/worktree.md:16-30 | rare | 123 | COMPRESS | 50 | Steps 1, 2, and 4 re-describe the scripts, which document themselves. Replacement: "Scripts (each has `--help`): `worktree-create.sh <id> [base]`, then edit only inside the printed `path=`; `worktree-merge.sh <id>` (exit 2 = nothing to merge, 3 = conflict → resolve below); `worktree-cleanup.sh <id>` only after merge exits 0." Keep step 3 (intent-based resolution, `merge --abort`). | 50 |
| 87 | I16 | evaluating-skills expanded tuning and holdout | evaluating-skills.md:62-69 | rare | 90 | COMPRESS | 50 | No query set exists to tune (I19). Keep "positive passes above 0.5; expand to ~20 prompts × 3 runs only when misfires persist". Drop the holdout procedure. | 40 |
| 88 | E9 | step 3 PR diff and area-history guidance | explain.md:27-34 | mode | 90 | COMPRESS | 50 | Replace with: "Change: explain from the diff (PR: `gh pr diff <n>`, else fetch `pull/<n>/head` and diff against the PR's base, not the current checkout). Area: add notable commits from `git log --oneline -20 <path>` to Background." "From changed hunks, not only current contents" is repeated in the table row at :47. | 35 |
| 89 | C30 | Growth-loop intro | references/plan-grow-doc.md:3-9 | mode (every plan turn) | 56 | COMPRESS | 50 | The orientation sentence and the `context_pack` pointer repeat plan-start. Replacement: "Each later turn: research what the repo can answer (`references/varde-code.md`) and run plan-fundamentals' external interface check when consumers are touched." | 25 |
| 90 | E4 | explain.md intro | varde-explore/references/explain.md:1-8 | mode | 64 | COMPRESS | 50 | Replace with: "Write a source-grounded explanation of a change or code area as one self-contained HTML file (inline CSS, no external assets). If the user asks for another format, answer in chat in that format instead." | 25 |
| 91 | K12 | note.md Storage | note.md:86-90 | mode | 35 | COMPRESS | 50 | "Merged into search by default" repeats CLI ref :25, and "versioned with the repo" is default knowledge. Replace with: "Write to the Personal vault (`~/.varde-workflow/`) only when asked; it is cross-project, so no client code, paths, or errors." | 13 |
| 92 | P14 | logic Rounds | logic-track.md:31-34 | mode | 25 | COMPRESS | 50 | :3 already says "edit in place". Replace with "Each round, ask about one missing action, scenario, or state field." | 10 |
| 93 | C28 | build-dispatch title/intro | references/build-dispatch.md:1-4 | mode | 27 | COMPRESS | 50 | The title "Task Execution" collides with build-execution.md ("Execution Reference"). Retitle it "Dispatch tasks" and keep the one-sentence delegation rule. | 5 |
| 94 | C27 | Per-task `varde-review simplify` stage | references/build-execution.md:56; build-dispatch.md:46 | mode | 10 | COMPRESS | 50 | Each executor loads varde-review and runs a simplify pass, then build-plan-finish runs a full review and a fix round over the same diff. The cost is one skill load plus one pass per task. Make it conditional ("when the task's diff is non-trivial: more than ~40 changed lines or new abstractions"), or let the finish review own it. | ~0 words; 1 skill load per task |

### Band C — worth tightening (30–49)

| # | ID | Item | Where | Load | Words | Verdict | Score | Case against → fix | Saved |
|---:|---|---|---|---|---:|---|---:|---|---:|
| 95 | C31 | Debug Phase 6 duplicates | references/build-posture-debug.md:86, 91-92 | mode | 35 | CUT | 45 | Checklist item 1 repeats Phase 5. The "structural would have prevented it → refactor candidate" paragraph repeats Phase 5's no-seam rule. The other gates stay (prior #51). | 35 |
| 96 | K18 | handoff-only-when-work-remains, stated in reflect.md and reflect-handoff.md | reflect.md:18-23; reflect-handoff.md:3-6 | mode | 90 | MERGE + FIX | 45 | The write path loads both files, so it reads the condition twice. Handoff intro becomes: "Carries this session's context to the next. To resume, skip to **Resume a handoff**." **FIX:** "When nothing is left, write none" also refuses an explicit "write a handoff" request, because the SKILL row routes that request to reflect.md. Append "…unless the user asked for one." | 30 |
| 97 | R41 | report.md "Choose the target" vs step 1 | varde-review/references/report.md:14-19,23-27 | mode | 43 | MERGE | 45 | Two scoping passes before any work. Fold the defaults (working tree vs `HEAD` or named ref; clean tree → since nearest merge/tag, offer whole-codebase) into step 1, followed by "state the resolved target and categories before reading code". Delete the heading. | 15 |
| 98 | C35 | build-plan-finish step 2 length | references/build-plan-finish.md:8-19 | mode | ~110 | COMPRESS | 45 | The human-triage mechanics are spelled out again even though fix.md owns them. Replacement (same semantics, #118 kept): "Findings → one `executor` round of `varde-review fix mode=build` (review ID + `plan_context`); no re-review. Escalated findings → one triage table in fix.md's format before acceptance checks (fix → `varde-review fix`, dismiss → reason, action-item → nested companion plan). Under orchestrate, return them instead of pausing." | 50 |
| 99 | I2 | README "Two SKILL.md shapes" | README.md:80-99 | rare | 151 | COMPRESS + FIX | 45 | varde-prototype is filed as "Inline", yet its SKILL.md routes to one of two track references, which is a dispatcher by the README's own definition. The explore paragraph restates the list. Keep the two definitions and "don't convert for consistency alone". Drop the per-skill assignments. | 50 |
| 100 | E10 | HTML output sections table | explain.md:41-47 | mode | 103 | COMPRESS | 45 | Background: why it exists (change intent or git log). Intuition: how it works, analogies, invariants. Code/How It Works: walk the hunks per file with affected callers (change), or key files, entry points, and data flow (area). "Found with Grep/Glob/Read" is noise. | 40 |
| 101 | R43 | scan.md step 6 `--apply` | varde-review/references/scan.md:48-56 | mode | 80 | COMPRESS | 45 | → "For a `rewrite` rule with a straightforward match, run `scan --apply` (same JSON). It rewrites only after a complete scan and reports dirty files as `skipped-dirty`; tell the user, and use `--force` only with approval. Otherwise fix by hand in the file's style, using `remediation` as guidance." Claims verified against `scan --help`. | 25 |
| 102 | P3 | Rules for every round | SKILL.md:17-24 | trigger | 74 | COMPRESS | 45 | Replace with: "Ask one topic per turn (≤3 questions only as facets of one decision) as an inline numbered menu with a recommendation. Deliver a plain HTML file on disk and report its path first after every write; an `Artifact`/`mcp__visualize` preview is additive, never a substitute." | 25 |
| 103 | C32 | plan-start discovery sentence | references/plan-start.md:9-12 | mode | 35 | COMPRESS | 45 | Batching and "fall back when unavailable" are default behaviour or covered by varde-code.md's fallback. Replacement: "Batch discovery into one read-only call; include `varde-code context_pack` (feature terms) when available." | 20 |
| 104 | C34 | verify.md opener/defaults | references/verify.md:3-5 | mode | 25 | COMPRESS | 45 | "Report evidence without changing files" plus the "Never…" line say one thing twice, and "Batch independent reads" is default. Replacement: "Read-only: never fix, change status, or tick criteria." | 18 |
| 105 | K6 | note.md Search | varde-knowledge/references/note.md:3-10 | mode | 61 | COMPRESS | 45 | **Order defect:** "`--vault project` first" comes before the CLI is even introduced, and the flag means nothing on the Grep path. "Never install the CLI" is repeated at CLI ref :43. Replace with: "Read a known note directly. To discover one, use ranked search per `references/varde-workflow-cli.md` (`--vault project` first) if `varde-workflow` is on PATH; else Grep/Glob `<knowledge>/` and name the lost ranked search once. Read a note in full only after search identifies it." | 16 |
| 106 | R45 | spec.md step 6 verify bullets | varde-docs/references/spec.md:26-35 | mode | 70 | COMPRESS | 45 | "Architecture has no flows" and "one `## Summary` between paired sentinels" restate spec-format rules. Keep the provenance recompute (the race guard), link resolution, the unverified-area marking, and lint (verified: `lint --bundle --vault project --okf` exists). | 15 |
| 107 | R47 | scan-author step 6 placement | varde-review/references/scan-author.md:25-29 | rare | 45 | COMPRESS | 45 | Repeats scan-rule-format "Scopes and precedence". → "Place it per scan-rule-format `## Scopes and precedence` (default repo scope; ask when unclear). To customize a built-in, `rules_seed` and edit in place, keeping its `id`." | 15 |
| 108 | I15 | evaluating-skills grading paragraph | evaluating-skills.md:35-41 | rare | 70 | COMPRESS + FIX | 45 | "Mechanical checks → verification_script" is said twice in two sentences. :59 "Codex's read-proxy scoring" is stale since #10; say "substring proxy". | 15 |
| 109 | R42 | simplify step 2 worktree | varde-review/references/simplify.md:16-18 | mode (every build task) | 30 | COMPRESS | 45 | → "Edit in the current checkout, no worktree; if concurrent edits make it unsafe, stop and ask." | 13 |
| 110 | C36 | docwatch setup | references/plan-docwatch.md:10-13 | rare | 20 | COMPRESS | 45 | The `docwatch list --json` confirmation is optional ceremony. All claims verified (`add <folder>`, `remove <path>` accepts a folder, guard.rs reverts outside writes). | 10 |
| 111 | R49 | refresh.md Constraints | varde-docs/references/refresh.md:35-39 | mode | 29 | COMPRESS | 45 | "Write only prose grounded in the source" duplicates step 3.1-3.2. Keep "Diagrams in Mermaid only" (non-default); the changelog line moves to SKILL.md per the eval-3 row. | 10 |
| 112 | K32 | "Read only the reference… Then load its explicitly required supporting files." | varde-knowledge/SKILL.md:19-20 | trigger | 14 | COMPRESS | 45 | Replace with "Read only that reference." References name their own dependencies. | 8 |
| 113 | C33 | Unconditional interview.md read in build-plan | references/build-plan.md:19-20 | mode | 10 | COMPRESS | 45 | Unattended runs (every orchestrate child) never ask, yet each loads 143 words. Change to "`references/interview.md` when interactive". | 0 words; 143 loaded per unattended run |
| 114 | R44 | spec.md step 3 delegate briefing | varde-docs/references/spec.md:12-19 | mode | 75 | FIX | 45 | "Read short, known files directly. Use `get_symbol` only for exact symbols…" duplicates varde-code.md "When to use it". "When `varde-code` was detected in step 2": step 2 detects nothing. "binary path" does not say which binary. Replace with: "…Brief each delegate with: `varde-code` path (if on PATH), domain, changed files, output path, `spec-format.md`." | 20 |
| 115 | R46 | review `varde-code.md` "When to use it" | varde-review/references/varde-code.md:11-14 | mode | 27 | KEEP | 45 | Generic, but short and not part of the vendored contract; the batch/get_symbol hints are mildly non-default. | 0 |
| 116 | R48 | verify-self-audit.sh | varde-agent-doc-authoring/evals/verify-self-audit.sh | — | 276 | KEEP | 45 | A deterministic ranking check is worth having. Minor: the assertion says "new markdown file", but any pre-existing top-level `.md` passes. | 0 |
| 117 | I21 | tests/output-evals.sh | skills/tests/output-evals.sh | — | 1,621 | KEEP | 45 | #80's compress was rejected. No new argument. It passes in 9 s. | 0 |
| 118 | K35 | knowledge evals | varde-knowledge/evals/evals.json | — | 764 | FIX | 42 | The judge sees only final text (#96 not applied), so the file and Edit assertions in 1-3 cannot be graded. Evals 2-3 edit notes that do not exist in the sandbox (no `files`). Eval 6 misdescribes distill: it asks "promote to a durable knowledge note", but distill proposes skill or doc changes and marks items `promoted`. It also asserts "independent" occurrences, while reflect-distill.md:16-17 counts repeats on one item. Fix: add `files` fixtures for 2-3, a `verification_script` for 1-3, and reword 6. | 0 |
| 119 | I19 | Trigger tooling with no committed query set | eval-tools/run-evals.sh (1,740) + tests/trigger-evals.sh (806) | — | 2,546 | FIX | 42 | No `queries.json` exists anywhere, so the always-tier descriptions have no routing regression check, and 2.5k words of runner go unused. Commit one ~20-prompt sibling-boundary set (explore/prototype, docs/doc-authoring, change/review, knowledge/change "wrap up"). If the user won't run it, mark the runner dormant. | 0 |
| 120 | R51 | reviewing.md Adversarial inventory report paragraph | varde-agent-doc-authoring/references/reviewing.md:22-28 | mode | 95 | COMPRESS | 40 | Prior #157 said to reshape it into a 4-bullet weigh list; that was **not applied**. The report spec is prose where a template carries it in fewer words: "Report: top summary of highest-value changes; then `\| # \| Item \| Location \| Benefit \| Cost \| Evidence \| Action \|`, #1 = strongest cut, load-bearing last; include a `wc -w` baseline. On an edit's final pass, apply the tests without writing a report." | 35 |
| 121 | R54 | scan-rule-format `temp.dependency_facts` detail | varde-review/references/scan-rule-format.md:112-118 | rare | 75 | COMPRESS | 40 | Column list and certainty semantics only matter for dependency-verification rules, which is rare within a rare file. Trim to the columns plus "base blocking policy on `certified` rows, not the persisted graph". | 30 |
| 122 | C37 | AC reference opener | references/plan-acceptance-criteria.md:3-6 | mode | 40 | COMPRESS | 40 | Repeats the template comment ("plan-level definition of done") and the plan-fundamentals ordering. Replacement: "Criteria are plan-level: true after ship, however build slices it." | 25 |
| 123 | R52 | report.md step 7 labelling clause | varde-review/references/report.md:50-54 | mode | 45 | COMPRESS | 40 | "labelled by the auto-fix rule…, with `Disposition` blank" restates report-format.md:63 and report-categories.md:7. → "Append each finding to its category file (report-format.md) as you find it." | 12 |
| 124 | K16 | reflect.md intro | varde-knowledge/references/reflect.md:1-6 | mode | 47 | COMPRESS | 40 | "Each record type's procedure owns its format." is filler. Cut it. | 7 |
| 125 | C39 | Missing eval: plan Finalize | evals/evals.json | — | +~80 | FIX (extend) | 40 | No eval covers the most frequent planning endpoint: slug rename, `validate`, the completeness check, "stays backlog". Parallel waves and the resume check are also uncovered, but those are costlier. Add one Finalize case first. | −80 (added) |
| 126 | I13 | eval-tools/README.md | skills/eval-tools/README.md:7-14 | rare | 117 | FIX + COMPRESS | 40 | **Broken pointer:** :7-9 sends query-set authoring to `optimizing-descriptions.md`, but #10a moved that content here. The file is now 100 words with no eval guidance. Point to `evaluating-skills.md` "Trigger accuracy". :13-14 restates the two bullets above it. | 40 |
| 127 | C38 | "Commit tracked plan moves" and the finish tail | references/build-plan-finish.md:34-39 | mode | 34 | FIX | 40 | Plans are no longer moved (#94 removed the archive convention; `conclude` edits status in place), so "moves" is stale. "Read interview.md and worktree.md then" is garbled. Replacement: "Show the local diff. If this run created a worktree, offer Merge (default) or Stop per `references/worktree.md`. Commit the plan's status change when plan storage is tracked." | 10 |
| 128 | R50 | docs `varde-code.md` "When to use it" lists "provenance" | varde-docs/references/varde-code.md:13 | mode | 27 | FIX | 40 | varde-code does not compute provenance; `git hash-object` does (spec-format.md:29-33). Drop "and provenance". | 2 |
| 129 | R53 | doc-authoring eval 2 "prioritizing ambiguities that would change the skill's structure" | varde-agent-doc-authoring/evals/evals.json (id 2) | — | 15 | FIX | 40 | authoring.md:13-20 asks about environment, failures, and conventions. It never mentions structural ambiguity, so the assertion grades an untaught behavior. Drop it or reword to match :15-17. | 0 |
| 130 | P17 | prototype evals | varde-prototype/evals/evals.json | — | 502 | FIX | 40 | The key assertions are about files: `variant-*.html`, a `<a href>` switcher with no `<script>`, `logic.html`, and a DOM-free module. The judge cannot see them (#96). A roughly 15-line `verification_script` (glob, grep for `<a href`, no `<script` in variants, `logic.html` exists) makes them deterministic without the #96 work. | 0 |
| 131 | C40 | Lesson-recording line | references/plan-start.md:49-50 | mode | 20 | KEEP | 40 | Short, and the same posture appears in the build and orchestrate finishes. No change. | 0 |
| 132 | R55 | authoring.md :10-11 "state the default action… exact commands only for fragile operations" | varde-agent-doc-authoring/references/authoring.md:10-11 | mode | 22 | KEEP | 40 | Overlaps reviewing.md:53-54, but authoring needs the instruction form and reviewing the check form. Acceptable. | 0 |
| 133 | P6 | memory-location gotcha, both halves | SKILL.md:42-46 | trigger | 39 | COMPRESS | 38 | Prototype never touches `<knowledge>`. Tailor it: "`<working>`: `varde-workflow paths --json` → `data.working`; else `$VARDE_WORKING_DIR`; else `memory-bank/working`. Outside the repo, use plain file ops." This needs vendored-copies.sh to pin 4 files instead of 5. | 17 |
| 134 | E15 | explore evals | varde-explore/evals/evals.json | — | 711 | FIX | 38 | **#83 was agreed but never applied** (7afcac2 did not touch this file). No `setup_script`, so all 5 cases run against an empty directory. #2 expects a menu for "payments", but explain.md:17-20 infers an area unless `payments` is also a git ref, which only the planned fixture creates. #3 still contains the self-contradicting "After writing the file…". No plain-area ("auth") case. | 0 |
| 135 | I22 | tests/trigger-evals.sh | skills/tests/trigger-evals.sh | — | 806 | KEEP (+I17) | 38 | Per-harness pass/miss/reject traces stay useful. Add one stderr-message assertion. | 0 |
| 136 | R60 | spec-format "Document content" as prose | varde-docs/references/spec-format.md:58-77 | mode | 155 | COMPRESS | 35 | A section list written as prose. As a skeleton template (`## Summary / ## Overview / ## Scope Boundary (owns\|does-not-own) / ## Key Operations / ## Key Types / ## Invariants / ## Acceptance Criteria / ## Flow: <name>`) plus 3 conditional rules, it is shorter and cannot be misread. | 40 |
| 137 | R59 | doc-authoring Workflow step 4 final pass loads reviewing.md | varde-agent-doc-authoring/SKILL.md:24 | trigger (pulls 552-word mode) | 14 | COMPRESS | 35 | Every authoring run also loads the whole review reference, including the report spec (:22-28), which a final pass does not use. Point to the checklists only: "Final pass: `reviewing.md` checklists (skip Adversarial inventory) on the changed scope; check every changed pointer." Or accept the cost (prior #19 kept it). | 0 |
| 138 | K26 | reconcile Notes: "`stale_after` date" signal | reconcile.md:17-20 | mode | 47 | FIX | 35 | `stale_after` is object-typed in OKF (okf-core `STRUCTURED_FIELD_NAMES`; lint rejects a bare scalar), and note.md never writes it, so this "date" signal never fires. Keep only: "A `reconciled.sha` far behind `HEAD` is a drift signal." | 12 |
| 139 | R57 | scan.md step 1 gate choice disconnected from step 2 command | varde-review/references/scan.md:18-22 | mode | 25 | FIX | 35 | Step 1 picks `severityThreshold`/`gateRules`, but step 2's command passes neither. → "Run `varde-code scan --json '{\"repoRoot\":\"<repo>\",\"severityThreshold\":\"error\"}'` (or `gateRules`; not both), without `--apply`." Merges steps 1-2. | 8 |
| 140 | R56 | docs eval 3 changelog refusal is on a route that never loads the constraint | varde-docs/evals/evals.json (id 3); refresh.md:39 | —/mode | 30 | FIX | 35 | The changelog exclusion lives only in refresh.md, but a spec request routes to spec.md alone. The eval therefore tests base-model behavior. Move "not CHANGELOGs, release notes, or external doc sites" into the SKILL.md table's user-facing row and drop it from refresh Constraints (net 0 words). | 0 |
| 141 | R58 | doc-authoring eval 3 "Workflow-type skill" term | varde-agent-doc-authoring/evals/evals.json (id 3) | — | 10 | FIX | 35 | "Workflow-type" came from the deleted vocabulary.md. Reword to "an ordered numbered `## Workflow`" (workflow-skills.md:13). | 0 |
| 142 | P9 | visual Files table + mockup rules | visual-track.md:9-21 | mode | 104 | KEEP (trim) | 35 | "JS/CDN/fonts need agreement" is valuable. Cut "with semantic elements where the content supports them" (default behaviour). | 8 |
| 143 | C41 | Route-away evals 6, 11 | evals/evals.json ids 6, 11 | — | ~60 | KEEP | 35 | Cheap. They test the Entry routing precedence. | 0 |
| 144 | C42 | Plan-level drift check | references/build-dispatch.md:6-13 | mode | 65 | KEEP | 35 | One cheap check before the first wave catches stale plans before executors burn cycles. | 0 |
| 145 | R61 | review `varde-code.md` "Diff-scoped lookups" | varde-review/references/varde-code.md:33-45 | mode | 90 | KEEP | 35 | Used by simplify on every build task; commands and inputs verified (`detect_changes {diffMode, range?}`, `symbols_in_files includeBody`, `context_pack query`). | 0 |
| 146 | R62 | tests/agent-doc-authoring-evals.sh fixture + verifier smoke | skills/tests/agent-doc-authoring-evals.sh:1-20,34-68 | — | 250 | KEEP | 35 | Passes; executable bit is fixed (#168 applied). Cheap guard that the verifiers honor the declared-assertion contract. | 0 |
| 147 | E11 | explain step 5 "Record lessons" | explain.md:38-39 | mode | 22 | KEEP | 35 | Prior #107: models never record unprompted, and "otherwise skip" limits noise. | 0 |
| 148 | I6 | README "Adding a review category", "Change execution checks" | README.md:116-156 | rare | 176 | KEEP | 35 | The user kept these (#27). No new argument. | 0 |
| 149 | R63 | doc-authoring eval 1 "consolidation vs condensation" assertions | varde-agent-doc-authoring/evals/evals.json (id 1), last 2 assertions | — | 40 | FIX | 30 | Since vocabulary.md was cut, no reference teaches "don't condense prose when the problem is fan-out". Two of seven assertions grade an untaught rule. The insight is real and non-default: add one line to reviewing.md Loading ("Fix fan-out by merging files, not by shortening prose"), about 10 words, or drop both assertions. | -10 |
| 150 | C47 | Standalone debug commits | references/build-posture-debug.md:93 vs build-micro-change.md:16 | mode | 15 | FIX | 30 | SKILL routes a named bug straight to debug `fix` with no task file, and Phase 6 then commits. The equally direct micro-change path forbids commits unless asked. Add "standalone (no task file): commit only when asked". | −6 |
| 151 | D2 | varde-review description has no "Not for" clause | varde-review/SKILL.md:3 | always | 24 | FIX | 30 | It is the only one of the seven that breaks the house rule check-refs.sh:46 prints. The nearest confusion is change's "fix a named bug" vs review's "apply a review's findings". Add "Not for fixing a named bug." (+6) only if I19's routing set shows misroutes. As it stands there is no evidence either way. | −6 |
| 152 | C45 | Initial task-file commit | references/build-decomposition.md:76-77 | mode | 20 | FIX | 30 | "Commit the initial task files once" contradicts build-plan.md:31, which says ignored plan files never enter a commit, and ignored is the default. Add "when plan storage is tracked". | −4 |
| 153 | E13 | varde-code.md operations + `includeReferences` note | varde-code.md:16-35 | rare | 114 | FIX | 30 | All five examples were run and return `ok:true`. **Wrong flag:** `includeReferences` is accepted only by `symbols_in_file(s)` (code-cli simple.rs:343), which the list does not show. `get_symbol` takes only `includeBody`. Replace :35 with "Pass `includeBody` only when bodies are needed." | 3 |
| 154 | C43 | "Spec" in the external interface check | references/plan-fundamentals.md:11 | mode | 64 | FIX | 30 | "Record them in the spec and AC": the plan has no "spec" section. Should read "in Design and AC". | 0 |
| 155 | C44 | Hard-coded `memory-bank/` in lint step | references/build-execution.md:57-58 | mode | 25 | FIX | 30 | Ignores path resolution. On this machine `<working>` is `~/not_cloud/Personal-Notes/...` (verified with `paths --json`). Should read "after source edits outside `<working>`/`<knowledge>`". | 0 |
| 156 | C46 | Refactor per-change commits | references/build-posture-refactor.md:22-24 | mode | 35 | FIX | 30 | "apply, verify, commit" per change contradicts one commit per task (build-plan-run:11, build-execution:66). Pick one rule. Suggested: per-change checkpoints are allowed but must reference the task ID, and plan-run:11 becomes "at least one commit per task". Or keep one commit and make "revert immediately" mean `git checkout -- <files>`. | 0 |
| 157 | C48 | `worktree-merge.sh` auto-commit and overloaded exit 4 | scripts/worktree-merge.sh:11-12, 20, 50-55, 68-69 | — | ~60 | FIX | 30 | `add -A` plus a placeholder commit merges unverified leftovers from an incomplete executor into the main branch under a non-task message. That contradicts "commit once Verification passes". Fix: exit 5 on a dirty worktree and let the caller decide. Exit 4 also covers a missing branch, an unresolvable target, and "merge failed without conflicts", but usage documents only the target mismatch; list them all. | 0 (—) |
| 158 | R64 | fix.md Closing "archive the review folder" | varde-review/references/fix.md:70-71 | mode | 8 | FIX | 30 | Undefined: no file in any skill says where or how to archive a review, and report-format.md:7 lists `status` with no values. Define it ("set `review.md` `status: archived`") or cut it. | 0 |
| 159 | R65 | scan.md "no third bucket" vs steps 6/8 | varde-review/references/scan.md:7-9,52-60 | mode | 20 | FIX | 30 | Step 6 leaves `skipped-dirty` findings "unresolved", and step 8 reports "anything left for the user", which is a third bucket. → "Every finding ends fixed, not-real with a reason, or explicitly handed to the user." | 0 |
| 160 | R66 | docs evals: no spec provenance/sentinel eval | varde-docs/evals/evals.json | — | 0 | FIX | 30 | The most fragile, most non-default behaviors (byte-identical `## Notes` tail, sentinel drift → leave unchanged, `source_hash` recompute) have no eval. Add one: a spec with a hand-edited Notes tail and a reversed sentinel pair. | 0 |
| 161 | I17 | run-evals.sh Codex parser calls undefined `fail()` | eval-tools/run-evals.sh:147-230 | — | 3-line fix | FIX | 30 | **Regression from 7afcac2:** `def fail` was deleted along with the lexer (it was at the old :167). Every Codex error path now raises NameError. The run still aborts through bash `\|\| die`, but the reason (auth, unknown schema, failed read) is lost. trigger-evals.sh checks only the reject exit, so it passes. Re-add `def fail(m): print(m, file=sys.stderr); sys.exit(1)` and assert one stderr message in trigger-evals.sh. | 0 |
| 162 | I18 | run-output-evals judge input (#96 agreed, not applied) | eval-tools/run-output-evals.sh:290-304 | — | runner | FIX | 30 | The judge still gets only `transcript.txt`. Most knowledge, explore, and prototype assertions (files written, Edit vs rewrite, no HTML written) are ungradable, so their eval results carry almost no signal. Apply #96, or ship per-skill verification scripts (P17). | 0 |
| 163 | R67 | review eval 4 (per-finding isolation) | varde-review/evals/evals.json (id 4) | — | 90 | KEEP | 30 | Tests a non-default behavior (no repo-wide stash or checkout) that fix-pass step 5 states. | 0 |
| 164 | R68 | doc-authoring fixtures | varde-agent-doc-authoring/evals/fixtures/* | — | 337 | KEEP | 30 | Intentionally frozen audit target. It references the retired memory-locations.md, which is fine for an audit fixture. | 0 |
| 165 | R69 | doc-authoring gotcha `</content>` | varde-agent-doc-authoring/SKILL.md:30 | trigger | 8 | KEEP | 30 | Concrete, observed failure; cheap. | 0 |
| 166 | R70 | reviewing.md "Workflow checks" | varde-agent-doc-authoring/references/reviewing.md:73-76 | mode | 19 | KEEP | 30 | Already at its minimum after the prior audit. | 0 |
| 167 | R71 | spec-plan "Plan" output | varde-docs/references/spec-plan.md:32-42 | mode | 64 | KEEP | 30 | dirty/upToDate/toDelete/ambiguous feeds spec.md steps 3-4; `ambiguous` protects moved code from deletion. | 0 |
| 168 | R72 | spec-plan "Full scan" | varde-docs/references/spec-plan.md:24-30 | mode | 43 | KEEP | 30 | Absorbs the git-only incremental path above; the layer-classification rule is non-default. | 0 |
| 169 | R73 | docs `varde-code.md` preamble + Fallback + Content and tests | varde-docs/references/varde-code.md:1-10,25-41 | mode | 160 | KEEP | 30 | Vendored contract (preamble, Fallback) pinned by the test. Keep "Content and tests" once spec.md routes here. | 0 |
| 170 | R74 | scan.md Suppressions | varde-review/references/scan.md:62-67 | mode | 33 | KEEP | 30 | Syntax verified against rules/suppress.rs. | 0 |
| 171 | K30 | reflect-distill steps 3, 5-9 (inspect, proposal, menu, apply, promote-retry) | reflect-distill.md:23-26,34-46 | rare | 173 | KEEP | 30 | The user already trimmed this (#130). Nothing new to argue. | 0 |
| 172 | I3 | README skill map | README.md:37-59 | rare | 166 | KEEP | 30 | Already compressed per #27. | 0 |
| 173 | I20 | run-output-evals.sh harness (timeout, HOME isolation, fixtures, verification) | eval-tools/run-output-evals.sh | — | 2,637 | KEEP | 30 | Kept by the user (#114). `files`/`setup_script`/`verification_script` support exists; the skills just don't use it. | 0 |

### Band D — keep; fix where marked (15–29)

| # | ID | Item | Where | Load | Words | Verdict | Score | Case against → fix | Saved |
|---:|---|---|---|---|---:|---|---:|---|---:|
| 174 | I4 | README intro, Related modules, Install | README.md:1-36 | rare | 124 | KEEP | 28 | The human entry point. The marker-deletion note matches install.sh. | 0 |
| 175 | R77 | fix-pass "defect gone" block placement + wording | varde-review/references/fix-pass.md:35-45 | mode | 100 | COMPRESS | 25 | Valuable (a passing scoped run ≠ defect fixed), but it sits after the loop while step 10 already says "On success, set `Disposition: fix`", so a literal reader sets it first. It also claims a scoped run "proves no regression". Make it the step 10 precondition: "10. Confirm the defect is gone before `Disposition: fix`: prefer a check that failed before the fix (existing test or step 8's `assert:` lines); one passing before and after proves nothing. With none, re-read the path against `Summary` and record 'confirmed by inspection'." | 45 |
| 176 | R76 | spec.md: inline generation never loads spec-format.md; spec path never loads varde-code.md | varde-docs/references/spec.md:12-19 | mode | 0 | FIX | 25 | spec-format.md is named only in the delegate briefing and the index step, but the default ("one at a time") has the main agent writing domains. Add "Write each domain per `spec-format.md`; with `varde-code` on PATH, use `references/varde-code.md`." (+15). That makes the moved pointer the only route into the file. | -15 |
| 177 | R75 | review eval 1 folder path | varde-review/evals/evals.json (id 1) | — | 20 | FIX | 25 | Expects `memory-bank/working/reviews/<YYYY-MM-DD>-<branch>-<target>/`. report-format.md:5 says `<working>/reviews/<YYYY-MM-DD>-<slug>/`, and on this machine `<working>` resolves outside the repo (`varde-workflow paths --json` → Personal-Notes). The grader would fail a correct run. Use `<working>/reviews/<date>-<slug>/`. | 0 |
| 178 | C49 | Plan-splitting | references/plan-splitting.md | mode | 167 | KEEP | 25 | Nesting-as-membership matches the CLI (derived ids from the path). Clusters is framed as a signal, and the user confirms before children are created. | 0 |
| 179 | C50 | Refactor posture core | references/build-posture-refactor.md:1-16, 25-37 | mode | ~200 | KEEP | 25 | Behaviour definition, tests-first bootstrap, "narrow pass proves nothing", rename discipline (prior #30 trimmed). The commit rule is fixed in C46. | 0 |
| 180 | C51 | change-output-eval-fixtures core | tests/change-output-eval-fixtures.sh (seeded-bug fixtures, state guard :84-94) | — | ~1,900 | KEEP | 25 | Checks that seeded bugs actually reproduce and that every `status:` literal is a schema state (read from the vendored table). Without it, the evals grade against broken fixtures. | 0 |
| 181 | R78 | docs eval 1 & 2 (minus stale assertions) | varde-docs/evals/evals.json (id 1-2) | — | 250 | KEEP | 25 | They test the approval loop and hand-written-section preservation. | 0 |
| 182 | R79 | review eval 1 (minus path fix) | varde-review/evals/evals.json (id 1) | — | 150 | KEEP | 25 | Default breadth, folder-before-work, per-category files. | 0 |
| 183 | K11 | note.md Link notes | note.md:80-84 | mode | 26 | KEEP | 25 | Bundle-absolute links are the OKF rule. | 0 |
| 184 | K34 | Mode split: note / friction / reflect / handoff / reconcile / distill as separate files | varde-knowledge/references/* | mode | 2,253 | KEEP | 25 | Each file is a distinct request and loads alone, except reflect. Its chain costs about 1,420 words (reflect 191 + friction 258 + note 445 + handoff 525), plus 244 when the CLI is on PATH. Merging would raise the cost of every *other* request. The fix is K14/K18/K22/K23 inside the chain, not a merge. | 0 |
| 185 | I5 | README Internal techniques (vendored-copy model) | README.md:100-115 | rare | 131 | KEEP | 25 | States why copies exist and names the guard test. | 0 |
| 186 | I26 | tests/frontmatter.sh | skills/tests/frontmatter.sh | — | 64 | KEEP | 25 | Uses the only-system uv workaround from AGENTS.md. Skips cleanly without uv. | 0 |
| 187 | I12 | check-refs pointer check scans source, not the install | check-refs.sh:56 | — | 1 | FIX | 22 | The header claims the checks see "exactly what an end user receives", but the Python check walks `$SCRIPT_DIR`. So `evals/` files count as resolvable basenames: a SKILL.md naming `verify-self-audit.sh` passes, yet that file is never shipped. Pass `"$TMP"`. :44 says "double-quoted", but only folded scalars are rejected; drop "double-quoted". | 0 |
| 188 | P10 | visual Round 1 variants | visual-track.md:23-42 | mode | 179 | KEEP (trim) | 22 | Full-page variants with a no-JS switcher, and "vary layout, not colours", work against agent defaults. Compress Pick N to "2–3 close variants (narrow) or 3–5 unrelated shapes (wide); default 3, max 5; state N." Drop step 4's "show the path" (the SKILL rule covers it). | 22 |
| 189 | K21 | reflect-handoff write steps (anchor, redact, save) | reflect-handoff.md:18-39 | mode | 150 | KEEP (trim) | 22 | Redaction and the git anchor are not default. Trim "if in doubt, redact" and "Drop empty sections" (the template already implies it). | 12 |
| 190 | K4 | knowledge CLI ref search examples + vault note | varde-workflow-cli.md:9-26 | mode | 94 | KEEP | 22 | Verified correct against `concept search --help`: `--field` narrows before `--text` ranks, and results merge the Personal vault unless `--vault project` is given. It is the only place the flag syntax lives. | 0 |
| 191 | C56 | Resume check ignores `in_progress`; spike vs commit rule | references/build-dispatch.md:65-73 | mode | 82 | FIX | 20 | A crash leaves a task `in_progress`. The resolver's `ready` takes only `todo` (script:128-131), so the task is never re-dispatched, the run never reaches "all done or blocked", and no rule says what to do. Also "every `done` task needs a matching source commit" fails for spike tasks ("commit nothing", build-plan.md:48). Add: "An `in_progress` task at resume was interrupted: show its diff and Progress, re-dispatch on confirmation. Spike tasks need no commit." | −25 |
| 192 | C58 | Parallel wave with ignored plan storage | references/build-parallel.md:10-14, 16-18 | rare | 60 | FIX | 20 | worktree-create.sh copies nothing, so under the default ignored `<working>` a task worktree has no `tasks/<id>.md`. The executor "owns its task file" (dispatch:46-47) but is never told where it lives. Add: "Brief each executor with the task file's absolute path in the main checkout; it updates status/Progress there." Merge exit 2 (no commits, e.g. a no-op task) is also unhandled: "exit 2 → cleanup, report". Keep the rest (prior #115). | −25 |
| 193 | C53 | build-plan step 5 wrong owner and needless load | references/build-plan.md:54-57 | mode | 34 | FIX | 20 | It says build-plan-run owns the "loop, resume check, bounded retry", but build-plan-run:5-6 and build-dispatch say dispatch owns them. It also makes the orchestrator read build-execution.md "in full" (517 words) even though the orchestrator "implements none itself" (dispatch:3-4). Replacement: "5. **Run tasks** per `references/build-plan-run.md`; read `build-execution.md` only under `inline`." | 14; ~517 loaded per delegated run |
| 194 | C54 | Plan discovery misses nested plans and includes groups | references/build-plan-run.md:23-24; status.md:5 | mode | 30 | FIX | 20 | Both glob `<working>/plans/*/plan.md`. build-plan-finish step 2 creates **nested** companion plans and step 3 then blocks the parent until they are `completed`, but no discovery or status path ever lists them. They are buildable only if the user types the compound id. Discovery also doesn't exclude `shape: group` parents, which have no tasks or AC (`conclude` fails "missing an acceptance criteria section", verified). Fix both: "every `plan.md` at any depth under `<working>/plans/`; skip `shape: group`" (status: show children under their group). | −12 |
| 195 | C55 | Bounded retry contradicts interactive Retry/Skip/Abort | references/build-dispatch.md:61-63 vs build-plan-run.md:45-49 | mode | 30 | FIX | 20 | Dispatch says the second failure means "halt the run". Plan-run's interactive mode offers Skip and continue. Replacement: "If that fails too, the task stays `blocked` with the reason in `#### Progress`; build-plan-run.md decides (unattended: halt; interactive: Retry/Skip/Abort)." | 10 |
| 196 | C60 | Orchestrate ordering via one child's `graph`; compound ids | references/orchestrate.md:31-34; varde-workflow-cli.md:37-38 | mode | 55 | FIX | 20 | Verified in a scratch repo: `graph` on one child returns only that child plus its `depends_on` closure, so independent siblings are missed. A compound `depends_on: [g/a]` returns `dependency_missing`, because the CLI resolves entries as sibling directory names. The text says "(sibling or compound ids)". Replacement: "Run `varde-workflow readiness` on each child (blockers = unmet deps); `depends_on` holds sibling slugs only." | 10 |
| 197 | C57 | `done` transition without `in_progress` | references/build-execution.md:62-63 | mode | 30 | FIX | 20 | `todo→done` is illegal (schema verified). Under `inline`, or when the orchestrator skipped the move, the executor's `transition … done` fails. Add "(from `in_progress`; move it there first if still `todo`)". | −8 |
| 198 | C52 | Resumed draft never re-enters the growth loop | references/plan-resume.md:11-12 | mode | 15 | FIX | 20 | "Continue from the headings that still hold placeholder text" never routes back to the growth loop, so a resumed draft can skip self-review, the completeness check, and `validate`. Replace with "Resume: continue per `references/plan-start.md` Later turns." | 5 |
| 199 | C61 | PLAN-TEMPLATE `depends_on` comment | assets/PLAN-TEMPLATE.md:8 | mode | 10 | FIX | 20 | The comment says "plan ids", but for a child the compound id resolves to the wrong path (verified). Replacement: "sibling plan dir names (a child's slug, never `<group>/<child>`) that must be `completed` first". | −4 |
| 200 | C59 | Orchestrate feature worktree "reuse an existing branch" | references/orchestrate.md:27-28 | mode | 20 | FIX | 20 | worktree-create.sh exits 3 when `worktree/<id>` already exists (script:68-70), so it cannot reuse one. Replacement: "exit 3 on resume → reuse `.varde/worktrees/orchestrate-<group-id>` as is." | 0 |
| 201 | I1 | README "Lessons are recorded…" bullet | skills/README.md:74-78 | rare | 55 | FIX | 20 | **Contradiction:** it says session boundaries "run `varde-knowledge reflect` and write a handoff", but reflect.md:18-23 writes one only when work remains. Replace with "…run `varde-knowledge` reflect, which writes a handoff only when work remains." | 0 |
| 202 | I9 | install.sh `-f` help text | install.sh:30 | — | 5 | FIX | 20 | "Overwrite selected consolidated directories" is stale jargon. Replace with "Overwrite existing installs without prompting". | 0 |
| 203 | C62 | Orchestrate Finish (group transitions, combined triage, reflect) | references/orchestrate.md:55-71 | mode | 105 | KEEP | 20 | The CLI lets a group go `completed` while children are still `backlog` (verified), so the prose is the only guard. The backlog→active→completed note prevents a rejected move. | 0 |
| 204 | C63 | Escalated-findings scan at plan scope | references/plan-start.md:41-44 | mode | 45 | KEEP | 20 | User-agreed (#48). Closes the loop for build-mode escalations. | 0 |
| 205 | C64 | status.md procedure | references/status.md | mode | 115 | KEEP | 20 | Prior #47 compression applied cleanly. Only the glob fix in C54 remains. | 0 |
| 206 | C65 | Growth-loop core (prototype hook, push-back, Design It Twice, terminology, watch-the-doc, resolve, single writer, doc-driven, exit criteria) | references/plan-grow-doc.md:28-87 | mode (every plan turn) | ~430 | KEEP | 20 | Each paragraph changes behaviour: user doc edits count as answers, the `observed_specs` wiring, do-not-build needs consent, and the exit condition is defined. | 0 |
| 207 | C66 | Setup/verify eval scripts | evals/setup-change-eval.sh; verify-change-eval.sh | — | 2,843 | KEEP | 20 | Deterministic fixtures and mechanical checks. The group fixture already uses sibling-slug `depends_on`, which is correct. | 0 |
| 208 | C67 | worktree-merge-destination.sh | tests/worktree-merge-destination.sh | — | 198 | KEEP | 20 | Guards target-branch safety. Extend it if C48 lands. | 0 |
| 209 | R80 | fix.md Companion plan | varde-review/references/fix.md:53-64 | mode | 90 | KEEP | 20 | Non-default paths and the nested-plan completion rule; the plan lifecycle depends on them. | 0 |
| 210 | R81 | fix.md Workflow steps | varde-review/references/fix.md:13-30 | mode | 145 | KEEP | 20 | Dirty-tree rule differs by mode; category order from the review.md table. Load-bearing. | 0 |
| 211 | R82 | spec.md steps 4, 5, 7 (orphans, index, report) | varde-docs/references/spec.md:20-25,36-37 | mode | 80 | KEEP | 20 | Deletion is confined and conditioned on confirmed orphans; this is a safety rule. | 0 |
| 212 | R83 | scan-rule-format core (fields, pattern syntax, SQL surface, tests, scopes) | varde-review/references/scan-rule-format.md:1-111,120-166 | rare | 900 | KEEP | 20 | Rarely loaded (rule edits only). Spot-checked claims hold: severity is case-insensitive (rules/mod.rs:85), unknown fields are ignored (:525), a rewrite with an unknown capture is rejected, rules_seed/rules_remove `--user`, `VARDE_USER_RULES_DIR`, and the build `index.db` path in `--help`. | 0 |
| 213 | R84 | scan-author workflow steps 1-5, 7-8 | varde-review/references/scan-author.md:6-24,30-35 | rare | 180 | KEEP | 20 | Example rule ids exist in `rules_list` (hardcoded-credential-*, function-complexity-gate, circular-import); the per-language test caveat is non-default. | 0 |
| 214 | R85 | reviewing.md When it applies / Loading / Instruction quality / Token economy checklists | varde-agent-doc-authoring/references/reviewing.md:30-71 | mode | 290 | KEEP | 20 | Compact checklists; the duplicates are handled in rows above. | 0 |
| 215 | R86 | workflow-skills.md Entry dispatch + Workflow | varde-agent-doc-authoring/references/workflow-skills.md:5-18 | rare | 108 | KEEP | 20 | The non-default rules: the dispatch cell names the discovery method; inline only gates and short checklists. | 0 |
| 216 | K5 | knowledge CLI ref Fallback rule (pinned ×2 by vendored-copies) | varde-workflow-cli.md:33-43 | mode | 78 | KEEP | 20 | The skill ships to users without this repo's AGENTS.md, so the retry-once-on-sandbox rule and "`ok:false` is a result" must travel with it. | 0 |
| 217 | K15 | friction frontmatter, status lifecycle, occurrence line | note-friction.md:28-48 | mode | 96 | KEEP | 20 | `head_sha` feeds reconcile's `git log <sha>..HEAD`. Status ownership (reconcile vs distill) prevents fights. | 0 |
| 218 | K20 | reflect-handoff Links table | reflect-handoff.md:8-16 | mode | 60 | KEEP | 20 | The `kind` values drive the resume-time "modified" labels. | 0 |
| 219 | K27 | reconcile Friction items | reconcile.md:22-30 | mode | 78 | KEEP | 20 | `git log <head_sha>..HEAD -- <path>` is the concrete check. | 0 |
| 220 | E12 | varde-code.md preamble (pinned ×4) | varde-code.md:1-9 | rare | 69 | KEEP | 20 | "Fast enough that no target is too small" stops agents skipping the index. `ok`/`data.error` verified. | 0 |
| 221 | E14 | varde-code.md Fallback rule (pinned) | varde-code.md:37-42 | rare | 38 | KEEP | 20 | "Grep-check implausible results (zero dependents)" is the non-default part. | 0 |
| 222 | P15 | logic "Stay a prototype" | logic-track.md:36-40 | mode | 33 | KEEP | 20 | "No tests" and "in-memory" work against agent instinct. | 0 |
| 223 | P16 | visual vs logic as separate files | varde-prototype/references/*-track.md | mode | 663 | KEEP | 20 | The tracks are mutually exclusive and share almost no rules, so each run loads one. | 0 |
| 224 | I25 | tests/install-catalogue.sh | skills/tests/install-catalogue.sh | — | 425 | KEEP | 20 | Tests the destructive path (marker-guarded removal). #134 trims applied. | 0 |
| 225 | K25 | reconcile shared rules | varde-knowledge/references/reconcile.md:1-13 | mode | 104 | KEEP (trim) | 18 | Evidence-or-no-edit plus confirm-first is the mode (eval 7). Cut the rationale "another author may own the record". | 7 |
| 226 | K7 | note.md Knowledge folder (type-first path, reserved files) | note.md:12-26 | mode | 84 | KEEP | 18 | A project contract, checked by `lint --okf` and eval 1. Trim the default-behaviour line "Create missing folders on first write." | 6 |
| 227 | P5 | Workflow steps 2-4 (rounds, close with liftable module, lessons) | SKILL.md:33-38 | trigger | 50 | KEEP | 18 | Naming the liftable module is the payoff of the logic track. | 0 |
| 228 | R87 | review eval 2 vs SKILL.md:8 | varde-review/SKILL.md:8; evals.json (id 2) | trigger | 11 | FIX | 15 | **Contradiction.** SKILL.md says "Changing source requires an explicit request". The eval prompt *is* an explicit request ("just go ahead and fix"), yet it expects no edits. Say what the eval expects: "Report mode never edits source, even when asked to fix; offer `fix` mode once findings are written." | -6 |
| 229 | K17 | reflect.md step 2 "Keep the paths." | reflect.md:17 | mode | 3 | FIX | 15 | Ambiguous (keep which paths, where?). The intent is to hand paths to step 3 and the report. Replace with: "Note the paths for step 3." | 0 |
| 230 | R95 | specification.md frontmatter table + Validation | varde-agent-doc-authoring/references/specification.md:3-9,19-24 | rare | 110 | KEEP | 15 | Matches the validator (NAME_RE, 1024/500 limits). Compress :11-13 to "Optional: `license`, `compatibility` (≤500 chars), `metadata` (string→string map)." (−15) | 15 |
| 231 | C68 | Decomposition core (breakdown fields, profile authority, size check, failing shapes, task ids) | references/build-decomposition.md:22-35, 43-79 | mode | ~420 | KEEP | 15 | Global task-id uniqueness looks costly but is justified: worktree branch `worktree/<task-id>` collides across plans (create exits 3). The size check is what keeps cheap executors bounded. | 0 |
| 232 | C69 | build-plan starting-action table + posture table | references/build-plan.md:3-12, 45-52 | mode | ~235 | KEEP | 15 | Routes ad-hoc vs named vs single-outcome plans, including the executor-safe single-task row. | 0 |
| 233 | C70 | build-plan-run git scope, failure states, selection messages, Retry/Skip/Abort | references/build-plan-run.md:8-38, 45-53 | mode | ~300 | KEEP | 15 | Never push, never `reset --hard`, unattended stop semantics. Kept per #52. | 0 |
| 234 | C71 | Dispatch strategies table + executor briefing/ownership | references/build-dispatch.md:26-48 | mode | ~165 | KEEP | 15 | The ≤3 cap, inline only as fallback, and the orchestrator/executor file ownership split carry the user's cost model. | 0 |
| 235 | C72 | Worktree ownership + merge-before-showing | references/worktree.md:1-14 | rare | 101 | KEEP | 15 | `created=false` → never merge or clean up is not derivable and matches the script. | 0 |
| 236 | C73 | Orchestrate route/discover/delegate/resume | references/orchestrate.md:1-20, 38-53 | mode | ~190 | KEEP | 15 | Stop on first failure, run no later child, merge nothing. Eval 5 covers discovery. | 0 |
| 237 | C74 | Behavioural evals 1-5, 8-10, 12-14 | evals/evals.json | — | ~1,200 | KEEP | 15 | They cover status, plan seed, micro, verify, orchestrate discovery, named build, debug fix/diagnose, explicit build, resume drafts, and the executor route. The prior audit's asks (#116, #159) landed as 13 and 14. | 0 |
| 238 | C75 | Parallel-wave scheduler test | tests/parallel-wave-scheduler.sh | — | 835 | KEEP | 15 | Covers the conflict, empty-radius, cap, no-CLI, cycle, and template-parse rules. Passes. | 0 |
| 239 | C76 | Worktree create/cleanup scripts | scripts/worktree-create.sh, worktree-cleanup.sh | — | 510 | KEEP | 15 | Pinned base SHA, `info/exclude` instead of a tracked .gitignore, and nested-worktree detection. | 0 |
| 240 | R88 | fix.md Human triage table + reply grammar | varde-review/references/fix.md:32-51 | mode | 140 | KEEP | 15 | A template plus one-message reply grammar; overrides the harness question-tool default the user prefers. | 0 |
| 241 | R89 | refresh.md steps 2-4 | varde-docs/references/refresh.md:16-31 | mode | 140 | KEEP | 15 | Proposal/approval loop and hand-written-section preservation; eval 2 depends on it. | 0 |
| 242 | R90 | spec-format Acceptance criteria + Index | varde-docs/references/spec-format.md:79-93 | mode | 94 | KEEP | 15 | The GWT form, the `tests_for_file` note, and `source_commit` as the index's only field (index.md is an OKF-reserved filename, verified in okf-core bundle.rs). | 0 |
| 243 | R91 | Memory-location gotcha (review, docs) | varde-review/SKILL.md:22; varde-docs/SKILL.md:20-24 | trigger | 39 | KEEP | 15 | Pinned by vendored-copies.sh; resolution verified against `varde-workflow paths --json` (`data.working`/`data.knowledge`). | 0 |
| 244 | R92 | review `varde-code.md` preamble + Fallback + Review scoping | varde-review/references/varde-code.md:1-29,50-55 | mode | 170 | KEEP | 15 | Contract sections plus the one batch call every review uses; inputs verified. | 0 |
| 245 | R93 | simplify Principles + steps 3-6 | varde-review/references/simplify.md:5-10,19-38 | mode (every build task) | 250 | KEEP | 15 | Scope to `-U0` ranges, keep signatures of externally used symbols, snapshot restore instead of `git checkout`. Runs every build task. | 0 |
| 246 | R94 | report-categories per-category When/Check/Severity | varde-review/references/report-categories.md:21-99 | mode | 510 | KEEP | 15 | Each Check line is a non-default verification (writer has a runtime reader, trace input to sink, every writer compared). Already compressed by the prior audit. | 0 |
| 247 | R96 | doc-authoring Workflow steps 1-3 + gotcha 2 | varde-agent-doc-authoring/SKILL.md:21-23,29 | trigger | 60 | KEEP | 15 | Validator command with the sandbox prefix (verified: runs OK on all 7 skills). | 0 |
| 248 | K9 | note.md body by type + decision template | note.md:58-74 | mode | 47 | KEEP | 15 | The one template that shapes recall. | 0 |
| 249 | K29 | reflect-distill classify (Add / Tighten / Simplify-remove) | reflect-distill.md:27-33 | rare | 71 | KEEP | 15 | "Propose the deletion, not a rewording" works against the default of adding rules. | 0 |
| 250 | E3 | explore gotcha: no plans/code/prototypes unless named | varde-explore/SKILL.md:22-23 | trigger | 19 | KEEP | 15 | Eval 4. It holds the sibling boundary. | 0 |
| 251 | E5 | target-shape table + testable ambiguity rule | explain.md:10-20 | mode | 100 | KEEP | 15 | User-agreed (#83). `git rev-parse --verify` makes the rule testable. | 0 |
| 252 | P7 | throwaway gotcha → varde-change | SKILL.md:47-48 | trigger | 17 | KEEP | 15 | Eval 2. | 0 |
| 253 | P8 | visual intro: reuse design tokens, minimal interaction | visual-track.md:1-7 | mode | 48 | KEEP | 15 | Stops generic-looking mockups. | 0 |
| 254 | I24 | tests/vendored-copies.sh manifest + memory-paragraph pin | tests/vendored-copies.sh:31-34 | — | ~460 | KEEP | 15 | It caught real drift (843ecba). Needs a P6 update if applied. | 0 |

### Band E — core, non-removable (<15)

| # | ID | Item | Where | Load | Words | Verdict | Score | Case against → fix | Saved |
|---:|---|---|---|---|---:|---|---:|---|---:|
| 255 | K19 | reflect.md order (friction → knowledge → handoff → reconcile-on-ask) | reflect.md:8-27 | mode | 144 | KEEP | 12 | Prior #129. Writing knowledge before the handoff lets the handoff link to it. Eval 5. | 0 |
| 256 | C80 | Execution cycle core (drift, profiles, tautology ban, out-of-scope write = blocker, UI rule, completion steps) | references/build-execution.md:14-70 | mode (every executor) | ~420 | KEEP | 10 | The executor contract. The cheaper model needs these explicit. Minor: :47 repeats :38-39 (cut ~10 words). | 10 |
| 257 | C77 | Plan Self-review + Finalize (fresh-eyes subagent, completeness check, validate, check-ignore) | references/plan-fundamentals.md:15-50 | mode | ~300 | KEEP | 10 | One cheap subagent call per plan catches unstated assumptions. "Silence on a line the user never saw is not confirmation" is not a model default. | 0 |
| 258 | C78 | External interface check | references/plan-fundamentals.md:6-13 | mode | 64 | KEEP | 10 | Consumer discovery with `dependents`/`blast_radius`. The wording fix is in C43. | 0 |
| 259 | C79 | Acceptance-criteria review rules | references/plan-acceptance-criteria.md:8-21 | mode | 134 | KEEP | 10 | Prefer `assert:`, self-grading bias, "stop with a blocker rather than weakening". | 0 |
| 260 | C81 | Debug evidence contract + Phases 1-5 | references/build-posture-debug.md:1-80 | mode | ~590 | KEEP | 10 | User-reduced (#51). Every gate is load-bearing and covered by evals 9 and 10. | 0 |
| 261 | C82 | Verify steps + UI paragraph | references/verify.md:7-48 | mode | ~285 | KEEP | 10 | Checkbox-is-a-claim, exact assertion, `unavailable` vs `failed`. Eval 4 covers these. | 0 |
| 262 | C83 | plan-start first turn steps 1-4 | references/plan-start.md:14-29 | mode | ~170 | KEEP | 10 | Seed-before-asking and the draft-id scheme feed plan-resume. Eval 2 covers this. | 0 |
| 263 | C84 | interview.md rules + menu format | references/interview.md:5-29 | mode | 134 | KEEP | 10 | Direct evidence in user memory (one topic per turn, inline menus). | 0 |
| 264 | C85 | varde-code.md catalogue + fallback | references/varde-code.md (except :30) | mode | ~340 | KEEP | 10 | Every argument name was verified against `--help` (`query`, `filePath`, `name`, `filePaths`, `includeBody`, `diffMode`/`range`, `calls[].mode`, `--format text`). The preamble and fallback are pinned by vendored-copies.sh. | 0 |
| 265 | C86 | Resolver core | scripts/resolve-execution-wave.py | — | ~780 | KEEP | 10 | A deterministic independence check beats a cheap model reasoning about disjointness. The docstring matches the prose. | 0 |
| 266 | C87 | PLAN-TEMPLATE body + writing style; TASK-TEMPLATE body | assets/PLAN-TEMPLATE.md; assets/TASK-TEMPLATE.md | mode | ~400 | KEEP | 10 | The structured-spec style line and the `assert:`/`retrieve:` shapes drive everything downstream. | 0 |
| 267 | R97 | varde-docs description | varde-docs/SKILL.md:3 | always | 22 | KEEP | 10 | Specific, with a `Not for` sibling boundary. | 0 |
| 268 | R98 | varde-docs routing table | varde-docs/SKILL.md:8-13 | trigger | 34 | KEEP | 10 | Two routes, minimal. | 0 |
| 269 | R99 | scan.md steps 2-5, 7-8 (ok vs analysis/gate, triage from real code) | varde-review/references/scan.md:20-47,57-60 | mode | 260 | KEEP | 10 | `ok:true` establishes neither status (matches `scan --help`); triage from code, not template text. Non-default and load-bearing. | 0 |
| 270 | R100 | fix-pass steps 1-3, 5-10 | varde-review/references/fix-pass.md:3-30 | mode | 220 | KEEP | 10 | Per-finding `$TMPDIR` isolation and the build `assert:` rerun; eval 4 depends on it. | 0 |
| 271 | R101 | fix-pass gate conditions (spec conflict, scope creep, human-only) | varde-review/references/fix-pass.md:53-62 | mode | 90 | KEEP | 10 | Keeps a build from auto-applying semantics changes. | 0 |
| 272 | R102 | report-categories always-triage list | varde-review/references/report-categories.md:13-19 | mode | 75 | KEEP | 10 | The fix-pass human-only gate depends on it. | 0 |
| 273 | R103 | report-format folder layout, field tables, field rules | varde-review/references/report-format.md:3-10,55-82 | mode | 225 | KEEP | 10 | fix mode parses these literally. | 0 |
| 274 | R104 | report.md steps 2-6, 8-9 + Split | varde-review/references/report.md:28-49,55-63,68-79 | mode | 400 | KEEP | 10 | 60k budget with at most 3 report-only chunks (fits the 3-subagent cap), spec-source precedence, verify high/critical. Core. | 0 |
| 275 | R105 | report.md Choose the breadth | varde-review/references/report.md:3-12 | mode | 78 | KEEP | 10 | Default three categories vs full vs single; the `ask, don't guess` rule. | 0 |
| 276 | R106 | reviewing.md Adversarial inventory core (:8-20) | varde-agent-doc-authoring/references/reviewing.md:6-20 | mode | 105 | KEEP | 10 | The load-weighted cost/benefit test; eval 1 depends on it. | 0 |
| 277 | R107 | doc-authoring description | varde-agent-doc-authoring/SKILL.md:3 | always | 27 | KEEP | 10 | Scoped with a `Not for` boundary against varde-docs. | 0 |
| 278 | R108 | validate-frontmatter.py | varde-agent-doc-authoring/scripts/validate-frontmatter.py | — | 800 | KEEP | 10 | Used by tests/frontmatter.sh and step 3; the docstring now matches NAME_RE (#158 applied). | 0 |
| 279 | K8 | note.md Write notes: frontmatter + provenance | note.md:28-56 | mode | 131 | KEEP | 10 | `generated`, `verified`, and `reconciled` as separate facts is non-default and is tested by eval 2. | 0 |
| 280 | K10 | note.md deprecate, don't delete | note.md:76-78 | mode | 34 | KEEP | 10 | Keeps links resolving. Eval 3. | 0 |
| 281 | K24 | handoff Resume | reflect-handoff.md:71-83 | mode | 109 | KEEP (+FIX) | 10 | Prior #154. Minor fix at :76: "Ask which to resume" should apply only when more than one candidate exists; otherwise every single-handoff resume costs a turn. | 0 |
| 282 | K33 | memory-location gotcha (pinned ×5) | varde-knowledge/SKILL.md:24 | trigger | 39 | KEEP | 10 | Verified against `varde-workflow paths --json` (`data.working`/`data.knowledge`). | 0 |
| 283 | P2 | track table + ambiguity line | varde-prototype/SKILL.md:8-15 | trigger | 62 | KEEP | 10 | The routing core. #137 was applied cleanly. | 0 |
| 284 | I7 | README Benchmark checks | README.md:133-146 | rare | 49 | KEEP | 10 | Accurate: every test is tracked 100755, and the runner fails non-executables. | 0 |
| 285 | I27 | tests/benchmark-foundation.sh | skills/tests/benchmark-foundation.sh | — | 98 | KEEP | 10 | Auto-discovery ends hand-registered tests. | 0 |
| 286 | C88 | SKILL.md mode table + entry routing | SKILL.md:8-26 | trigger | ~150 | KEEP | 8 | Compact. Precedence is tested by evals 6 and 9-12. | 0 |
| 287 | P13 | logic pure module + shell sections + domain language + coverage | logic-track.md:11-29 | mode | 191 | KEEP | 8 | The pure-module/DOM split, guided scenarios, and "an action that should be illegal" are the track's value. Eval 3. | 0 |
| 288 | I11 | check-refs.sh invariants (flat layout, single-line description, script and reference reachability, retired names) | skills/check-refs.sh | — | 992 | KEEP | 8 | Guards AGENTS.md rule 1 on what users receive. Passes in the sandbox (the #140 fix is applied). | 0 |
| 289 | C89 | Workflow state table + no-shortcut rule | references/varde-workflow-cli.md:15-40 | mode | 175 | KEEP | 5 | Matches workflow_schema.rs:91-112 exactly. It is the source for the eval state guard and prevents `draft`/`backlog`-task errors. | 0 |
| 290 | C90 | `<working>`/`<knowledge>` resolution gotcha | SKILL.md:30-34 | trigger | 45 | KEEP | 5 | Verified: `varde-workflow paths --json` → `data.working`/`data.knowledge`. It matters here because `<working>` is outside the repo on this machine. | 0 |
| 291 | C91 | Frontmatter description | SKILL.md:3 | always | 22 | KEEP | 5 | Applied per #89. Outcome verbs plus a sibling exclusion. | 0 |
| 292 | R109 | spec-format Generated block (sentinels, Notes tail) | varde-docs/references/spec-format.md:40-56 | mode | 81 | KEEP | 5 | Byte-preservation and drift rules; nothing else prevents clobbering hand-written notes. | 0 |
| 293 | R110 | spec-format provenance + `source_hash` recipe | varde-docs/references/spec-format.md:6-38 | mode | 163 | KEEP | 5 | Verified: it matches `validate_specification` in workflow-cli/varde-workflow/src/conclusion.rs:505-541 (sorted path+hash concatenated, blob-hashed). Exact recipe required. | 0 |
| 294 | R111 | report-format finding template | varde-review/references/report-format.md:12-35 | mode | 70 | KEEP | 5 | Literal template for machine-read output. | 0 |
| 295 | R112 | report-format Finding discipline (minus Calibration) | varde-review/references/report-format.md:37-51 | mode | 127 | KEEP | 5 | The evidence bar (enumerate the set, sample boundaries, show the check) is non-default and cuts false positives. | 0 |
| 296 | R113 | varde-review routing table | varde-review/SKILL.md:10-18 | trigger | 91 | KEEP | 5 | Five distinct modes with no overlap; simplify vs report is clearly split by findings-file vs inline. | 0 |
| 297 | R114 | varde-review description | varde-review/SKILL.md:3 | always | 25 | KEEP | 5 | All five modes named in user terms. | 0 |
| 298 | R115 | authoring.md "Use project evidence" (incl. no-source interview) | varde-agent-doc-authoring/references/authoring.md:3-20 | mode | 149 | KEEP | 5 | The one strongly non-default authoring behavior (decline to restate model defaults); eval 2 depends on it. | 0 |
| 299 | K28 | reflect-distill gate + two-occurrence threshold | reflect-distill.md:1-22 | rare | 170 | KEEP | 5 | Stops an agent from editing its own skills unapproved, and stops rule bloat. Prior #130/#67. | 0 |
| 300 | K31 | knowledge SKILL routing table | varde-knowledge/SKILL.md:8-17 | trigger | 101 | KEEP | 5 | The dispatch core. The #119 distill row is correctly present. | 0 |
| 301 | D1 | Seven descriptions as a set | skills/*/SKILL.md:3 | always | 172 | KEEP | 5 | Distinct and paired. explore↔prototype, docs↔doc-authoring, and change↔(explore, review) each carry mutual "Not for" clauses. knowledge excludes plans and findings. Installed text equals the repo in three harnesses; pi was unverifiable under the sandbox. Only E1 and P1 trims are proposed. | 0 |
| 302 | I8 | install.sh catalogue, RETIRED, marker-guarded removal, dry run | skills/install.sh | — | ~500 | KEEP | 5 | The only wiring path. Tested. | 0 |

## Resolutions (walkthrough)

One entry per item, in rank order. **Clear** = one answer that preserves functionality. **Decided** = the user chose among options.

- **#1 C1 — Clear.** Delete `plan-grow-doc.md:12-18` (the old two-bullet version under `## Routing unknowns`); keep the heading and the compressed rule at :20-25.
- **#2 R1 — Clear.** Delete the "Spec scoping" section from `varde-docs/references/varde-code.md:16-23`. Refresh never scopes specs, and the `map_file` bucketing it teaches is wrong (#9).
- **#3 K1 — Clear.** Delete "Legacy artifacts" (`varde-knowledge/references/varde-workflow-cli.md:28-31`) and "legacy migration" at :4. Follow-up outside `skills/`: `varde-workflow inspect` reporting valid OKF notes as `migration_required` is a workflow-cli bug.
- **#4 C2 — Clear.** Delete the `inspect`/`migrate` sentence at `varde-change/references/varde-workflow-cli.md:44-45`. Same workflow-cli follow-up: template-made plans validate as `legacy: true`.

- **#5 R4 — Clear.** Delete `specification.md` "Loading and references" (:15-17). The rule lives in authoring.md; the 500-line budget is enforced by `validate-frontmatter.py`.
- **#6 R2 — Clear.** Delete the `optimizing-descriptions.md` preamble (:3-4).
- **#7 R3 — Clear.** Delete `authoring.md` "Write skill metadata and descriptions" (:46-49); the SKILL.md table already routes both files.
- **#8 R5 — Clear.** Delete the `workflow-skills.md` opener line (:3).
- **#9 R6 — Clear.** Replace `spec-plan.md` "Incremental" section (steps 1-4) with: "Recompute every document's provenance; a mismatch is stale. For missing domains, list `git diff --name-only <source_commit>..HEAD` plus untracked files; a file in no document's `sources` is a candidate missing domain. Diff from `source_commit`, never `source_hash`; an unresolvable watermark means a Full scan." Retitle it "Incremental, with a `source_commit`"; Full scan's "Without `varde-code` or" becomes "Without".
- **#10 C3 — Clear.** In `tests/change-output-eval-fixtures.sh`, delete the prose greps (:72-77), the stale comment (:78-82), and the assertion-count `jq` checks (:265-275). Keep the seeded-fixture tests and the state guard.
- **#11 C4 — Clear.** Delete `build-dispatch.md` "Commit-per-task" (:50-53); build-plan-run.md:10-12 and build-execution.md own the rule.
- **#12 R7 — Clear.** Delete the two preamble lines in `varde-agent-doc-authoring/SKILL.md` (:8-9).

- **#13 R9 — Clear.** Delete `spec.md` step 1 "Work in place" (:9-10) and renumber.
- **#14 R8 — Clear.** Delete `varde-docs/SKILL.md:15-16` ("Read only the reference… supporting files"), matching varde-review.
- **#15 R10 — Clear.** Delete `report.md:65-67`.
- **#16 C5 — Clear.** Remove "or answer a readiness question" from `varde-change/SKILL.md:22` and delete `plan-start.md:31-32`. No "readiness sections" exist; a new-idea readiness question still routes to plan-start, an existing-plan one to status.
- **#17 C6 — Clear.** Delete the last sentence of `build-plan-run.md` step 1 (:43-44); build-dispatch owns resume evidence.
- **#18 R11 — Clear.** Delete the `rules_list` parenthetical at `scan.md:14`.
- **#19 C7 — Clear.** Fold `build-research-task.md` into build-execution.md "Choose the task kind" as: "`kind: research`: write the `creates` doc from primary sources outside the repo, citing each claim (URL, spec section, file:line); a decision ends with one recommendation. Then run Completion." Delete the file; point TASK-TEMPLATE.md:10 at build-execution.md.
- **#20 R12 — Clear.** Replace `refresh.md` step 1's pointer (:13-15) with: "Many `docs/` files and `varde-code` on PATH → `varde-code context_pack --json '{\"repoRoot\":…,\"query\":\"<doc subject>\"}'` maps each doc to source." Drop "Write changes with Write/Edit". The varde-code.md pointer moves to spec.md (see #2/#128/#169).
- **#21 C11 — Clear.** In `build-plan.md` step 4 (:39-41), replace "present the breakdown… unattended named-plan run" with "per `references/build-decomposition.md`", which owns the pause rule.
- **#22 C10 — Clear.** Delete `build-plan.md:42-43`; the table row at :10 states the refactor-posture rule.

- **#23 R13 — Clear.** Delete `refresh.md` "Inputs" (:6-9).
- **#24 R16 — Clear.** Delete the second sentence of `reviewing.md:62-63` ("Confirm harness loading… always loaded"); authoring.md:24-26 owns it.
- **#25 R15 — Clear.** Delete `report-format.md:63-64`.
- **#26 C12 — Clear.** Delete `interview.md:3`.
- **#27 R17 — Clear.** Delete `simplify.md:10-11`.
- **#28 R18 — Clear.** Delete `varde-review/references/varde-code.md:31`.
- **#29 E6 — Clear.** Delete `explain.md:24` step 1 and renumber.
- **#30 R14 — Clear.** Drop the `docs:v1` assertion from varde-docs eval 2.
- **#31 C8 — Clear.** Delete `references/build.md`. Replace `varde-change/SKILL.md:24` with three rows, executor row first: "One task file assigned by an orchestrator (executor)" → build-execution.md; "A single concrete behavior whose check result you can state before editing" → build-micro-change.md; "A plan, ad-hoc change, refactor, or spike" → build-plan.md. Move `execution=<auto|serial|inline>` (default `auto`) to build-plan.md step 3.
- **#32 C9 — Clear.** Replace `build-micro-change.md` body with: "Only for one concrete behavior whose check result you can state before editing; otherwise use `build-plan.md`. Inspect the target and its narrowest check together (one `varde-code batch` for symbols + covering tests when several files matter). State the check and expected result, edit only that behavior, run it, compare, and report files and evidence. No plans, tasks, worktrees, handoffs, or commits unless asked."
- **#33 C13 — Clear.** `plan-grow-doc.md:73-75` → "**Ask** the highest-value Open Question per `references/interview.md`, solution-shape questions before spelling ones."

- **#34 R19 — Clear.** Fold `optimizing-descriptions.md` into `specification.md` (the `description` row plus a short "Description wording" subsection: outcome verbs, `Not for <sibling>`, one double-quoted line). Delete the file; route "Improve triggering" in SKILL.md:17 to specification.md; fix the eval-tools README pointer (#126).
- **#35 E8 — Clear.** Delete explore `varde-code.md` "When to use it" (:11-14).
- **#36 C14 — Clear.** Delete `build-plan.md:63-64`; keep the plan-wide vs task blocker bullet.
- **#37 R21 — Clear.** Delete `fix-pass.md:32-33`.
- **#38 C16 — Clear.** Delete `map_path` from varde-change `varde-code.md:30`.
- **#39 P4 — Clear.** Trim prototype SKILL.md step 1 (:28-29) to the slug, storage path, and "ask only if that path exists".
- **#40 R22 — Clear.** Drop the "creates no worktree" assertion and "in the current checkout" from docs eval 1.
- **#41 C15 — Clear.** Inline `build-edge-cases.md` under decomposition's trigger bullets (:7-15): wide refactor = expand, N migrate batches, contract, plus an integrate task if batches can't stay green; deletion = the three greps. Delete the file.
- **#42 R20 — Clear.** `fix-pass.md` step 4 → "In build mode, run the gate below. On rejection, relabel `triage`, add `**Escalated:**` after `Location` (values: report-format), leave `Disposition:` blank, and move on." Delete :64-70.
- **#43 K2 — Clear.** Knowledge CLI ref preamble (:1-7) → "Optional; adds ranked search and lint over the same files. Write notes with Write/Edit whether or not it is installed." Keep the pinned Fallback rule.
- **#44 R24 — Clear.** `authoring.md:34-39` → "Bundle a script only to replace repeated parsing or validation; name its exact skill-root-relative invocation where it runs, and pin dependencies inline (PEP 723)."

- **#45 R23 — Clear.** doc-authoring SKILL.md:17 "Improve triggering" row → `| Improve triggering | specification.md | — |` (after #34). Strip `references/` from all table cells.
- **#46 C19 — Clear.** `plan-start.md:36-39` → "Follow plan-grow-doc every turn until its exit criteria pass, then plan-fundamentals Finalize."
- **#47 C17 — Clear.** Delete the "outside repo = ignored / plain mv" asides at `build-plan.md:30-31` and `plan-fundamentals.md:27-28`; SKILL.md:33-34 owns it.
- **#48 C18 — Clear.** Delete the `command -v` preamble in varde-change `varde-workflow-cli.md:3-7`.
- **#49 R27 — Clear.** Delete `varde-review/references/varde-code.md:47-48`.
- **#50 R28 — Clear.** Trim `refresh.md:3-4` to its first sentence.
- **#51 C20 — Clear.** Drop `parent:` from TASK-TEMPLATE.md:4 and from `setup-change-eval.sh` fixtures (:40, :112, :337). Nothing in workflow-cli or the resolver reads it.
- **#52 R25 — Clear.** `authoring.md:22-32,41-44` → "Confirm what the target harness loads at startup, on activation, and by reference. Make the entry file a run sheet; move detailed procedures, tables, and long templates to references, each with a load condition. A portable skill loads only its own files. Weight detail by load frequency; state each rule once (`reviewing.md`)." This also fixes the wrong "Token economy" cross-reference.
- **#53 R26 — Clear.** `workflow-skills.md:22-33` → three bullets: "Map one step to one self-contained reference; no step reads several cross-referencing peers." · "Split only to improve routing, never to hit a size target or by dropping directives." · "Premature completion (a step ends before its criterion is met): make completion observable; split by sequence only when later work repeatedly prompts early completion and evidence shows a handoff helps."

- **#54 K23 — Clear.** `reflect-handoff.md:67-69` → "The body does not restate frontmatter."
- **#55 P11 — Clear.** `visual-track.md:44-49` → "Each round: ask one targeted question, then write `v<N+1>.html`."
- **#56 K14 — Clear.** `note-friction.md:5-13` → "Record only a real event from this session (a command failed on stale docs, a workaround repeated, a tool surprised) in `<working>/friction/`. If there is none, say so and write nothing. A reusable technique is a `pattern` note instead. `source` is the current task or skill." `:24-26` → "One item per distinct event; a repeat of an open item is a new occurrence." Drop the body list at :39-40.
- **#57 R29 — Clear.** Keep the SKILL.md:28 gotcha; drop "A portable skill loads only its own files." from the #52 rewrite and the authoring.md:30-32 sentence.
- **#58 P1 — Clear.** Prototype description → "Build a throwaway HTML prototype to answer a design question — a visual mockup, or a clickable walkthrough of a state model or data shape. Not for comparing options in chat." Reinstall so the harness copies match.
- **#59 I10 — Clear.** Delete `portable_mode`, `preserve_skill_directory_modes`, their call at install.sh:198, and the 751 assertions in `tests/install-catalogue.sh`. `cp -p` already keeps file exec bits.

- **#60 C23 — Clear.** Remove the resolver's `--strategy` output mode (`resolve-execution-wave.py:17-18, 228-233`); switch the 8 test call sites to `jq -r .strategy`.
- **#61 R34 — Clear.** Delete the `scan-author.md:39-40` gotcha and its heading.
- **#62 R33 — Clear.** Delete `reviewing.md:42`; the SKILL.md gotcha and `check-refs.sh` cover it.
- **#63 R37 — Clear.** Delete `tests/agent-doc-authoring-evals.sh:22-32`; keep the fixture check and verifier smoke runs.
- **#64 I14 — Clear.** Delete `evaluating-skills.md:13-17,43-46` except "start with 2-3 cases incl. an edge case" and "review outputs before writing assertions".
- **#65 C21 — Clear.** `build-dispatch.md:15-24` → "Before each wave run `scripts/resolve-execution-wave.py --repo-root <checkout> <plan-dir>`; dispatch its `wave` with its `strategy`, report `blocked_by_dep`; exit 3 = cycle, a hard failure. Recalculate after each wave until every task is `done` or `blocked`."

- **#66 R31 — Clear.** `report-categories.md:7-12` → "**Auto-fix rule:** `auto-fix` only when the fix is precisely describable and mirrors a pattern already in the file or its siblings; otherwise `triage` (a standalone fix run skips it)."
- **#67 R35 — Clear.** `authoring.md:51-59` → "Avoid skills too small to use alone or too broad to select precisely. Cut generic background and stale environment facts; reserve prohibitions for hard boundaries, with the alternative."
- **#68 R40 — Clear.** `fix.md:3-11` → "Standalone is the default. `varde-change build` passes `mode=build` with `plan_context`; without it, stop (hard error). Read and edit the review's Markdown directly (format: report-format.md)." Move "malformed → report category + id, stop" into step 2 in place of "Validate quietly…".
- **#69 K22 — Clear.** `reflect-handoff.md:56` placeholder → "<one line per call: chose X over Y because Z (else the next session re-litigates it); link the plan, commit, or review for detail>".
- **#70 C22 — Clear.** `build-decomposition.md:37-41` → "Declare every written file in `modifies`/`creates`; if unknown, leave both empty (the task never runs in parallel)."
- **#71 R30 — Clear.** `fix-pass.md:49-51` → "Check against `plan_context` (goal, plan-level criteria, `creates`/`modifies`):"

- **#72 R32 — Clear.** Cut the `report-format.md:52-53` Calibration bullet; add "and its consumption path" to report.md step 1.
- **#73 C24 — Clear.** Every pinned "Fallback rule" copy → "Sandbox denial: retry once with escalated access, command unchanged; if that fails, or the CLI errors, use Read/Grep and Write/Edit and name the lost capability once." Update all vendored copies together so `tests/vendored-copies.sh` stays green.
- **#74 C25 — Clear.** In `orchestrate.md:21-22` keep "Stop until the user selects one."; drop the prohibition list after it.
- **#75 R39 — Clear.** Drop `simplify.md` step 1's load pointer (:15); step 4 keeps its pointer.
- **#76 E7 — Clear.** `explain.md:25-26` → "Load `references/varde-code.md` for unknown scope or several targets."
- **#77 E1 — Clear.** Explore description: "as a self-contained HTML explanation" → "as an HTML page". Reinstall.

- **#78 R36 — Clear.** Replace review eval 3 ("banana") with a build-mode escalation eval: a finding in the always-triage list gets `Escalated: human-only` and is not applied. It covers the fix-pass gate restructured in #42.

- **#79 K3 — Decided (A).** Cut lint from varde-knowledge: delete the `lint` line and its comment in `varde-workflow-cli.md:21-22`, drop "and lint" from the #43 preamble, and change "Search and lint merge…" to "Search merges…". No knowledge step runs it, and on this repo its orphan-link errors contradict note.md.

- **#80 C26 — Decided (A).** Convert change eval 7 to a real run: name the notifications group in the prompt, seed the `schema` child's task as `blocked` in `setup-change-eval.sh`, and run the group. Assert (in `verify-change-eval.sh`) that `delivery` is untouched, nothing merges, and the run reports the blocked child and stops.
- **#81 R38 — Clear.** Upgrade `verify-release-skill.sh` to run `validate-frontmatter.py` on the output and check `name: deploy-release` (assertion 3), instead of only checking that the file exists.
- **#82 K13 — Clear.** Merge `note.md` "When not to write" (:92-95) into :30 as one line: "Never store session narrative, tool output, logs, temporary task state, secrets, or unverified guesses; an obstacle is friction (`references/note-friction.md`)."
- **#83 P12 — Clear.** Cut "It opens by double-click and survives being emailed or committed as-is." from `logic-track.md:7-9`.

- **#84 E2 — Clear.** Delete explore `## Explore` (:15-18); row 1 → "| An open question — problem, design, tradeoff, or how code works (default) | Answer in chat. For structure (what exists, what depends on what, blast radius), load `references/varde-code.md`. |"
- **#85 I23 — Clear.** Cut `tests/vendored-copies.sh:4-19,28-30` to a 2-line purpose statement plus the manifest format.
- **#86 C29 — Clear.** `worktree.md:16-30` steps 1, 2, 4 → "Scripts (each has `--help`): `worktree-create.sh <id> [base]`, then edit only inside the printed `path=`; `worktree-merge.sh <id>` (exit 2 = nothing to merge, 3 = conflict → resolve below); `worktree-cleanup.sh <id>` only after merge exits 0." Keep step 3.
- **#87 I16 — Clear.** `evaluating-skills.md:62-69` → "Positive cases should pass above 0.5; expand to ~20 prompts × 3 runs only when misfires persist." Drop the holdout procedure.
- **#88 E9 — Clear.** `explain.md:27-34` → "Change: explain from the diff (PR: `gh pr diff <n>`, else fetch `pull/<n>/head` and diff against the PR's base, not the current checkout). Area: add notable commits from `git log --oneline -20 <path>` to Background."
- **#89 C30 — Clear.** `plan-grow-doc.md:3-9` → "Each later turn: research what the repo can answer (`references/varde-code.md`) and run plan-fundamentals' external interface check when consumers are touched."

- **#90 E4 — Clear.** `explain.md:1-8` → "Write a source-grounded explanation of a change or code area as one self-contained HTML file (inline CSS, no external assets). If the user asks for another format, answer in chat in that format instead."
- **#91 K12 — Clear.** `note.md:86-90` → "Write to the Personal vault (`~/.varde-workflow/`) only when asked; it is cross-project, so no client code, paths, or errors."
- **#92 P14 — Clear.** `logic-track.md:31-34` → "Each round, ask about one missing action, scenario, or state field."
- **#93 C28 — Clear.** Retitle `build-dispatch.md` "Dispatch tasks"; keep the one-sentence delegation rule.

- **#94 C27 — Decided (A).** Make the per-task simplify conditional. `build-execution.md` Completion step 1 → "When the task's diff exceeds ~40 changed lines or adds a new abstraction, run `varde-review simplify` scoped to its uncommitted changes." `build-dispatch.md:46` → "runs `execute → verify`, with `varde-review simplify` between them per build-execution Completion".
- **#95 C31 — Clear.** Delete `build-posture-debug.md:86` (checklist item 1) and :91-92 (refactor-candidate paragraph); both repeat Phase 5.

- **#96 K18 — Clear.** `reflect-handoff.md:3-6` intro → "Carries this session's context to the next. To resume, skip to **Resume a handoff**." In `reflect.md:18-23`, append "…unless the user asked for one" to "When nothing is left, write none", so an explicit handoff request is honoured.
- **#97 R41 — Clear.** Fold `report.md` "Choose the target" (:14-19) into step 1 (working tree vs `HEAD` or a named ref; clean tree → since nearest merge/tag, offer whole-codebase), then "state the resolved target and categories before reading code". Delete the heading.
- **#98 C35 — Clear.** `build-plan-finish.md:8-19` step 2 → "Findings → one `executor` round of `varde-review fix mode=build` (review ID + `plan_context`); no re-review. Escalated findings → one triage table in fix.md's format before acceptance checks (fix → `varde-review fix`, dismiss → reason, action-item → nested companion plan). Under orchestrate, return them instead of pausing."
- **#99 I2 — Clear.** In README "Two SKILL.md shapes" (:80-99), keep the two definitions and "don't convert for consistency alone"; drop the per-skill assignments (which also misfiled prototype).
- **#100 E10 — Clear.** `explain.md:41-47` table → Background: why it exists (change intent or git log). Intuition: how it works, analogies, invariants. Code/How It Works: walk the hunks per file with affected callers (change), or key files, entry points, and data flow (area). Drop "Found with Grep/Glob/Read".
- **#101 R43 — Clear.** `scan.md:48-56` step 6 → "For a `rewrite` rule with a straightforward match, run `scan --apply` (same JSON). It rewrites only after a complete scan and reports dirty files as `skipped-dirty`; tell the user, and use `--force` only with approval. Otherwise fix by hand in the file's style, using `remediation` as guidance."

- **#102 P3 — Clear.** Prototype SKILL.md:17-24 → "Ask one topic per turn (≤3 questions only as facets of one decision) as an inline numbered menu with a recommendation. Deliver a plain HTML file on disk and report its path first after every write; an `Artifact`/`mcp__visualize` preview is additive, never a substitute."
- **#103 C32 — Clear.** `plan-start.md:9-12` → "Batch discovery into one read-only call; include `varde-code context_pack` (feature terms) when available."
- **#104 C34 — Clear.** `verify.md:3-5` → "Read-only: never fix, change status, or tick criteria."
- **#105 K6 — Clear.** `note.md:3-10` → "Read a known note directly. To discover one, use ranked search per `references/varde-workflow-cli.md` (`--vault project` first) if `varde-workflow` is on PATH; else Grep/Glob `<knowledge>/` and name the lost ranked search once. Read a note in full only after search identifies it."
- **#106 R45 — Clear.** In `spec.md:26-35` step 6, drop the "no flows in Architecture" and "one `## Summary` between sentinels" bullets; keep the provenance recompute, link resolution, unverified-area marking, and lint.
- **#107 R47 — Clear.** `scan-author.md:25-29` step 6 → "Place it per scan-rule-format `## Scopes and precedence` (default repo scope; ask when unclear). To customize a built-in, `rules_seed` and edit in place, keeping its `id`."

- **#108 I15 — Clear.** Say "mechanical checks → `verification_script`" once in `evaluating-skills.md:35-41`; change :59 "Codex's read-proxy scoring" to "substring proxy".
- **#109 R42 — Clear.** `simplify.md:16-18` → "Edit in the current checkout, no worktree; if concurrent edits make it unsafe, stop and ask."
- **#110 C36 — Clear.** Drop the `docwatch list --json` confirmation step from `plan-docwatch.md:10-13`.
- **#111 R49 — Clear.** In `refresh.md:35-39` Constraints keep "Diagrams in Mermaid only"; delete "Write only prose grounded in the source"; the changelog line moves to varde-docs SKILL.md (see #140).
- **#112 K32 — Clear.** `varde-knowledge/SKILL.md:19-20` → "Read only that reference."
- **#113 C33 — Clear.** `build-plan.md:19-20` → load `references/interview.md` "when interactive".

- **#114 R44 — Clear.** `spec.md:12-19` step 3 → "…Brief each delegate with: `varde-code` path (if on PATH), domain, changed files, output path, `spec-format.md`." Drop the duplicated `get_symbol` guidance and the "detected in step 2" clause.
- **#115 R46 — Keep.** No change.
- **#116 R48 — Keep.** Minor fix: have `verify-self-audit.sh` require a top-level `.md` newer than the run start, not any existing one.
- **#117 I21 — Keep.** No change.
- **#118 K35 — Clear.** Knowledge evals: add `files` fixtures for evals 2-3 (the notes they edit), a `verification_script` for 1-3, and reword eval 6 to "propose a skill or doc change from repeated friction; mark items `promoted`", counting repeats on one item per reflect-distill.md:16-17.

- **#119 I19 — Decided (A).** Commit one ~20-prompt `queries.json` targeting sibling boundaries (explore/prototype, docs/doc-authoring, change/review, knowledge/change "wrap up"), with positive and near-miss negative cases. Run it manually after any description change (#58, #77); not wired into CI. Fixing #161 (`def fail`) becomes a prerequisite.

- **#120 R51 — Clear.** `reviewing.md:22-28` → "Report: top summary of highest-value changes; then `| # | Item | Location | Benefit | Cost | Evidence | Action |`, #1 = strongest cut, load-bearing last; include a `wc -w` baseline. On an edit's final pass, apply the tests without writing a report."
- **#121 R54 — Clear.** Trim `scan-rule-format.md:112-118` to the column list plus "base blocking policy on `certified` rows, not the persisted graph".
- **#122 C37 — Clear.** `plan-acceptance-criteria.md:3-6` → "Criteria are plan-level: true after ship, however build slices it."
- **#123 R52 — Clear.** `report.md:50-54` step 7 → "Append each finding to its category file (report-format.md) as you find it."
- **#124 K16 — Clear.** Cut "Each record type's procedure owns its format." from `reflect.md`.
- **#125 C39 — Clear.** Add one varde-change eval for plan Finalize: slug rename, `validate`, completeness check, plan stays `backlog`. Parallel-wave and resume evals stay out of scope.

- **#126 I13 — Clear.** In `eval-tools/README.md:7-9`, point query-set authoring to `evaluating-skills.md` "Trigger accuracy"; delete :13-14.
- **#127 C38 — Clear.** `build-plan-finish.md:34-39` → "Show the local diff. If this run created a worktree, offer Merge (default) or Stop per `references/worktree.md`. Commit the plan's status change when plan storage is tracked."
- **#128 R50 — Clear.** Drop "and provenance" from varde-docs `varde-code.md:13`.
- **#129 R53 — Clear.** Reword doc-authoring eval 2's structural-ambiguity assertion to grade what authoring.md:15-17 teaches (asks about environment, failures, and conventions before drafting).
- **#130 P17 — Clear.** Add a ~15-line prototype `verification_script`: `variant-*.html` exist, the switcher uses `<a href>`, variants contain no `<script`, and `logic.html` exists for logic runs.
- **#131 C40 — Keep.** No change.

- **#132 R55 — Keep.** No change.
- **#133 P6 — Clear.** Prototype SKILL.md:42-46 gotcha → "`<working>`: `varde-workflow paths --json` → `data.working`; else `$VARDE_WORKING_DIR`; else `memory-bank/working`. Outside the repo, use plain file ops." Remove prototype from the memory-paragraph pin in `tests/vendored-copies.sh` (5 → 4 files).
- **#134 E15 — Clear.** Apply prior #83: add a `setup_script` that builds a small git repo fixture (`src/core/auth/…`, a `payments` area plus a `payments` branch so eval 2's ambiguity is real, and a plain area for a new "auth" case). Delete the contradictory "After writing the file…" from eval 3.
- **#135 I22 — Keep.** Add the stderr-message assertion from #161.
- **#136 R60 — Clear.** Replace `spec-format.md:58-77` prose with a skeleton: `## Summary / ## Overview / ## Scope Boundary (owns|does-not-own) / ## Key Operations / ## Key Types / ## Invariants / ## Acceptance Criteria / ## Flow: <name>`, plus its 3 conditional rules.
- **#137 R59 — Clear.** doc-authoring SKILL.md:24 step 4 → "Final pass: `reviewing.md` checklists (skip Adversarial inventory) on the changed scope; check every changed pointer." Keeps prior #19's final pass, skips the unused report spec.

- **#138 K26 — Clear.** `reconcile.md:17-20` → keep only "A `reconciled.sha` far behind `HEAD` is a drift signal." (the `stale_after` date signal never fires).
- **#139 R57 — Clear.** Merge `scan.md` steps 1-2 → "Run `varde-code scan --json '{\"repoRoot\":\"<repo>\",\"severityThreshold\":\"error\"}'` (or `gateRules`; not both), without `--apply`."
- **#140 R56 — Clear.** Move "not CHANGELOGs, release notes, or external doc sites" into varde-docs SKILL.md's user-facing row; drop it from refresh Constraints.
- **#141 R58 — Clear.** Doc-authoring eval 3: "Workflow-type skill" → "an ordered numbered `## Workflow`".
- **#142 P9 — Keep (trim).** Cut "with semantic elements where the content supports them" from `visual-track.md`.
- **#143 C41 — Keep.** No change.

- **#144 C42 — Keep.** No change.
- **#145 R61 — Keep.** No change.
- **#146 R62 — Keep.** No change.
- **#147 E11 — Keep.** No change.
- **#148 I6 — Keep.** No change (user kept these in pass 1).
- **#149 R63 — Clear.** Add to `reviewing.md` Loading: "Fix fan-out by merging files, not by shortening prose." Keeps doc-authoring eval 1's two assertions grounded in taught text.

- **#150 C47 — Clear.** Add to `build-posture-debug.md:93`: "Standalone (no task file): commit only when asked."
- **#151 D2 — Clear (gated).** Leave the varde-review description alone until the #119 query set runs; add "Not for fixing a named bug." only if it shows change↔review misroutes.
- **#152 C45 — Clear.** `build-decomposition.md:76-77` → "Commit the initial task files once when plan storage is tracked."
- **#153 E13 — Clear.** Replace explore `varde-code.md:35` with "Pass `includeBody` only when bodies are needed."
- **#154 C43 — Clear.** `plan-fundamentals.md:11` "in the spec and AC" → "in Design and AC".
- **#155 C44 — Clear.** `build-execution.md:57-58` "outside `memory-bank/`" → "outside `<working>`/`<knowledge>`".

- **#156 C46 — Decided (B).** One commit per task everywhere. `build-posture-refactor.md:22-24` step 2 → "…apply, verify. On any regression, revert that change with `git checkout -- <files>` before the next one." Commit once at task completion per build-execution.md.

- **#157 C48 — Clear.** Follows from #156: `worktree-merge.sh` no longer auto-commits. A dirty worktree exits 5 ("uncommitted changes — the task did not complete; caller decides") without merging. List every exit-4 cause in usage (missing branch, unresolvable target, target mismatch, non-conflict merge failure), or split them out. Update `worktree.md` and `tests/worktree-merge-destination.sh`.
- **#158 R64 — Clear.** Cut "archive the review folder" from `fix.md:70-71`; `triage_status: complete` already marks a finished review, and nothing reads a review `status`.
- **#159 R65 — Clear.** `scan.md:7-9` → "Every finding ends fixed, not-real with a reason, or explicitly handed to the user."
- **#160 R66 — Clear.** Add a varde-docs eval: a spec with a hand-edited `## Notes` tail and a reversed sentinel pair; assert the Notes tail is byte-identical, the drifted section is left unchanged and reported, and `source_hash` is recomputed.

- **#161 I17 — Clear.** Restore `def fail(msg): print(msg, file=sys.stderr); sys.exit(1)` (matching the deleted original) in `run-evals.sh`'s Codex parser, and add a stderr-message assertion to `trigger-evals.sh` so a NameError can't pass again. Prerequisite for #119.
- **#162 I18 — Clear.** Apply pass-1 #96 as already agreed: `run_llm_judge` appends the sandbox's post-run file listing (paths, sizes, small text files inlined up to a cap) and the ordered stream-json tool-use list to the judge prompt. Then update `evaluating-skills.md:54`. The per-skill verification scripts (#118, #130) stay for the deterministic checks.
- **#163 R67 — Keep.** No change.
- **#164 R68 — Keep.** No change.
- **#165 R69 — Keep.** No change.
- **#166 R70 — Keep.** No change.

- **#167 R71 — Keep.** No change.
- **#168 R72 — Keep.** No change.
- **#169 R73 — Keep.** Add the pointer in `spec.md` step 3: "With `varde-code` on PATH, load `references/varde-code.md` (and `references/spec-format.md` for inline generation)." This completes #2/#20: the file moves from refresh to spec.
- **#170 R74 — Keep.** No change.
- **#171 K30 — Keep.** No change.
- **#172 I3 — Keep.** No change.

- **#173 I20 — Keep.** No change.
- **#174 I4 — Keep.** No change.
- **#175 R77 — Clear.** Move the "defect gone" block (`fix-pass.md:35-45`) into step 10 as its precondition: "10. Confirm the defect is gone before `Disposition: fix`: prefer a check that failed before the fix (existing test or step 8's `assert:` lines); one passing before and after proves nothing. With none, re-read the path against `Summary` and record 'confirmed by inspection'." Drop the "proves no regression" claim.
- **#176 R76 — Clear.** Same edit as #169, stated in `spec.md` generation: "Write each domain per `spec-format.md`; with `varde-code` on PATH, use `references/varde-code.md`."
- **#177 R75 — Clear.** Review eval 1 expected path → `<working>/reviews/<date>-<slug>/`.
- **#178 C49 — Keep.** No change.
- **#179 C50 — Keep.** Commit rule settled by #156.

- **#180–#186 (C51, R78, R79, K11, K34, I5, I26) — Keep.** No change beyond fixes already recorded (#10, #30, #40, #177).

- **#187 I12 — Clear.** `check-refs.sh:56`: pass `"$TMP"` (the install) to the pointer check instead of `$SCRIPT_DIR`, so unshipped `evals/` files can't satisfy a pointer. Drop "double-quoted" from :44.
- **#188 P10 — Keep (trim).** Pick N → "2–3 close variants (narrow) or 3–5 unrelated shapes (wide); default 3, max 5; state N." Drop step 4's "show the path".
- **#189 K21 — Keep (trim).** Cut "if in doubt, redact" and "Drop empty sections" from `reflect-handoff.md:18-39`.
- **#190 K4 — Keep.** No change beyond #79's lint removal.

- **#191 C56 — Decided (A).** Append to `build-dispatch.md` Resume check: "An `in_progress` task at resume was interrupted: show its diff and `#### Progress` and let the user choose resume, restart from clean, or blocked. Unattended, mark it `blocked` (reason: interrupted) and halt. Spike tasks need no commit."
- **#192 C58 — Clear.** In `build-parallel.md`, add: "Brief each executor with the task file's absolute path in the main checkout; it updates status and Progress there." Handle merge exit 2: "exit 2 (no commits) → cleanup and report." With #157, also handle exit 5: "exit 5 (dirty worktree) → the task did not complete; mark it `blocked`."
- **#193 C53 — Clear.** `build-plan.md:54-57` step 5 → "5. **Run tasks** per `references/build-plan-run.md`; read `build-execution.md` only under `inline`."

- **#194 C54 — Clear.** `build-plan-run.md:23-24` and `status.md:5` discovery → "every `plan.md` at any depth under `<working>/plans/`; skip `shape: group`". Status shows children under their group.
- **#195 C55 — Clear.** `build-dispatch.md:61-63` → "If that fails too, the task stays `blocked` with the reason in `#### Progress`; build-plan-run.md decides (unattended: halt; interactive: Retry/Skip/Abort)."
- **#196 C60 — Clear.** `orchestrate.md:31-34` → "Run `varde-workflow readiness` on each child (blockers = unmet deps); `depends_on` holds sibling slugs only." Fix `varde-workflow-cli.md:37-38` "(sibling or compound ids)" to match.
- **#197 C57 — Clear.** `build-execution.md:62-63`: add "(from `in_progress`; move it there first if still `todo`)".
- **#198 C52 — Clear.** `plan-resume.md:11-12` → "Resume: continue per `references/plan-start.md` Later turns."
- **#199 C61 — Clear.** PLAN-TEMPLATE.md:8 comment → "sibling plan dir names (a child's slug, never `<group>/<child>`) that must be `completed` first".

- **#200 C59 — Clear.** `orchestrate.md:27-28` → "`worktree-create.sh` exit 3 on resume → reuse `.varde/worktrees/orchestrate-<group-id>` as is."
- **#201 I1 — Clear.** `skills/README.md:74-78` → "…run `varde-knowledge` reflect, which writes a handoff only when work remains."
- **#202 I9 — Clear.** `install.sh:30` `-f` help → "Overwrite existing installs without prompting".
- **#203–#206 (C62, C63, C64, C65) — Keep.** No change beyond #194's glob fix.

- **#207–#214 (C66, C67, R80–R85) — Keep.** Extend `worktree-merge-destination.sh` with the #157 dirty-worktree exit 5 case.

- **#215–#221 (R86, K5, K15, K20, K27, E12, E14) — Keep.** No change beyond #73's shared Fallback-rule wording.

- **#222–#224 (P15, P16, I25) — Keep.** No change.
- **#225 K25 — Keep (trim).** Cut "another author may own the record" from `reconcile.md`.
- **#226 K7 — Keep (trim).** Cut "Create missing folders on first write." from `note.md`.
- **#227 P5 — Keep.** No change.

- **#228 R87 — Decided (B).** An explicit fix request chains report → fix. `varde-review/SKILL.md:8` → "Reporting is the default. When the user explicitly asks to fix, write the report, then run `fix` on that review in the same session." Rewrite review eval 2's expected output and assertions: findings persisted first, then a standalone fix pass applies `auto-fix` findings and leaves `triage` findings for the user.

- **#229 K17 — Clear.** `reflect.md:17` "Keep the paths." → "Note the paths for step 3."
- **#230 R95 — Keep (trim).** `specification.md:11-13` → "Optional: `license`, `compatibility` (≤500 chars), `metadata` (string→string map)."
- **#231–#236 (C68–C73) — Keep.** No change beyond fixes recorded above (#194–#200).

- **#237–#244 (C74–C76, R88–R92) — Keep.** No change beyond #134/#157/#194-era fixes already recorded.

- **#245–#252 (R93, R94, R96, K9, K29, E3, E5, P7) — Keep.** No change.

- **#253–#255 (P8, I24, K19) — Keep.** I24: update the pin per #133.
- **#256 C80 — Keep (trim).** Cut `build-execution.md:47`, which repeats :38-39.
- **#257–#260 (C77, C78, C79, C81) — Keep.** C78's wording fix is #154.

- **#261–#270 (C82–C87, R97–R100) — Keep.** No change beyond #38 (`map_path`) and #139 (scan steps 1-2).

- **#271–#280 (R101–R108, K8, K10) — Keep.** No change.
- **#281 K24 — Keep (fix).** `reflect-handoff.md:76`: ask which handoff to resume only when more than one candidate exists; with one, resume it.
- **#282–#302 (K33, P2, I7, I27, C88–C91, R109–R115, K28, K31, D1, I8) — Keep.** Core, non-removable. The varde-change SKILL.md table (#286) changes only per #16 and #31; descriptions (#301) change only per #58, #77, and gated #151. After reinstalling, verify the pi copies in `~/.pi/agent/skills` by hand (sandbox-blocked during the audit).

### Walkthrough outcome

302 items resolved: 7 decided by the user (#79 A, #80 A, #94 A, #119 A, #156 B, #191 A, #228 B); the rest clear or keep. Suggested apply order: (1) correctness — #3, #4, #161, #191–#199, #157, #9, #20/#169/#176; (2) the decided behaviour changes — #94, #156, #228, #80; (3) the cut/compress edits in rank order; (4) eval work — #118, #119, #125, #130, #134, #160, #162. Run `skills/check-refs.sh`, `tests/*.sh`, and `install.sh` after each group.

---

## Appendix: partition summaries (from the auditors)

### Adversarial audit: varde-change (pass 2, 2026-09-24)

**Agent-read words:** 9,024 now (SKILL 223, references 8,386, assets 415). Projected after the CUT/COMPRESS/MERGE rows, net of the FIX additions: about **8,100** (−~930 words, ~−1,250 tokens), plus three fewer file hops (build.md, build-research-task.md, build-edge-cases.md).

The words-per-file saving understates the real gain. Most of the savings are in **load per run**:
- C53 stops every delegated plan run from loading build-execution.md (517 words) into the orchestrator.
- C33 stops every unattended orchestrate child from loading interview.md (143 words).
- C8 removes one Read from every build, including every executor dispatch.
- C27 would drop a varde-review skill load per task.

Non-agent-read: about −180 words across tests and the resolver.

The prior pass left these undone or half-done: #15 (micro-change compression), the #95 migrate cut, the #55 duplicate paragraph, and the #11 prose greps.

**Five highest-value changes**
1. **C54 + C60 + C61: the plan-graph model is wrong in three places.** Discovery and status skip nested companion plans, which finish blocks on, so those plans are stranded. Orchestrate orders children from one child's `graph`, which misses siblings. Compound `depends_on` ids, as orchestrate and the template's comment describe them, resolve to `dependency_missing`. All three were verified against the CLI.
2. **C56 + C57 + C55: resume and retry edge cases.** An `in_progress` task left by a crash is never re-dispatched. `todo→done` is illegal, but the executor path doesn't guarantee `in_progress` first. Dispatch's "halt" contradicts the interactive Retry/Skip/Abort.
3. **C53 + C33 + C8: cut per-run load.** The orchestrator shouldn't read build-execution.md, unattended runs shouldn't read interview.md, and build.md should fold into SKILL.md.
4. **C1 + C2 + C9: finish the prior pass.** Delete the duplicated routing paragraph, delete the migrate line (every template plan reports `migration_required`), and apply the 65-word micro-change rewrite. About −200 words.
5. **C58 + C48: parallel-wave safety.** Tell executors where the task file lives when plan storage is ignored (the default). Stop `worktree-merge.sh` from auto-committing unverified leftovers into the main branch.

### Adversarial audit: varde-review, varde-docs, varde-agent-doc-authoring

**Agent-read words** (SKILL.md + references/*.md across the three skills):
- Now: 8,672 (varde-review 5,383, varde-docs 1,646, doc-authoring 1,643).
- Projected: about 7,580, a cut of about 1,090 words (≈1,470 tokens).
- Per-run savings are larger than the word count shows:
  - A docs refresh stops loading the 229-word `varde-code.md`.
  - An "improve triggering" run stops loading authoring.md (385 words).
  - simplify, which runs on every build task, loses about 35 words.
- Maintenance-only savings: about 90 words from `tests/agent-doc-authoring-evals.sh`.

**Prior-audit decisions that were not applied or were partly reverted:**
- #156: the triggering route and the `references/` prefixes.
- #44: the "Keep reading focused" compression.
- #136: the fan-out duplicate of reviewing.md:41.
- #157: the weigh-list reshape.
- #8: the generic script hygiene came back in with the merge.

**Top 5 changes:**
1. **Fix spec-plan's incremental scoping.** `map_file` returns graph communities, not spec domains. Use provenance recompute plus "a changed file in no document's `sources`" instead, and cut the dead "Spec scoping" section. Correctness fix, −90 words, and spec planning no longer needs varde-code.
2. **Reroute the varde-docs `varde-code.md`.** Refresh loads it but can use none of it, and needs `context_pack` inline. spec.md never loads it, and never loads spec-format.md for inline generation. Move the pointers to where they are needed.
3. **Fix the review evals.**
   - Eval 2 contradicts SKILL.md:8 ("explicit request" allows changing source); reword SKILL.md:8.
   - Eval 1 hard-codes a wrong folder path.
   - Replace the "banana" eval with a build escalation-gate or scan-status eval. simplify, scan, triage, and the gate have zero coverage.
   - Drop the stale docs assertions (`docs:v1`, worktree).
   - Fix the doc-authoring assertions that grade vocabulary.md terms nobody teaches anymore.
4. **Restructure fix-pass.**
   - Merge step 4 with the gate's trailing paragraphs.
   - Make "confirm the defect is gone" the precondition of step 10. Today it sits after the loop that already set `Disposition: fix`.
   - Drop the duplicated Escalated values. About −150 words.
5. **Finish doc-authoring.**
   - Apply #156/#44/#136.
   - Fold optimizing-descriptions.md into specification.md.
   - Fix authoring.md's wrong "Token economy" cross-reference.
   - Cut the repeated loading and independence rules (four copies). About −300 words.

### Adversarial audit, pass 2: varde-knowledge, varde-explore, varde-prototype, and shared infrastructure

**Agent-read words, now → projected** (excluding evals, scripts, and tests):

| Group | Now | Projected |
|---|---|---|
| varde-knowledge | 2,497 | ~2,190 |
| varde-explore | 832 | ~660 |
| varde-prototype | 1,006 | ~870 |
| README + eval-tools docs (rare) | 1,601 | ~1,400 |
| **Total** | **5,936** | **~5,120 (−14%)** |
| Descriptions (always, 7 skills) | 172 | ~162 (−10 per session; +6 if D2 is adopted) |

The biggest per-run saving is the reflect chain: about −170 of roughly 1,420 words. Code and test cuts come to about −220 words (I10, I23).

**Five highest-value changes:**

1. **K1: cut the knowledge CLI's "Legacy artifacts" section.** `inspect` flags every valid OKF note `migration_required`, and `migrate` rewrites notes into workflow-artifact envelopes. Following the reference corrupts notes.
2. **I17: restore `def fail` in run-evals.sh's Codex parser.** 7afcac2 removed it, and every Codex error path now dies with a NameError instead of its reason. Add one message assertion to trigger-evals.sh.
3. **I18 / E15 / K35 / P17: make the three skills' evals measurable.** Today there are no fixtures and the judge sees only final text. The agreed #83 fixtures and #96 judge input were never applied. A short `verification_script` per skill gives most of the value cheaply.
4. **I1 + I13: fix contradictory or broken cross-references.** README:74-78 promises a handoff at every session boundary, contrary to reflect.md. eval-tools/README.md:7-9 points to optimizing-descriptions.md for query sets, but that content moved.
5. **Say "when to load varde-code" once in explore and compress explain.md (E2, E6-E10).** About −145 words on every explain run. The loading rule currently appears three times, and the PR-diff and HTML-section prose is roughly twice the size it needs to be.
