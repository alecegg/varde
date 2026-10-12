# Plan

## Resume a draft

When asked to resume planning with no feature named:

- **Find drafts.** A draft is a `plan.md` with `status: backlog` and an id
  ending in `-draft` or `-draft-<n>`, or a live Open Questions bullet. Search
  at any depth under `<working>/plans/`. Nested child plans count; their id is
  their path, such as `<group-id>/<child-id>`.
- **Ask.** List every draft as a numbered `title - plan id` list and ask which
  to resume, then continue with [The growth loop](#the-growth-loop). If there
  are none, wait for the user's idea and [start a plan](#start-a-plan).

## Start a plan

### First turn

Include `varde map context_pack` with feature terms when available. In the
same read-only discovery call, scan `<working>/reviews/deferred/`.

1. Pick a temporary slug from the prompt and run
   `scripts/plan-path.py draft --working <working> --slug <slug>`; it creates
   and prints the draft directory, whose name is the plan id until
   finalization. Create `plan.md` there from `assets/PLAN-TEMPLATE.md` with
   Write/Edit, and set `title` to the initial prompt.
2. Seed genuine best guesses immediately in the template's formats, including
   Given/When/Then criteria and every unknown as an Open Question or Assumption.
   List deferred findings with a blank `Disposition` and an in-scope `Location`
   as Open Questions with their review date, deduplicating copies by `Source`
   and original id. The user decides to include or defer; never add one
   automatically.
3. Tell the user the plan path and welcome direct edits. Ask the one highest-value question per
   [Asking questions](#asking-questions), then wait.

## The growth loop

Each turn, research what the repo can answer. Load
`references/varde-code-cli.md` only when `varde` is on PATH and scope or
dependents are unknown.

### Routing unknowns

Route every unknown instead of blocking; impact beats confidence:

- **Code or search can answer it:** research it; don't list it.
- **Confident, and a wrong guess stays inside one Design subsection:**
  `## Assumptions` with `confidence: high`; don't spend a turn.
- **Needs something concrete** (an open UI shape, interaction feel, a state
  model, or a layout tradeoff visible only once built): mark it
  `[needs prototype]`, invoke `varde-prototype`, and resume with its answer.
  Skip this when the UI shape is already settled.
- **Everything else** (unsure, or touching the plan split, AC, an external
  contract, or solution shape): `## Open Questions` with a recommendation, and
  ask.

**Push back.** Challenge the idea and propose a better, smaller shape when
you see one:

- If the scenario is speculative or an existing capability seems to cover it,
  offer do-not-build ("This looks like [X] already covers it. Build anyway, or
  is this a non-issue?").
- Close as do-not-build only on explicit agreement, then discard the plan
  directory.

### Terminology and standards

Once the seed makes the domain concrete, search `<knowledge>/` for the
feature's specs, decisions, definitions, and patterns:

- Link the ones that apply under `## Related`.
- Put any that look stale into `## Open Questions` as one item.
- Record a missing definition with `varde-knowledge`.
- When `<knowledge>/specs/<domain>.md` covers code this plan changes, add the
  domain to `observed_specs` and pass its spec file at Finalize step 3's
  `review init` (`--scope`, or `--artifact <absolute-file>` outside the
  repository); after init, add it with `review expand` and a fresh pre-edit
  verdict.

### Per-turn steps

1. **Watch the doc.** Re-read `plan.md` and diff it against your last
   snapshot. A change you did not make to `## Open Questions`,
   `## Assumptions`, `## Design`, `## Non-goals`, or `## Constraints` is a
   user edit that counts as an answer; process it with the chat message.
2. **Resolve items.** Write each decision into its `## Design` subsection (or
   Non-goals/Constraints) in the template's form, append
   `<question> → <answer>` to `## Decisions so far`, remove the resolved
   line, and add any unknowns the answer exposes. An accepted assumption moves
   to the decision log too.
3. **Ask** the highest-value Open Question per [Asking questions](#asking-questions),
   solution-shape questions before spelling ones.

Throughout:

- **Single writer.** Only this session edits `plan.md`. Research subagents get
  the resolved absolute `<working>` and `<knowledge>` paths, use them without
  re-resolving storage, and return findings.

### Exit criteria

Each turn, route implicit assumptions in Design/AC per
[Routing unknowns](#routing-unknowns). Run [Self-review](#self-review) when
`## Open Questions` first has no live item, and again at Finalize. Finalize
when `## Open Questions` has no live item and the final self-review finds
nothing new.

## External interface check

If a touched surface has existing consumers (exported API, CLI flag, env var,
CI config, shared type, or a file others read), flag it explicitly and find
them with `dependents`/`blast_radius` from `varde map` and
`references/varde-code-cli.md`, or grep otherwise. Record them in Design and
AC.

## Self-review

When run, an empty `## Open Questions` is not done. Add an Open Question for
each of these and continue:

- placeholders (TBD, vague Design);
- contradictions between decisions;
- scope the Solution implies but Non-goals omits;
- decisions admitting two implementations.

When scope outside fenced code blocks adds a second case to a formerly
single-case model, makes a required field optional, or turns a derived or
fixed value into a choice, and `## Decisions so far` does not already resolve
that shift, add one Open Question: promote the general model, or add it
alongside the old one?

## Acceptance criteria

Criteria are plan-level: true after ship, however build slices it. Review the
full set before the final completeness check:

- **`assert:`** (preferred): a command, grep, or test whose pass/fail needs no
  LLM judgment.
- **`retrieve:`**: the file(s) or grep an LLM must read and judge, and what it
  looks for. An agent grading text it just produced is biased, so first try to
  restate it as `assert:` (command, exit code, file existence, non-empty
  output). Keep it only for semantic judgment no command can give, such as
  whether an error message explains the cause.
- **Testable as written:** each criterion names a command or a file a reader
  judges.

## Finalize

1. **Rename and validate.**
   - Derive the slug from the plan's title or problem (lowercase, hyphenated)
     without asking, and run
     `scripts/plan-path.py finalize --draft <plan-dir> --slug <slug>`. It
     renames the directory, keeping the draft's date, and prints the new path
     and `ignored: true|false`; record `ignored`.
   - Run `varde work validate <plan-dir>/plan.md --json` and fix
     diagnostics before review.
2. **Split or decompose before review.** For several independently shippable
   changes, [split](#split-into-child-plans) first: the parent gets no tasks. Otherwise follow `references/plan-decomposition.md`.
3. **Establish review location and review.** Establish the visible plan
   worktree per `references/build-worktree.md` without committing before step
   5's approval (unless a specific checkpoint is already authorized); map tracked
   plan files there, retain external storage, and initialize the exact-root subject
   (`review init --plan <plan.md>`, with `observed_specs` files) per
   `references/review-gate-plan.md` §1 and `references/review-gates.md`.
   Give an independent reviewer the plan/tasks, subject/scope, and resolved
   `<working>`/`<knowledge>` paths to check splits, execution-wave independence,
   context estimates, assumptions, human choices, criteria, and shippability.
   It inspects `pre-edit` and writes its own `varde work review record`; keep
   the subject id in plan Progress for build/resume.
4. **Apply the review.** Apply findings and review every criterion per
   [Acceptance criteria](#acceptance-criteria), investigating code-answerable
   unknowns and returning human decisions to the interview. For several
   changes, follow [Split into child plans](#split-into-child-plans) instead of
   step 5. Revalidate after edits; a materially changed plan needs fresh
   inspection and independent approval, otherwise the approved verdict carries
   to build.
5. Ask the **final completeness check**: unseen assumptions and changes from
   steps 2-4, one line each, grouped by impact. Link the plan and approval
   worktree, branch/base; explicitly request local plan/task commit
   authorization while reserving target integration for separate approval.
   Ask "Anything left to resolve before we finalize?" Wait for confirmation;
   apply requested changes, revalidate/review, and repeat when needed.

6. After confirmation, no more questions or content changes. The plan stays
   `backlog` until build moves it to `active`.
7. Reuse step 1's reported `ignored` value: ignored plans stay local;
   otherwise commit only the plan directory on its authorized plan branch,
   never the user's target branch.
8. Announce that `Plan <plan-id> is ready; ask to build it.`

### Split into child plans

Use this at Finalize step 2, or step 4 when review finds several shippable
changes; from step 4, first delete the parent's task files and note in
Progress that its subject is abandoned.

1. List candidate titles and dependency order. Ask whether any should be
   combined or split differently, then wait.
2. Establish one visible group plan worktree per
   `references/build-worktree.md` as the exact approval root for parent and
   children, before their finalization reviews. Create nested child plans at
   `<working>/plans/<plan-id>/<child-slug>/plan.md`. The path gives each child
   its compound id and group membership, so no `children:`/`parent:` fields
   are needed. Finalize each child with Finalize step 1's validate only
   (never `plan-path.py finalize`), then steps 2-8; build decomposes each
   later.
3. Keep the current plan as the group parent with `shape: group` in
   frontmatter. Keep its goal, non-goals, constraints, and aggregate contract
   outside Progress: source scope, child ids/dependencies/contracts,
   assumptions, and aggregate acceptance/verification. Validate it, then
   initialize its subject over the aggregate source scope (Finalize step 3's
   `review init --plan`, with the owning approval repoRoot). Get independent
   `pre-edit` approval of the combined contract in the same reviewer session
   as the children's step 3 reviews, one record per subject; keep the subject
   id in the parent's Progress. Commit the parent with its children only on
   the authorized group plan branch when storage is tracked, then finish the
   parent with Finalize steps 7-8 only.

## Asking questions

Up to three questions may share a turn when they are facets of one decision
or share candidate solutions, such as naming sibling commands or edge cases of
one input. Silence and surrounding context leave the decision open. Use this
menu:

```
<Question>

  1. <Option A>
  2. <Option B>
  3. Other - describe what you want

Recommendation: <n> (<label>) - <one-sentence reason>.
```
