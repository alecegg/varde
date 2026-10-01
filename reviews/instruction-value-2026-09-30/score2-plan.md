# Score-2 plan

Approved 2026-09-30: A and B apply, C shortens to one clause, D awaits per-row decisions.

## A: within-skill merges (apply) (45)

| # | Score | Verdict | Location | Instruction | Why |
|---|---|---|---|---|---|
| 164 | 2 | cut | `skills/varde-review/references/fix-pr.md:3` | One-shot, read-only intake building local review folder | Descriptive; steps imply it. |
| 165 | 2 | merge→review-gates.md:81 | `skills/shared/references/review-gate-plan.md:15` | Pass reviewer subject id, repository, memory paths | Subset of review-gates §3 list. |
| 166 | 2 | merge→build-execution.md:25 | `skills/shared/references/review-gate-plan.md:38` | Tasks may be done while aggregate review pending | Duplicate of build-execution:25. |
| 167 | 2 | merge→build-finish.md:9 | `skills/shared/references/review-gate-plan.md:40` | Finish source/docs/spec/changelog/verification before final review | Duplicate of build-finish §1 and review-gates §5.1. |
| 168 | 2 | merge→review-gates.md:114 | `skills/shared/references/review-gate-plan.md:52` | Material changes need fresh independent verdict | Stated in review-gates §4 and micro-change. |
| 171 | 2 | merge→build-finish.md:86 | `skills/shared/references/varde-workflow-cli.md:34` | Run conclude after criteria/specs pass; conclusion-* follow-ups | Owned by build-finish §6. |
| 172 | 2 | merge→review-gates.md:63 | `skills/shared/references/varde-workflow-cli.md:39` | Review init commands (without --tier-evidence) | Duplicates review-gates with a stale flag set. |
| 173 | 2 | merge→review-gate-record.md:9 | `skills/shared/references/varde-workflow-cli.md:48` | init returns subject_id/version; reviewer inspects and records | Owned by review-gate-record. |
| 174 | 2 | merge→review-gates.md:103 | `skills/shared/references/varde-workflow-cli.md:52` | inspect/record/check/contract/expand command block | Each command already given where used. |
| 175 | 2 | merge→review-gate-plan.md:49 | `skills/shared/references/varde-workflow-cli.md:64` | contract/expand may invalidate approval | Stated with more precision in review-gate-plan. |
| 176 | 2 | merge→skills/varde-agent-doc-authoring/references/criteria.md:110 | `skills/varde-agent-doc-authoring/references/criteria.md:149` | Keep short procedures and gates inline | Same as 'merge other references into caller'. |
| 177 | 2 | merge→skills/varde-agent-doc-authoring/references/criteria.md:50 | `skills/varde-agent-doc-authoring/references/criteria.md:163` | Cut guidance that names no observable action | Overlaps Cut-it list. |
| 178 | 2 | merge→skills/varde-agent-doc-authoring/references/criteria.md:51 | `skills/varde-agent-doc-authoring/references/criteria.md:16` | State the goal and a default; let the agent choose the method | Same test as Cut-it item 'spells out a method'. |
| 179 | 2 | merge→skills/varde-agent-doc-authoring/references/author.md:5 | `skills/varde-agent-doc-authoring/references/criteria.md:24` | Ground project-specific rules in evidence: runbooks, schemas, history, incidents, reviews | Overlaps author.md step 2 evidence gathering. |
| 180 | 2 | merge→skills/varde-agent-doc-authoring/references/criteria.md:71 | `skills/varde-agent-doc-authoring/references/criteria.md:63` | Success is fewer words; structuring alone only moves the problem | Same point as L71 'only moves the length'. |
| 181 | 2 | merge→skills/varde-agent-doc-authoring/references/author.md:13 | `skills/varde-agent-doc-authoring/references/specification.md:30` | Validate with validate-frontmatter.py (--json; several paths) | author.md:13 already requires the run. |
| 182 | 2 | merge→skills/varde-agent-doc-authoring/references/specification.md:18 | `skills/varde-agent-doc-authoring/references/specification.md:8` | description: non-empty, max 1024; what, when, trigger terms | Length enforced by validator; guidance dups wording list. |
| 183 | 2 | merge→user CLAUDE.md | `skills/varde-change/SKILL.md:39` | One topic per turn; up to three facets; wait | Same rule in user's global CLAUDE.md; needed only for other users. |
| 184 | 2 | merge→user CLAUDE.md | `skills/varde-change/SKILL.md:43` | Recommend one option with one-sentence reason | Same as global CLAUDE.md. |
| 185 | 2 | merge→build-execution.md:104 | `skills/varde-change/references/build-execution.md:108` | "In a parallel wave, do not edit the task file" | Third statement of the same rule (L104, build-parallel:40). |
| 186 | 2 | merge→review-gates.md | `skills/varde-change/references/build-finish.md:67` | Fix plans pass pre-edit gate; changed covered files need fresh full-subject record | Gate rule owned by review-gates. |
| 187 | 2 | merge→build-posture-debug.md:60 | `skills/varde-change/references/build-posture-debug.md:39` | Label unreproduced symptoms **unreproduced**, state limits | Stated again in Phase 1 and Phase 2 step 3. |
| 188 | 2 | merge→build.md:72 | `skills/varde-change/references/build.md:126` | Repeat until done/blocked/empty; remaining todo as blocked_by_dep | Duplicates step 5.4 wording. |
| 189 | 2 | merge→build.md:224 | `skills/varde-change/references/orchestrate.md:98` | Stop when statuses and commits disagree | Same rule as build Resume check. |
| 192 | 2 | merge→skills/varde-knowledge/references/reflect.md:10 | `skills/varde-knowledge/SKILL.md:20` | Friction belongs to varde-learn; switch by name, don't import references | Description 'Not for friction' plus reflect step 1 cover it. |
| 193 | 2 | merge→skills/varde-knowledge/references/reflect.md:12 | `skills/varde-knowledge/references/note.md:30` | Keep only lasting decisions, patterns, definitions | Dup of skill purpose and reflect filter. |
| 194 | 2 | merge→skills/varde-knowledge/references/note.md:36 | `skills/varde-knowledge/references/note.md:45` | Frontmatter example block | Duplicates field bullets. |
| 195 | 2 | merge→skills/varde-knowledge/references/note.md:78 | `skills/varde-knowledge/references/reconcile.md:5` | Correct in place; gone subject -> deprecated | Deprecation rule owned by note.md. |
| 197 | 2 | merge→skills/varde-learn/SKILL.md | `skills/varde-learn/references/capture.md:12` | Page with --offset/--limit; show until meta.truncated false | Paging rule repeated in 4 learn references. |
| 198 | 2 | merge→skills/varde-learn/references/diagnose-capture.md:29 | `skills/varde-learn/references/diagnose-capture.md:22` | Copy digest, thread_id, anchor; incident_kind one of three; item mode | Template placeholders already encode mapping; keep kind enum only. |
| 199 | 2 | merge→skills/varde-learn/references/diagnose.md:96 | `skills/varde-learn/references/diagnose-capture.md:72` | Rewritten, inherited, uncertain anchors remain report-only | Dup of L8 and diagnose.md report rules. |
| 200 | 2 | merge→skills/varde-learn/references/diagnose.md:104 | `skills/varde-learn/references/diagnose-toz.md:10` | Current/unknown overlap: verified links, frozen pre-cutoff excerpts; cite handles | Restates diagnose.md cutoff rules. |
| 202 | 2 | merge→skills/varde-learn/SKILL.md | `skills/varde-learn/references/distill.md:12` | Follow next_offset while truncated; finish show pages before counting | Paging rule repeated; 'before counting' is the unique bit. |
| 203 | 2 | merge→skills/varde-learn/references/distill.md:37 | `skills/varde-learn/references/distill.md:33` | If evals approved, run before cases | Merge with L37 into one before/after line. |
| 204 | 2 | merge→skills/varde-learn/SKILL.md | `skills/varde-learn/references/reconcile.md:11` | show pages occurrences and history; continue --offset until not truncated | Paging rule repeated. |
| 205 | 2 | merge→skills/varde-prototype/SKILL.md:8 | `skills/varde-prototype/references/visual-track.md:34` | Never edit production source in this track | Dup of SKILL.md production boundary. |
| 206 | 2 | merge→`skills/varde-review/references/fix.md:49` | `skills/varde-review/SKILL.md:45` | At end of write flow record obstacles via varde-learn, decisions via varde-knowledge | Duplicated in fix.md:49, refresh.md:29, spec.md:35; keep one per skill. |
| 207 | 2 | merge→`skills/varde-review/references/fix.md:76` | `skills/varde-review/references/fix.md:77` | Size wins: large high-severity fix is action-item | Fold into previous bullet. |
| 208 | 2 | merge→`skills/varde-review/references/fix-pass.md:15` | `skills/varde-review/references/fix.md:87` | Disposition alone doesn't approve solution; keep decision history | Same rule at fix-pass.md:15-16. |
| 209 | 2 | merge→`skills/varde-review/references/scan.md:3` | `skills/varde-review/references/scan.md:44` | Report every finding: fixed, not-real reasons, left for user | Restates the opening contract. |
| 225 | 2 | shorten | `skills/shared/references/varde-workflow-cli.md:4` | CLI purpose; Write/Edit for artifacts; review commands require CLI | Last clause is the value; duplicated at L96. |
| 244 | 2 | shorten | `skills/varde-change/references/build-retry-reassessment.md:24` | Revised plan returns to pre-edit gate; no routine review cycle | Gate rule owned by review-gates. |
| 253 | 2 | shorten | `skills/varde-learn/references/diagnose.md:51` | Before report for current/unknown overlap, follow procedure below | Forward pointer; reorder sections instead. |
| 254 | 2 | shorten | `skills/varde-learn/references/distill.md:52` | Recording promotes atomically; no separate status command; report failure | Stops redundant set-status; drop 'nothing partial' clause. |
| 262 | 2 | shorten | `skills/varde-review/references/report-format.md:50` | Imported PR feedback/scan candidates pending triage; severity only routing | fix-pr.md:54 and scan.md:59 already set Label/Severity. |

