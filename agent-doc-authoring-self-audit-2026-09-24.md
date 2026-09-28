# Varde agent doc authoring: self-audit

**Date:** 2026-09-24

**Scope:** The current working-tree version of `skills/varde-agent-doc-authoring/`: `SKILL.md`, all eight references, four scripts, and `evals/evals.json`. I also inspected the three local test scripts that exercise its tooling. The working tree already contains uncommitted changes to the skill, review reference, and eval file; this report evaluates those changes as they stand.

**Snapshot note:** This audit measured an earlier checkout; its findings and rankings describe that snapshot. The 586-word `using-scripts.md` and 1,445-word `vocabulary.md` counts are historical, not current. Follow-up edits reduced them to 188 and 323 words.

## Follow-up results

The item-by-item follow-up was developed in an isolated worktree. Items 1–12, 14, and 16 received the chosen edits; items 13 and 15 were kept. The validator and root dispatch in items 17–18 remain useful as ranked. Current word counts should be read from the files, not the snapshot table below.

The three self-eval defects have targeted fixes: cases 1 and 3 now include their source files, case 3 writes to a workspace-relative path, missing or traversing declared inputs stop before an agent call, and filesystem verifiers check the report and skill artifacts. A further integrity check found that the evaluated skill snapshot exposed `evals/evals.json` and its expected answers; the runner now excludes `evals/` from that snapshot while keeping setup and verification scripts runner-side. The runner still inherits the user's `HOME` for Claude authentication, so a temporary working directory is **not** a general write sandbox against arbitrary absolute paths. No billed output eval was run; local fixture and reference checks passed.

## Highest-value changes

1. **Repair and contain the skill's own eval cases before paying to run them.** The output runner creates an empty working directory plus a copy of this skill. Eval 1 asks for `skills/varde-change/SKILL.md`, which is not supplied. Eval 3 claims a task happened earlier in the conversation, but each invocation has a fresh context. It also asks the agent to write under `~/.claude/skills/` while the runner leaves `HOME` unchanged. Add fixtures, self-contained prompts, an isolated home directory, and a filesystem verifier for claimed files.
2. **Put a cost gate on description optimization.** The reference prescribes about 20 prompts, three runs each, and multiple iterations. One initial round means at least 60 billed agent calls. Reserve that process for measured trigger problems; start with a small set of representative near misses.
3. **Prune repeated rules and test broad model claims.** This skill serves agent documents across projects, so cross-language script guidance has a real audience. Its 586-word script reference can still be shorter by dropping versioned package examples that do not change a decision. The 1,445-word vocabulary reference mixes useful routing concepts with broad claims about model behavior that are not supported by evidence in the skill.
4. **Make frontmatter validation conditional in the root workflow.** `SKILL.md` calls for it on every run, while the review reference calls for it only after frontmatter edits. The unconditional step adds a tool call to reference-only and review-only work.

The first item is a correctness defect. The others are value and token-cost judgments, not proven output regressions. No skill source was changed in this audit.

## Measured load

Counts use whitespace-separated words, not tokenizer output. The reference's 1.3 tokens per word is only a rough estimate. Scripts do not load into model context merely because they are shipped.

| Path through the skill | Words loaded from instructions and named references |
|---|---:|
| Root `SKILL.md` | 324 |
| Author or revise | 950 |
| Author with frontmatter specification | 1,414 |
| Review | 968 |
| Review an ordered workflow | 1,240 |
| Review plus optional vocabulary | 2,413 |
| Improve triggering | 1,562 |
| Evaluate a mature skill, including final review | 2,056 |

The description is 171 characters including YAML quotes. The whole skill directory contains 11,045 whitespace-separated words: 6,061 in Markdown guidance, 4,361 in scripts, and 623 in the eval JSON. That total is an inventory size, not a per-run prompt cost.

## Ranked inventory

**#1 is the strongest candidate to cut or shrink. The list moves toward content most worth keeping.** Each entry gives the benefit, cost, evidence, and recommended action. Correctness defects appear separately below so a broken feature is not mistaken for a low-value one.

