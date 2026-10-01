| # | Score | Verdict | Location | Instruction | Why |
|---|---|---|---|---|---|
| 3 | 0 | cut | `skills/varde-docs/references/spec-format.md:4` | Format for domain docs, architecture, index | Restates title and loader. |
| 4 | 0 | cut | `skills/varde-docs/references/spec-manual-inventory.md:4` | Load this fallback only when spec inventory unavailable or fails | Loader (spec.md:60) already gates it. |
| 10 | 0 | cut | `skills/varde-manage/SKILL.md:26` | Resolve <working>/<knowledge> via paths --json; outside repo use file ops | No varde-manage reference uses <working> or <knowledge>. |
| 74 | 1 | cut | `skills/varde-docs/SKILL.md:8` | Carry its verdict through execution and completion | review-gates.md owns it. |
| 75 | 1 | cut | `skills/varde-docs/references/spec-format.md:73` | Plan's observed_specs may list architecture | Consumer fact, not an action here. |
| 76 | 1 | cut | `skills/varde-docs/references/spec.md:87` | Row missing/stale: refresh per Architecture above | Restates spec.md:79. |
| 96 | 1 | cut | `skills/varde-manage/SKILL.md:10` | Carry its verdict through completion | review-gates.md owns it. |
| 97 | 1 | cut | `skills/varde-manage/references/scan-author.md:139` | clone_bands approximate, not proof | Stated in scan.md:29; exact-clone covers proof. |
| 98 | 1 | cut | `skills/varde-manage/references/scan-author.md:152` | GROUP BY HAVING; MIN(start_line) | Standard SQL. |
| 99 | 1 | cut | `skills/varde-manage/references/scan-author.md:195` | rules_seed --user writes built-ins; rules_remove undoes | rules_seed --help states both. |
| 100 | 1 | cut | `skills/varde-manage/references/scan-author.md:62` | Recommended fields name, description, remediation | Unvalidated; seeded rules show them. |
| 101 | 1 | cut | `skills/varde-manage/references/scan-author.md:82` | test: self-tests; scan ignores them | Covered by Test entries section. |
| 139 | 1 | merge→`skills/varde-manage/references/scan-author.md:12` | `skills/varde-manage/references/scan-author.md:125` | Worked queries via rules_list; start from closest | Repeats workflow step 3. |
| 140 | 1 | merge→`skills/varde-manage/SKILL.md:30` | `skills/varde-manage/references/setup.md:33` | Inspect existing config and help; preserve overrides | Same rule in SKILL.md:30-31. |
| 141 | 1 | merge→`skills/varde-manage/SKILL.md:32` | `skills/varde-manage/references/setup.md:53` | Report diagnostics and failures separately | SKILL.md:32-33 owns reporting. |
