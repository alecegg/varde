# Skill instruction value audit (2026-09-30)

Report-only. No skill files were edited.

- Scope: every agent-loaded `.md` under `skills/` (SKILL.md, references, assets). Shared references were audited once.
- Excluded: `FLOW.md` (human-only), `evals/`, `skills/README.md`, `agents/`.
- Coverage: 1,389 instruction units, about 32,200 words.
- Full ranked list: [merged-table.md](merged-table.md). It is sorted by score (least valuable first), then by verdict (cut, merge, script, shorten, keep).
- Per-part detail, defects, and structural notes: [part-a.md](part-a.md) (varde-change and shared), [part-b.md](part-b.md) (review, manage, docs, toz), [part-c.md](part-c.md) (learn, knowledge, explore, prototype, agent-doc-authoring).

## Isolation rule (revision 2)

Every installed skill must run alone. Repetition across skills is kept. Only these are cut:

- repetition within one skill, including a skill's own copies of shared files;
- shared-file sections that a receiving skill never uses. These are handled by splitting the MANIFEST entry, not by deleting the section.

A pointer to AGENTS.md or to another skill's files does not satisfy this rule. Rows changed by this rule are marked `(revised)` in the merged table (19 rows). Four merges were reversed because their target lived only in varde-change.

## Scale

| Score | Meaning | Units |
|---|---|---|
| 0 | No behavioral effect: rationale, restatement, or duplicate | 13 |
| 1 | Marginal: default model behavior, or an unevidenced edge case | 150 |
| 2 | Helpful default; a cheap failure without it | 344 |
| 3 | Prevents a moderate-cost failure, or states an uninferable preference | 475 |
| 4 | Structural contract (path, format, CLI, state, routing) | 368 |
| 5 | Safety boundary or cross-skill core contract | 39 |

Verdicts for units scored 0-2: 122 cut, 71 merge, 15 script, 56 shorten, 243 keep.

Calibration caveat: three auditors scored separate parts. Part A gave 26 units a 5; part C gave 2. Compare scores within a skill more than across parts.

## Savings estimate

| Part | Audited words | Cuttable (estimate) | Plus scripting |
|---|---|---|---|
| A: varde-change and shared | 13,921 | ~1,950 (14%) | ~450 |
| B: review, manage, docs, toz | ~10,080 | ~840 (8%) | ~275 |
| C: learn, knowledge, explore, prototype, ada | 8,203 | ~1,250 (15%) | 208-400 per affected run, from conditional loads |
| **Total** | **~32,200** | **~3,900 (12%)** after the isolation revision | **~900 more** |

Shared references are copied into up to five skills. Their per-install savings multiply.

## Highest-leverage changes

1. **Shared CLI references.**
   - `varde-workflow-cli.md` (~330 words): drop the concept-search and concept-map sections from varde-change's copy by splitting the MANIFEST entry.
   - `varde-code-cli.md` (~180 words per copy, four copies): cut the command-catalog restatements.
2. **Repetition within one skill** (~235 words in total):
   - resolved-path brief rule (7 times in varde-change);
   - paging instruction (5 times in varde-learn);
   - "carry its verdict" in a SKILL.md whose own `review-gates.md` copy already owns it;
   - "record lessons" (twice each in varde-review and varde-docs; keep one per skill).
3. **Prose that restates a script or CLI.**
   - `diagnose-capture.md` (~200 words);
   - `criteria.md` thresholds (~150 words);
   - `scan-author.md` field lists.
4. **Script candidates.**
   - PR intake in `fix-pr.md:7-44` (~200 words);
   - ownership audit and plan selection in `build.md` (~240 words);
   - worktree-wave sequence in `build-parallel.md` (~200 words).
5. **Conditional loads.**
   - `specification.md` only for SKILL.md edits;
   - the overlap branch of `diagnose.md` (~400 words) into its own file;
   - "Select a plan" in `build.md` only when no plan is named.
6. **Near-duplicate files.**
   - `build-worktree.md` "Review authorization" duplicates `review-gate-worktree.md` (~165 words). Cut it from `build-worktree.md`, not from the shared file, which installs into 5 skills;
   - the `## Executor` section of `fix.md` (~90 words).

## Correctness defects (fix before trimming)

Checked by the orchestrator against the files: 1, 2, and 3. The rest are as reported by auditors.

1. `review init` lacks `--tier-evidence` in `build-micro-change.md:24`, `plan.md:192`, `orchestrate.md:61`, and `varde-workflow-cli.md:44-45`. Missing evidence forces high tier (`review-gates.md:71`), so low-tier shortcuts never apply there.
2. `handoff-write.md:22` asks for `content_hashes` without pointing to `handoff-snapshot.py`. Resume recomputes with that script, so hand-built hashes read as modified or unknown.
3. `criteria.md:151` requires a closing `## Gotchas` section, but `criteria.md:159` says "keep gotchas inline". The two conflict or at least read ambiguously.
4. `build-finish.md:24` makes implementation review conditional; `review-gates.md:118` says it is always required.
5. `review-gate-record.md:6` reuses the reviewer's context; `review-gates.md:81` requires a clean-context reviewer.
6. `varde-learn/SKILL.md:22` says "do not write Markdown", yet diagnose writes `report.md`. It means "do not record friction in Markdown".
7. `handoff-snapshot.md:6` runs `scripts/...` relative to the current directory, not the skill root.
8. `report.md:34` passes a plan id to delegates that `report.md:71` says write nothing. The `CODE` category is a default but has no scope or check.
9. Minor:
   - stale `kind: spike` in `TASK-TEMPLATE.md:17`;
   - `->` vs. `→` in the decision log;
   - `fix.md:6` pointer missing `references/`;
   - `report.md:55` heading with no blank line before it.