1. **The default scale of description optimization.** [optimizing-descriptions.md](skills/varde-agent-doc-authoring/references/optimizing-descriptions.md#L29) gives a useful way to detect false and missed triggers, but prescribes about 20 prompts, at least three runs each, a train/validation split, and up to about five iterations. That is at least 60 billed calls in the first round, before a fresh sanity set. Use this only when actual misfires justify the cost. Start smaller, then expand if results are noisy or a change is consequential.

2. **Cross-language script advice.** [using-scripts.md](skills/varde-agent-doc-authoring/references/using-scripts.md#L3) is 586 words and lists package runners, example versions, and language-by-language conventions. This skill is general-purpose, so cross-language coverage is valuable. The versioned command catalog can go stale and rarely changes the document-authoring decision. Keep examples across runtimes, the rule that each bundled script is named where it runs, and the script interface contract; shorten or remove versioned package commands that merely illustrate an already stated rule.

3. **The optional conceptual vocabulary essay.** [vocabulary.md](skills/varde-agent-doc-authoring/references/vocabulary.md#L48) is 1,445 words. Its pointer, load-path, duplication, and no-op concepts help an auditor reason about costs. Its stronger claims about leading words, negation, and model attention are presented as general facts without tests here. Keep the decision vocabulary and concrete failure modes; mark hypotheses as such and remove repeated rationale. This file alone makes a review that loads it 2,413 words.

4. **Extra output-benchmark machinery.** [run-output-evals.sh](skills/varde-agent-doc-authoring/scripts/run-output-evals.sh#L39) is 2,658 words of shell and Perl. It supplies isolation, timeouts, deterministic verification, judging, token accounting, and aggregated deltas. Those are real capabilities, and the fixture test passed. The many metrics and custom process-control paths also create a large maintenance surface. Keep the basic with/without comparison and artifact verification; justify each metric against a decision it changes before extending it. This is a maintenance cost, not prompt load unless the script is read.

5. **Repository release wrapper shipped with the skill.** [run-changed-output-evals.sh](skills/varde-agent-doc-authoring/scripts/run-changed-output-evals.sh#L1) selects changed skills between Git refs and invokes the output runner. That helps repo maintainers before releases; an installed copy of this skill rarely needs repository-wide selection. Move the wrapper to repo tooling if no installed-skill use case exists. Its 411 words of code and dedicated fixture test are then maintained where the release flow lives.

6. **Repeated progressive-disclosure rules.** [SKILL.md](skills/varde-agent-doc-authoring/SKILL.md#L26), [authoring.md](skills/varde-agent-doc-authoring/references/authoring.md#L14), [specification.md](skills/varde-agent-doc-authoring/references/specification.md#L31), [workflow-skills.md](skills/varde-agent-doc-authoring/references/workflow-skills.md#L26), and [vocabulary.md](skills/varde-agent-doc-authoring/references/vocabulary.md#L29) each explain what belongs inline versus behind a reference. The distinction is valuable, but repeated prose adds tokens and makes revisions drift. Keep one operational rule in `authoring.md` and only branch-specific consequences elsewhere.

7. **The newly added review inventory's wording.** [reviewing.md](skills/varde-agent-doc-authoring/references/reviewing.md#L6) makes every review ask whether a line is necessary, worth its cost, and accurately compressible. That catches the blind spot the earlier checklist had. It adds about 246 words to every review, and some ideas recur in the later instruction-quality and token-economy lists. Keep the three decision tests and ranked output; merge duplicate checklist questions after verifying the shorter version still prompts full coverage.

8. **The unconditional frontmatter step.** [SKILL.md](skills/varde-agent-doc-authoring/SKILL.md#L31) says to run validation as step 6 in every workflow; [reviewing.md](skills/varde-agent-doc-authoring/references/reviewing.md#L83) narrows it to frontmatter edits. The validator is cheap and useful when YAML changes, but a review or reference-only edit does not need the call. Make the root step conditional.

9. **The trigger test runner.** [run-evals.sh](skills/varde-agent-doc-authoring/scripts/run-evals.sh#L1) offers quantitative trigger checks and is needed for systematic description tuning. It costs one agent invocation per query and repetition. No test for this script was found under `skills/tests/`, and its parser assumes a `.messages[].content[]` tool-use shape without a checked fixture. Keep the capability, add a small mocked-envelope test, and require a cost estimate before large runs. The parser concern is unverified against the installed Claude CLI.

10. **The output-evaluation guide.** [evaluating-skills.md](skills/varde-agent-doc-authoring/references/evaluating-skills.md#L1) is 1,088 words. Clean contexts, mechanical verification, human review, and comparing versions are useful. The long runner walkthrough and output-tree example partly repeat script `--help`; trim these after the eval fixtures are repaired. Keep the warning that repeated runs are billed and the distinction between mechanical and subjective assertions.

11. **The description-writing guide.** [optimizing-descriptions.md](skills/varde-agent-doc-authoring/references/optimizing-descriptions.md#L5) correctly centers user intent and near misses. Keep the concise writing rules and measured tuning path. Compress the extended sample and iteration instructions when no measurement is needed.

12. **The specification reference.** [specification.md](skills/varde-agent-doc-authoring/references/specification.md#L1) preserves exact frontmatter constraints and a validation command. That prevents load failures. The directory tree and generic load-stage explanation repeat authoring guidance; trim those while keeping constraints and the sandbox-specific `uv` workaround.

13. **Ordered-workflow layout.** [workflow-skills.md](skills/varde-agent-doc-authoring/references/workflow-skills.md#L3) is only 272 words and gives actionable dispatch, one step per action, and a fan-out check. This earns its conditional load, especially for skills with several modes. Keep it.

14. **Review checklist and ranked output.** [reviewing.md](skills/varde-agent-doc-authoring/references/reviewing.md#L34) covers triggering, reference loading, instruction quality, token economy, workflow structure, and final checks. A full ranked inventory is more costly than a terse finding list, but the user explicitly wants cost and removability tested on every review. Keep the judgment criteria and ranking, while making the prose leaner as in item 7.

15. **Output eval's deterministic verification and local fixtures.** [run-output-evals.sh](skills/varde-agent-doc-authoring/scripts/run-output-evals.sh#L270) can grade filesystem outcomes directly and reserve the judge for transcript behavior. [output-evals.sh](skills/tests/output-evals.sh#L1) exercises timing, missing usage, timeouts, verification, isolation, and selection with a mock CLI. This is the part of the evaluation system that prevents persuasive prose from passing as an artifact. Keep it and use it for this skill's own evals.

16. **Grounding and default authoring procedure.** [authoring.md](skills/varde-agent-doc-authoring/references/authoring.md#L3) requires real task, runbook, incident, or project evidence before writing a skill. It also says where to place instructions and when to include concrete gotchas. That prevents plausible but unearned workflow text. Keep it, with duplicate routing prose consolidated as in item 6.

17. **Frontmatter validator.** [validate-frontmatter.py](skills/varde-agent-doc-authoring/scripts/validate-frontmatter.py#L1) checks YAML parsing, name and description constraints, optional fields, and size warnings. [frontmatter.sh](skills/tests/frontmatter.sh#L1) runs it against shipped skills. The validator passed on the current tree. Keep it; only its invocation needs narrowing.

18. **Root task dispatch and local references.** [SKILL.md](skills/varde-agent-doc-authoring/SKILL.md#L11) routes authoring, review, trigger tuning, and mature evaluation to distinct references. At 324 words, the root keeps conditional material off the common path. The self-contained reference layout also survives installation. Keep this structure and the description's scope boundary.

## Correctness defects to fix regardless of rank

1. **An eval can target the real home directory.** [evals.json](skills/varde-agent-doc-authoring/evals/evals.json#L29) asks the agent to create `~/.claude/skills/deploy-release/`. The runner [creates a temporary working directory and invokes Claude from it](skills/varde-agent-doc-authoring/scripts/run-output-evals.sh#L430), but does not change `HOME` or confine writes to that directory. A real run could write to the user's home directory. Replace the prompt's home path with a sandbox-relative path and isolate `HOME` before running prompts. This is a risk established from the command and environment setup, not an observed write.

2. **The checked-in evals do not recreate their stated inputs.** [evals.json](skills/varde-agent-doc-authoring/evals/evals.json#L6) case 1 names another skill file, but the runner starts in a temporary directory and only copies this skill and listed `files`; case 1 lists no files. Case 3 claims a completed prior session, but [the runner sends only the case prompt in a fresh invocation](skills/varde-agent-doc-authoring/scripts/run-output-evals.sh#L458). Its expected behavior depends on context the test does not provide. Rewrite both prompts with fixtures or setup scripts. This is established from the runner and eval data; the paid evals were not run.

3. **The eval cannot prove its new report-file assertion.** [evals.json](skills/varde-agent-doc-authoring/evals/evals.json#L9) asks whether a Markdown report is linked. The runner [passes only the final transcript to the LLM judge](skills/varde-agent-doc-authoring/scripts/run-output-evals.sh#L366), and this eval has no `verification_script`. A link in prose could pass even when no file exists, contrary to [the guide's instruction to verify artifacts directly](skills/varde-agent-doc-authoring/references/evaluating-skills.md#L104). Add a filesystem verifier and grade the actual report.

4. **Validation instructions conflict.** The root's unconditional validation step and the review reference's conditional step disagree. Resolve as item 8 recommends.

## Verification and limits

- Passed: `skills/tests/output-evals.sh`, `skills/tests/changed-output-evals.sh`, and `skills/tests/frontmatter.sh`.
- Read-only review of the skill and tooling. No billed agent evaluations were run, so the report does not claim measured output quality or trigger accuracy.
- The runner's fixture tests show that its mechanics work for mocked responses. They do not establish that these three checked-in eval cases are valid or that current Claude CLI JSON always matches `run-evals.sh`'s parser.