## B: restates a script or CLI (apply; move fix hints into script messages) (20)

| # | Score | Verdict | Location | Instruction | Why |
|---|---|---|---|---|---|
| 211 | 2 | script | `skills/varde-agent-doc-authoring/references/author.md:18` | Check every changed pointer and each file's kind | skill-flow.py already reports pointers and kinds. |
| 212 | 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:67` | Parallel items one per line under purpose lead-in at 4+ or 3 multiword | check-length.py already warns on inline lists with these thresholds. |
| 213 | 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:78` | End line items with punctuation; blank line after list; lazy continuation rationale | check-length.py warns lazy continuations; drop rationale sentence. |
| 214 | 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:94` | Unit sentences: target 3, reason 4-5, defect 6+ | Script computes; agent needs only the 'needs a reason' band. |
| 215 | 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:95` | Section words: 250 / 251-400 / over 400 | Script computes. |
| 216 | 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:96` | File prose share: 40% / 41-60% / over 60% | Script computes. |
| 217 | 2 | script | `skills/varde-agent-doc-authoring/references/criteria.md:98` | High prose share means steps or lists still written as sentences | Fix hint; belongs in script message. |
| 218 | 2 | script | `skills/varde-agent-doc-authoring/references/specification.md:7` | name: 1-64 lowercase, digits, single hyphens; matches directory | validate-frontmatter.py enforces; self-correcting. |
| 220 | 2 | script | `skills/varde-learn/references/evals.md:39` | List changed skills with git diff | cut | sort -u | Deterministic; fits a script or CLI flag. |
| 221 | 2 | shorten | `skills/shared/references/review-gate-record.md:18` | record_template pre-fills listed fields | Describes CLI output internals; "fill remaining placeholders" suffices. |
| 222 | 2 | shorten | `skills/shared/references/review-gates.md:71` | Missing tier evidence, open_choices, shared contracts default to high | CLI behavior description; partly useful. |
| 223 | 2 | shorten | `skills/shared/references/varde-code-cli.md:27` | Command catalog (14 entries) | --help lists commands; keep names + key caveats only. |
| 224 | 2 | shorten | `skills/shared/references/varde-workflow-cli.md:28` | readiness reports actions/blockers | Describes output. |
| 236 | 2 | shorten | `skills/varde-change/references/build-finish.md:60` | Fix: bounded build task with finding_ids, solution, decision evidence | Restates varde-review fix Parent workflow it cites. |
| 245 | 2 | shorten | `skills/varde-change/references/build-worktree.md:70` | Binding authorizes only start/resume; renewed approval never revives stale worker | CLI enforces this; prose is explanation. |
| 256 | 2 | shorten | `skills/varde-manage/references/scan-author.md:55` | kind: pattern or sql | Visible in every seeded rule. |
| 257 | 2 | shorten | `skills/varde-manage/references/scan-author.md:56` | severity values, case-insensitive | Visible in seeded rules. |
| 258 | 2 | shorten | `skills/varde-manage/references/scan-author.md:58` | message is finding headline | Visible in seeded rules. |
| 259 | 2 | shorten | `skills/varde-manage/references/scan-author.md:59` | pattern or query per kind | Visible in seeded rules. |
| 260 | 2 | shorten | `skills/varde-manage/references/setup.md:39` | Row: Toz config root precedence (env, XDG, legacy) | `varde-toz doctor --json` reports the root (setup.md:43). |

## C: model-default craft (shorten to one clause) (18)

| # | Score | Verdict | Location | Instruction | Why |
|---|---|---|---|---|---|
| 228 | 2 | shorten | `skills/varde-agent-doc-authoring/references/review.md:3` | Audit adversarially every item in scope; trace behavior and loading | Posture line; overlaps step 1.3. |
| 231 | 2 | shorten | `skills/varde-change/references/build-execution.md:25` | Task may be done while aggregate review pending; not plan completion | Guards premature "plan done" claims; one clause suffices. |
| 232 | 2 | shorten | `skills/varde-change/references/build-execution.md:52` | Benign drift: note and proceed; invalidating drift: blocker | Reasonable default; examples in parentheses cuttable. |
| 233 | 2 | shorten | `skills/varde-change/references/build-execution.md:62` | Profile table tdd/regression/characterization/smoke/not-applicable | Names are template vocabulary; methods are model defaults. |
| 234 | 2 | shorten | `skills/varde-change/references/build-execution.md:81` | Check shared surface dependents first (varde-code or grep) | Default-ish; also owned by plan.md External interface check. |
| 237 | 2 | shorten | `skills/varde-change/references/build-finish.md:72` | Rerun only AC checks covering fix-changed files; unconfirmed blocks | Optimization detail; "rerun affected AC checks" suffices. |
| 238 | 2 | shorten | `skills/varde-change/references/build-posture-debug.md:21` | Field definitions: reproduction, hypotheses, experiments, cause, verification | Field names suffice; definitions are mostly self-evident. |
| 239 | 2 | shorten | `skills/varde-change/references/build-posture-debug.md:34` | diagnose may leave cause uncertain; state evidence limit | Overlaps L39 unreproduced labeling. |
| 240 | 2 | shorten | `skills/varde-change/references/build-posture-debug.md:70` | Minimize to smallest red scenario, rerun after each cut | Good craft; one clause. |
| 241 | 2 | shorten | `skills/varde-change/references/build-posture-debug.md:77` | State falsifiable hypothesis before testing, with template sentence | Useful; template sentence cuttable. |
| 242 | 2 | shorten | `skills/varde-change/references/build-posture-refactor.md:15` | Target selection order: explicit, review findings, structural goal, else ask | Order mostly default; "else ask" is the value. |
| 243 | 2 | shorten | `skills/varde-change/references/build-posture-refactor.md:64` | Verify with approved checks; full suite only for new failures/concerns | Long; condense to one rule. |
| 246 | 2 | shorten | `skills/varde-change/references/build.md:35` | Default to current checkout; stage only task-owned paths | Default; staging half dup of build-execution. |
| 248 | 2 | shorten | `skills/varde-change/references/plan.md:83` | Design It Twice: constraints, two alternatives, recommend, log loser | Useful technique; could be one line. |
| 249 | 2 | shorten | `skills/varde-change/references/status.md:10` | Handoffs table: open, newest 5, columns, empty message | Format detail; model would do similar. |
| 250 | 2 | shorten | `skills/varde-docs/references/refresh.md:11` | Many docs + varde-code: load cli ref, context_pack | Optional optimization; "many" undefined. |
| 263 | 2 | shorten | `skills/varde-review/references/scan.md:26` | Weigh rule definition, unseen context; certainty and clone bands are hints | Partly default reasoning. |
| 264 | 2 | shorten | `skills/varde-review/references/simplify.md:7` | Preserve behavior; readability over brevity; keep earned abstractions; no nested ternaries | Mostly defaults; keep "no nested ternaries" only if a preference. |

## D: rare edge cases (user decides per row) (7)

| # | Score | Verdict | Location | Instruction | Why |
|---|---|---|---|---|---|
| 219 | 2 | script | `skills/varde-knowledge/references/handoff-resume.md:32` | Legacy link: git root checks, git diff head_sha; nonempty modified | Legacy path; could be a script mode or dropped. |
| 226 | 2 | shorten | `skills/varde-agent-doc-authoring/references/criteria.md:129` | Name a path after 'skip' in entry file to drop it from route metrics | Niche metrics feature; one clause suffices. |
| 230 | 2 | shorten | `skills/varde-change/references/build-execution.md:124` | "Undo a completed implementation task with `git revert`." | Rarely needed at completion; move to a gotcha or cut. |
| 235 | 2 | shorten | `skills/varde-change/references/build-finish.md:46` | Agent-document findings: bounded change, record in Progress, no review folder | Edge route; could point to review-gates. |
| 247 | 2 | shorten | `skills/varde-change/references/plan.md:214` | Plan id change: rename, validate, rerun review, replace subject id | Rare edge case; long. |
| 251 | 2 | shorten | `skills/varde-knowledge/SKILL.md:18` | Outside the repo, use plain file ops instead of git | Relevant for git mv; wording ambiguous. |
| 252 | 2 | shorten | `skills/varde-knowledge/references/handoff-resume.md:36` | Missing baseline, other repo, external, dir, failure: unknown; drop 'because' rationale | Catch-all label; rationale unneeded. |

## D decisions (user, 2026-09-30)

- 219 handoff-resume.md:32 legacy links: cut (no legacy handoffs in use).
- 230 build-execution.md:124 `git revert`: keep.
- 235 build-finish.md:46: shorten; keep "no review folder".
- 247 plan.md:214 plan id change: shorten; keep all four steps.
- 251 varde-knowledge SKILL.md:18: shorten to "outside a repo, use mv, not git mv".
- 252 handoff-resume.md:36: shorten; drop rationale, keep the list.
- 226 criteria.md:129: shorten to one clause.

Remaining batches: batch-3.md (varde-change, shared; 99 rows), batch-4.md (review, docs, manage, toz; 42), batch-5.md (learn, knowledge, doc-authoring, explore, prototype; 88).
