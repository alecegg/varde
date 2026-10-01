| # | Score | Verdict | Location | Instruction | Why | Group |
|---|---|---|---|---|---|---|
| 11 | 0 | cut | `skills/varde-review/references/report.md:34` | Pass the plan id to every delegate | Delegates write nothing (report.md:71); plan id unused. | 0-1 |
| 12 | 0 | cut | `skills/varde-review/references/visual.md:3` | Inspect running UI for layout, spacing, hierarchy... | Restates SKILL.md route and description. | 0-1 |
| 105 | 1 | cut | `skills/varde-review/SKILL.md:12` | Carry its verdict through execution and completion, including this skill's changes | review-gates.md owns verdict lifecycle; same sentence in varde-docs and varde-manage SKILL.md. | 0-1 |
| 106 | 1 | cut | `skills/varde-review/SKILL.md:44` | Outside the repo, use plain file ops instead of git | Default behavior; git fails visibly outside repos. | 0-1 |
| 107 | 1 | cut | `skills/varde-review/references/fix-pass.md:35` | Apply only the selected solution | Restates step 2. | 0-1 |
| 108 | 1 | cut | `skills/varde-review/references/fix.md:54` | Executor: follow fix-pass.md for given IDs or route | Repeats fix.md:17 and dispatch instructions. | 0-1 |
| 109 | 1 | cut | `skills/varde-review/references/fix.md:55` | Executor: no triage or companion plan; keep Escalated notes | Repeats fix.md:3-5. | 0-1 |
| 110 | 1 | cut | `skills/varde-review/references/fix.md:61` | Return review folder and deferred findings to parent | Repeats fix.md:18-20. | 0-1 |
| 111 | 1 | cut | `skills/varde-review/references/report-categories.md:5` | Finding discipline in report-format.md sets evidence bar | Readers already load Finding format, which contains it. | 0-1 |
| 112 | 1 | cut | `skills/varde-review/references/report-categories.md:63` | Swallowed error rates by data loss it hides | Default severity reasoning. | 0-1 |
| 113 | 1 | cut | `skills/varde-review/references/report.md:19` | Use --help for targets; inspect consumers, follow area's consumption path | --help implied; consumer reading duplicates step 6 "affected callers". | 0-1 |
| 114 | 1 | cut | `skills/varde-review/references/report.md:53` | Suggest varde-change build refactor posture for complexity/readability findings | Advice agent can offer unprompted; no evidence of need. | 0-1 |
| 115 | 1 | cut | `skills/varde-review/references/scan.md:18` | (or gateRules; not both) | CLI help and validation state it. | 0-1 |
| 116 | 1 | cut | `skills/varde-review/references/scan.md:74` | Suppressions remove findings before gating | Implementation detail. | 0-1 |
| 117 | 1 | cut | `skills/varde-review/references/simplify.md:3` | Simplify edits inline and reports to caller; no findings store | Descriptive; workflow steps imply it. | 0-1 |
| 118 | 1 | cut | `skills/varde-review/references/visual.md:69` | Bring the app window forward | Default. | 0-1 |
| 119 | 1 | cut | `skills/varde-review/references/visual.md:78` | One finding per problem; uninspected concern isn't a finding | Covered by Finding discipline. | 0-1 |
| 120 | 1 | cut | `skills/varde-review/references/visual.md:90` | User asks to fix -> run fix.md on this review | SKILL.md:8-9 and route table cover it. | 0-1 |
| 144 | 1 | merge→`skills/varde-review/references/report-format.md:56` | `skills/varde-review/references/report-format.md:60` | Numbers carry their sample boundary | Special case of "show the check". | 0-1 |
| 145 | 1 | merge→`skills/varde-review/references/report.md:72` | `skills/varde-review/references/report.md:43` | Verify every high or critical finding yourself | Repeated at report.md:72 and report-format.md:54. | 0-1 |
| 146 | 1 | merge→`skills/varde-review/references/report-format.md:84` | `skills/varde-review/references/visual.md:80` | Screenshot path as Location; route/viewport in Summary | report-format.md:84-86 owns it. | 0-1 |
| 147 | 1 | merge→`skills/varde-review/references/report-categories.md:7` | `skills/varde-review/references/visual.md:83` | Label design choices triage; auto-fix only when mirrors style | Restates auto-fix rule; internally redundant. | 0-1 |
| 158 | 1 | shorten | `skills/varde-review/references/report-categories.md:54` | PERFORMANCE When: unbounded loops, hot paths, I/O in loops | Self-evident relevance. | 0-1 |
| 159 | 1 | shorten | `skills/varde-review/references/report-categories.md:60` | OBSERVABILITY When: new failure mode, external call, background op | Self-evident relevance. | 0-1 |
| 160 | 1 | shorten | `skills/varde-review/references/report-categories.md:67` | READABILITY When: names, comments, structure; not generated code | Self-evident relevance. | 0-1 |
| 161 | 1 | shorten | `skills/varde-review/references/report-categories.md:74` | RESILIENCE When: external calls, I/O, partial failure | Self-evident relevance. | 0-1 |
| 162 | 1 | shorten | `skills/varde-review/references/report-categories.md:82` | DATA-INTEGRITY When: persistent writes, shared state | Self-evident relevance. | 0-1 |
| 163 | 1 | shorten | `skills/varde-review/references/report-categories.md:90` | API-DESIGN When: public signature, type, flag, endpoint | Self-evident relevance. | 0-1 |
| 164 | 2 | cut | `skills/varde-review/references/fix-pr.md:3` | One-shot, read-only intake building local review folder | Descriptive; steps imply it. | A: merge within skill |
| 206 | 2 | merge→`skills/varde-review/references/fix.md:49` | `skills/varde-review/SKILL.md:45` | At end of write flow record obstacles via varde-learn, decisions via varde-knowledge | Duplicated in fix.md:49, refresh.md:29, spec.md:35; keep one per skill. | A: merge within skill |
| 207 | 2 | merge→`skills/varde-review/references/fix.md:76` | `skills/varde-review/references/fix.md:77` | Size wins: large high-severity fix is action-item | Fold into previous bullet. | A: merge within skill |
| 208 | 2 | merge→`skills/varde-review/references/fix-pass.md:15` | `skills/varde-review/references/fix.md:87` | Disposition alone doesn't approve solution; keep decision history | Same rule at fix-pass.md:15-16. | A: merge within skill |
| 209 | 2 | merge→`skills/varde-review/references/scan.md:3` | `skills/varde-review/references/scan.md:44` | Report every finding: fixed, not-real reasons, left for user | Restates the opening contract. | A: merge within skill |
| 250 | 2 | shorten | `skills/varde-docs/references/refresh.md:11` | Many docs + varde-code: load cli ref, context_pack | Optional optimization; "many" undefined. | C: shorten to one clause, keep direction |
| 256 | 2 | shorten | `skills/varde-manage/references/scan-author.md:55` | kind: pattern or sql | Visible in every seeded rule. | B: cut prose restating script/CLI; may move a needed fix hint into that script message |
| 257 | 2 | shorten | `skills/varde-manage/references/scan-author.md:56` | severity values, case-insensitive | Visible in seeded rules. | B: cut prose restating script/CLI; may move a needed fix hint into that script message |
| 258 | 2 | shorten | `skills/varde-manage/references/scan-author.md:58` | message is finding headline | Visible in seeded rules. | B: cut prose restating script/CLI; may move a needed fix hint into that script message |
| 259 | 2 | shorten | `skills/varde-manage/references/scan-author.md:59` | pattern or query per kind | Visible in seeded rules. | B: cut prose restating script/CLI; may move a needed fix hint into that script message |
| 260 | 2 | shorten | `skills/varde-manage/references/setup.md:39` | Row: Toz config root precedence (env, XDG, legacy) | `varde-toz doctor --json` reports the root (setup.md:43). | B: cut prose restating script/CLI; may move a needed fix hint into that script message |
| 262 | 2 | shorten | `skills/varde-review/references/report-format.md:50` | Imported PR feedback/scan candidates pending triage; severity only routing | fix-pr.md:54 and scan.md:59 already set Label/Severity. | A: merge within skill |
| 263 | 2 | shorten | `skills/varde-review/references/scan.md:26` | Weigh rule definition, unseen context; certainty and clone bands are hints | Partly default reasoning. | C: shorten to one clause, keep direction |
| 264 | 2 | shorten | `skills/varde-review/references/simplify.md:7` | Preserve behavior; readability over brevity; keep earned abstractions; no nested ternaries | Mostly defaults; keep "no nested ternaries" only if a preference. | C: shorten to one clause, keep direction |
