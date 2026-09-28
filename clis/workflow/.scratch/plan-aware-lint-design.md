# Design draft: plan-aware lint for varde-docs

Status: proposal / spar draft. Authored from the varde-skills side to sketch
the one piece of the skills↔varde-docs integration that needs new work *in
this repo*. Not a committed decision.

## Why this exists

varde-docs already stores, searches, and version-checks plan docs as generic
markdown — that needed no scope change. The one additive capability the
skills would benefit from is a **deterministic, LLM-free health check for
plan docs**, mirroring how `--okf` is "just a lint on top" of generic CRUD.

A plan-aware lint is reusable across `varde-plan` (readiness gate),
`varde-build`, and `varde-orchestrate` (all three currently re-derive plan
consistency by reading files), and it's fast and reproducible where those
checks are mechanical.

## The scope decision this forces (read first)

Storing plan markdown is generic. **A *plan-aware* lint is not** — it encodes
knowledge of a specific bundle type (plan.md + tasks/), which is exactly the
"workflow-specific bundle types … stay out; keep a generic OKF store" line the
README draws. Adding
this lint **reverses that line for lint specifically.** Three ways to go:

- **A. Add it here** as an opt-in lint profile (below). varde-docs gains a
  plan bundle type; the README scope note is amended.
- **B. Keep it in the skills.** `varde-plan`/`build`/`orchestrate` keep doing
  these checks as skill logic (some already do). No scope change; no reuse,
  and each skill re-implements.
- **C. Split.** The *generic* graph/consistency checks that any nested bundle
  could want (dangling links, orphan files, id/file consistency) go in the
  engine as generic lint; the *plan-semantic* ones (readiness, GWT shape,
  task-field presence) stay in the skills.

Recommendation: **C**, leaning toward a thin engine surface. Put in the engine
only what is (1) purely structural/deterministic and (2) plausibly useful
beyond plans; keep plan-semantic judgment in the skill. This keeps varde-docs
generic and honest to its current scope while still removing the repetitive
graph checks from the skills.

## Candidate checks

Grouped by where C would put them.

### Generic (engine — extends default `lint`, no plan knowledge)
- **Dangling links** — a markdown link to a bundle path with no target file.
- **Orphan concepts** — a `.md` nothing links to (report, never a failure).
- **Reserved-name misuse** — `index.md`/`log.md` used as a concept.
- (These overlap with what `lint` likely already reports — confirm before
  duplicating.)

### Plan-semantic (candidate `lint --plan`, IF choosing A; else stays in skill)
Operates on a plan bundle = a dir with `plan.md` + `tasks/<id>.md`.
1. **Readiness signal** — count unresolved `## Open Questions` and
   `## Assumptions` entries. Report `ready` (both empty) vs `N open`. Never
   blocks — the readiness *report*, not a gate.
2. **Section completeness** — required headings present in `plan.md`
   (Problem, Solution, Tasks, Acceptance criteria). Missing → warn.
3. **Task ↔ file consistency** — every id under `## Tasks` has a
   `tasks/<id>.md`; every `tasks/*.md` is listed. Report dangling / orphan.
4. **Task-field presence** — each task file has the expected fields
   (observable outcome, verification command, `test_approach`, dependencies).
   Presence only — not quality.
5. **Dependency graph** — task `dependencies` reference existing ids; no
   cycles; report a topological order.
6. **AC shape** — acceptance-criteria entries match Given/When/Then
   (regex-detectable form), not prose.
7. **Status lifecycle** — `plan.md` frontmatter `status` is a known value
   (`idea|draft|backlog|…`); flag unknown/terminal-invalid transitions.

Checks 1–2, 4, 6, 7 are plan-*semantic* (skill territory under C). Checks
3 and 5 are pure graph/consistency and are the strongest case for the
engine even under C — but they need the plan schema (what "tasks" and
"dependencies" mean), so they're only generic if expressed as a small
declarative bundle schema the engine consumes rather than hardcoded plan
logic. That schema idea is the crux of the A/B/C call.

## CLI surface (if A)

Mirror `--okf`: a composable profile flag on the existing `lint` command.

```sh
varde-docs lint --bundle <plan-dir> --plan --json
```

- Same never-blocks contract as `--okf`.
- Same output/exit-code envelope as the rest of the CLI.
- `--plan` and `--okf` composable (though rarely both apply to one bundle).

## Open questions for the spar

- **A, B, or C?** This is the real decision — everything else follows.
- If C: is a **declarative bundle-schema** mechanism (so id/file + dependency
  checks are generic, driven by a schema file, not hardcoded) worth building,
  or is that over-engineering for one bundle type?
- Which checks does the **existing default `lint` already cover**? Don't
  duplicate — confirm against `okf-core/src/lint/` first.
- Do `varde-build`/`varde-orchestrate` actually want to *call* this, or only
  `varde-plan`? That determines whether engine reuse pays for itself vs B.
```
