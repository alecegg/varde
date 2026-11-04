---
topic: varde-manage/presets
version: 1
summary: Sync presets, selection closure, and orchestration retention
---

| Preset | Includes |
|---|---|
| `toz` | Captured output. |
| `doc` | Doc tools. |
| `knowledge` | Project knowledge. |
| `learn` | Diagnosis, friction, evals. |
| `code` | Code, scans, rules. |
| `dev` | Explore and prototype. |
| `workflow` | Plan, build, review, plus the required code, doc, development, knowledge, and Toz modules (11 skills). |
| `full` | All skills. |

Sync selects managed instruction sections and hook features from the
`requires` closure of the selected skills (or all skills when no selection is
saved).

- For configured instruction targets and synced harnesses, `workflow`, `full`,
  and default all-skills installs retain orchestration.
- A hand-picked list without `varde-orchestrate` drops orchestration and the
  inbox hook on the next sync.
- Selecting `varde-learn` adds learn guidance to the optional Varde section of
  the shared instruction block; deselecting it removes that section.
