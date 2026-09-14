# Workflow Simplification Review

> Historical review. The implementation notes below describe a superseded
> isolation-first design. Current defaults are local execution, direct task
> work, and sequential processing. Use a worktree only for an explicit request
> or concrete concurrent-edit risk, except long autonomous feature/spec runs.
> `varde-simplify` always runs where its input diff already exists. Delegation
> is optional and capped at three concurrent delegates. Reflection still runs at
> every top-level workflow close, but it saves nothing unless the result is
> valuable.

Comparison of the `varde-*` skill workflow (plan / orchestrate / build) against
reference methodologies: **superpowers**, **gsd-core**, **compound-engineering-plugin**,
**builderio-skills**, and Matt Pocock's **skills**.

## Verdict

The **SKILL.md layer is already lean** (62–127 line entry files fanning out to
references) — matches best practice everywhere. Over-complication is concentrated
in the **build orchestration model** and the **git-isolation layering**, and it
contradicts the project's own stated philosophy: *"Favor spawning for keeping
context clean, not for multithreading speed."*

## What to keep (do not simplify away)

- Lean SKILL.md + references fan-out (best-in-class progressive disclosure).
- The living-doc planning model (matches superpowers' human-reviewed plan-as-document).
- Immediate-write discipline ("never batch decisions").
- Report-only review with labeled findings feeding `review-fix`.
- `_shared/` + `sync-shared-refs.sh` — already solves reference duplication at author time.

---

## Net changes (implementation checklist)

**Implementation status: complete** (all boxes below checked). Not yet committed;
not yet mirrored to other harness skill dirs (see follow-ups at bottom).

All five items resolved. The agreed end state:

- [x] **`varde-build`** — one plan, tasks run **sequentially in `depends_on`
  order**, unattended. Delete batching, file-conflict grouping, per-batch
  integration, re-derivation loop. One staging worktree; commit per task; one
  final merge to base. Always isolate. Bounded task-verify retry (2) →
  fail-closed. (Items 1, 2, 5)
- [x] **`varde-orchestrate`** (new, thin <150 lines) — walks a feature's
  plan-level `depends_on` DAG **one plan at a time, sequential, unattended,
  fail-closed**; delegates each plan to `varde-build`; one feature worktree;
  single final merge to base; thin resume from frontmatter + run-state marker.
  Cedes to `varde-build` for a single plan. (Items 1, 2, 3)
- [x] **`varde-worktree`** — becomes the single isolation seam; `plan`, `build`,
  `orchestrate`, `review-fix`, `simplify` call it and never re-describe
  mechanics; skip when already inside a caller's worktree. (Item 2)
- [x] **State** — task frontmatter + `plan.md` are the sole progress source;
  delete the event ledger; keep one minimal capped run-state file (worktree
  anchor + halt/event trail); **drop per-plan `index.md`** and its regenerate
  steps everywhere. (Item 3)
- [x] **`define`** — dropped; terminology + readiness fold into `plan`,
  standards into `varde-knowledge` / inline planning; migrate/delete its
  references. (Item 4)
- [x] **Review cluster** — keep `review` / `review-fix` / `simplify`; tighten
  TRIGGER/SKIP so `simplify` vs `review` don't compete. Review→fix capped at 1
  round then defer. (Items 4, 5)
- [x] Update triggering guards so `build` ("a plan") and `orchestrate` ("a
  feature / all its plans") route cleanly. (Item 1)

### Follow-ups (not done)

- **Mirror to other harness skill dirs** per global note: `~/.config/opencode/skills`,
  `~/.codex/skills`, `~/.pi/agent/skills` (add `varde-orchestrate`, remove
  `varde-define`, update the changed `varde-build`/`varde-plan`/etc.).
- **Not committed** — changes are staged in the working tree only.
- **Breaking changes** to skill contracts (no more staging branch / ledger /
  `index.md` / `varde-define`). Any in-flight plan bundles written under the old
  model would need a migration note or clean cutover.
- The **review folder's** `index.md` was intentionally kept — it has a real
  consumer (`review-fix`), unlike the dropped per-plan nav.

## Resolved items (discussion record)

Each item below is discussed one at a time. Once resolved, the agreed solution is
recorded under **Resolution**.

### Item 1 — Parallel batching in `varde-build` (biggest complexity center)

**Problem.** `varde-build` step 5 derives dependency-ready tasks → groups them into
non-file-conflicting batches → dispatches each batch to isolated worktree subagents
→ runs a per-batch integration merge → re-derives readiness → repeats. This exists
to run tasks *concurrently*, which contradicts the project's own "spawn for clean
context, not speed" note. Peers (superpowers) run one task at a time: implementer
subagent → reviewer subagent → next.

**Status:** ✅ resolved

**Resolution — sequential build + two-skill split + unattended chain.**

Decisions:

1. **Delete intra-plan parallel batching.** `varde-build` runs one plan's tasks
   **sequentially, in `depends_on` order**, unattended. Remove file-conflict
   batch grouping, per-batch integration stages, and the re-derivation loop.
   Dependency ordering stays (it's correctness, not parallelism). Rationale:
   parallelism's only benefit is wall-clock speed, which the project explicitly
   deprioritizes ("spawn for clean context, not speed"), and concurrent
   subagents actively fight the "≤3 subagents" and usage-caution constraints.
   Still one subagent per task → clean-context isolation is preserved.

2. **Split large work at plan time, not with intra-plan parallelism.** "Long
   plan" is really three separate pains: wall-clock (unfixable, not a priority),
   reviewability, and recoverability. The latter two are solved by splitting a
   feature into small, file-disjoint plans (planning already does this) — each
   an independently reviewable/recoverable unit. Plans split along
   subsystem/surface boundaries are file-disjoint **by construction**, so
   running a set needs no conflict resolution — just an ordered walk.

3. **Two skills, not one skill with modes:**
   - `varde-build` — executes **exactly one plan**: sequential, unattended,
     dependency-ordered, ends at its merge/stop gate. Knows nothing about
     chains. The simplest possible leaf executor.
   - **`varde-orchestrate`** (new, thin coordinator, target <150 lines) —
     resolves a feature's plan-level `depends_on` DAG, walks it in dependency
     order **one plan at a time**, invokes `varde-build plan=<id>` per plan,
     owns the feature-level staging branch, and handles fail-closed halting +
     chain resume. Delegates all execution. When it finds a single plan, it
     cedes straight to `varde-build` and adds nothing.
   Rationale: builderio's lesson — separate orchestration from implementation,
   keep the orchestrator thin. Boundary is sharp (one plan vs. a set), so this
   is clean separation, not the fuzzy overlap Item 4 targets.

4. **Unattended ≠ parallel.** The user wants to kick off a whole feature after
   planning and walk away (planning effort already spent; re-asking is
   redundant). `varde-orchestrate` runs the whole set **sequentially and
   unattended**, stopping only on failure/blocker/completion (fail-closed): a
   blocker in plan C halts the chain, leaves A/B merged, and reports where it
   stopped.

5. **Recovery machinery is justified for the unattended chain** (a long
   no-human-watching run is exactly when crash-resume matters) but keep it
   thin: resume at a plan/task boundary derived from frontmatter + a small
   chain-state marker — not a parallel-batch event log.

**Triggering guard (must be crisp to avoid mis-routing):**
- `varde-build` — "run/execute **a plan**" (object = a specific plan).
- `varde-orchestrate` — "build **a whole feature** / run **all its plans** /
  ship the split set" (object = a feature spanning multiple plans).

**Downstream:** isolation unit becomes one worktree per feature — see Item 2.
(Refined there: plans in an orchestrated run do **not** merge into a staging
branch; they commit into the single feature worktree, and there is exactly one
merge to base at the end.)

### Item 2 — Three levels of git isolation

**Problem.** `varde-plan` opens a worktree; `varde-build` creates a staging branch
*and* per-task worktrees branched off it, merges each into staging, then does one
atomic merge to the original branch. Isolation logic is threaded through plan, build,
review-fix, and simplify independently. superpowers uses one worktree per task;
gsd-core has one worktree-safety seam.

**Status:** ✅ resolved

**Resolution — one worktree per top-level operation, single seam, commit-per-task.**

Decisions:

1. **One worktree layer per operation, never stacked:**
   - `varde-plan` → one worktree for the planning session.
   - `varde-build` (single plan) → one staging worktree; tasks run sequentially
     inside and **commit per task**; exactly **one** final merge to base.
   - `varde-orchestrate` (feature) → one feature worktree; plans run
     sequentially inside, committing as they go; **no per-plan branches, no
     intermediate merges**; one final merge to base.
2. **Delete per-task worktrees and the staging-branch + per-task stacking.**
   With sequential execution, tasks share one working dir; git commits provide
   the per-task/per-plan granularity that separate branches used to. Per-task
   isolation existed mainly to keep parallel subagents apart — Item 1 removed
   that need.
3. **Single seam.** All worktree mechanics route through the `varde-worktree`
   skill (gsd-core's one-worktree-safety-module lesson). `review-fix` and
   `simplify` reuse it and **skip when already inside a caller's worktree**.
   No skill re-describes worktree mechanics.
4. **Fail-closed falls out for free.** A failed plan/task just means the final
   merge doesn't happen; the worktree holds the partial work for resume; base
   stays clean. "Base branch touched exactly once per operation" is the
   invariant.
5. **Always isolate**, even for a 1–2 task plan. Uniformity over a size-based
   special case; it's what makes the base-touched-once invariant hold
   everywhere.

### Item 3 — State lives in too many places

**Problem.** Run state is spread across `plan.md ## Tasks`, per-task frontmatter
(`status`, `verified`), the `progress.md` ledger, and generated `index.md`. The
ledger largely duplicates task frontmatter. gsd-core's core lesson: one canonical
owner per concern.

**Status:** ✅ resolved

**Resolution — frontmatter is the single source of truth; one minimal run-state
file; drop per-plan `index.md`.**

Decisions:

1. **Frontmatter/`plan.md` own progress; delete the event ledger.** Task
   frontmatter owns task `status`/`verified` (single owner); `plan.md` owns
   plan-level `blocked` and completion. The old `progress.md` ledger tracked
   dispatch/retry/per-batch-merge/cleanup events that no longer exist after
   Items 1–2 — remove it.
2. **Keep one minimal run-state file per operation** (owned by
   build/orchestrate), holding only the non-derivable bits: worktree path +
   branch, plus a **capped, append-only one-line-per-event trail** (plan/task
   started · done · blocked+reason). This is the crash-resume anchor + human
   debug trail for unattended runs, and a fraction of the old ledger.
   Everything else (which plan/task is "current") is **derived**: first plan in
   DAG order not fully done; first task in `depends_on` order not `done`.
3. **Drop the per-plan `index.md` entirely.** Verified against
   `PLAN-RUN.md:39` — plan discovery is "List the plan directories and read
   each `plan.md`'s frontmatter directly." There is **no top-level index file
   and no consumer of `index.md` anywhere**; it was a generated nav cache with
   zero readers. Its one job (list a plan's tasks) is already served by
   `plan.md`'s `## Tasks` section. Dropping it removes the "regenerate
   `index.md`" step from ~8 reference files and eliminates one orchestrator-owned
   generated file from the stale-worktree clobber guard and ownership rules.
   Any nav info still wanted moves into `plan.md`; no separate index file.

### Item 4 — Skill overlap (define vs plan; review vs review-fix vs simplify)

**Problem.** `plan` folds terminology/readiness inline, partly duplicating `define`.
Three review-adjacent skills exist. Matt's `skills` repo solves this with a router +
leaf disciplines and maturity buckets.

**Status:** ✅ resolved

**Resolution — drop `define` (fold into `plan` + `varde-knowledge`); keep the
review cluster, tighten triggers.**

Decisions:

1. **Drop the `define` skill.** Standalone `define` use is atypical; its three
   postures redistribute:
   - **terminology** → already done inline in `plan`'s living-doc loop
     (`DESIGN-VOCABULARY.md`). Delete the duplicate.
   - **readiness** ("are we ready to build?") → already `plan`'s front phase
     (draft doc, route unknowns into `## Open Questions`/`## Assumptions`;
     those gaps *are* the readiness answer). Surface as a `plan`
     readiness-focused entry.
   - **standards** → handled inline during planning when it arises; standalone
     project-standards grooming → `varde-knowledge` (standards are
     `decision`/`pattern` knowledge notes). Accepted trade: standalone loses
     `define`'s guided-interview cadence, acceptable since standalone is rare.
   - Migration: `define`'s references (`postures/`, `MAIN-MENU.md`,
     `QUALITY-CATEGORIES.md`, `TERMINOLOGY-FORMATS.md`) — terminology/readiness
     content merges into `plan` references, standards-interview content into
     `varde-knowledge`, the rest deleted.
2. **Keep the review cluster (`review` / `review-fix` / `simplify`) — no merges.**
   They are three distinct tools with clean boundaries: report-only persisted
   findings / apply-persisted-findings / diff-scoped inline tidy. Merging would
   break the report-only principle or force a findings store onto the
   lightweight inline pass. Only action: **tighten TRIGGER/SKIP** so `simplify`
   ("tidy the diff I just wrote") and `review` ("structured audit with persisted
   findings") never compete for the same phrasing.

**Problem.** Blocker handling is implicit; there is no bounded reviewer→implementer
loop, which is where unattended runs can hang. superpowers caps at N rounds then
escalates/stops.

**Status:** ✅ resolved

**Resolution — bounded caps + fail-closed, no model escalation.**

Decisions:

1. **Every automated retry loop gets an explicit cap.** No unbounded loops —
   critical now that `orchestrate` runs unattended and a spin would burn usage
   silently.
2. **Task-level verify:** on `tsc`/`test` failure, retry up to **2** times;
   still failing → mark the task `blocked`, halt the chain fail-closed
   (completed work stays in the worktree, unmerged), report where and why.
3. **Review→fix:** fix once, re-verify once; any findings still open after that
   round are **reported as deferred, not re-looped**.
4. **No model escalation.** Same model throughout — simpler and keeps usage
   predictable (escalation adds model-selection logic and can spike usage,
   cutting against the project's usage-caution constraint).
5. On any cap exhaustion the behavior is uniform: mark `blocked`, halt, report —
   the human re-engages only at a real stopping point.
