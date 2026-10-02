# Orchestrate mode

Run a group plan's children end to end. Children are nested `plan.md`s; id
`<group-id>/<child-slug>`. The orchestrator never edits production source or
dispatches tasks.

## Route

| The request is | Action |
|---|---|
| Names a group plan | Go to **Order children**. |
| Requests a whole feature without naming a group | **Discover groups**. |
| Names a plan without `shape: group` | Build plan `<id>` (`varde-change build`, named-plan route) and stop. |

## Discover groups

1. Read `<working>/plans/*/plan.md` frontmatter; keep `shape: group` plans with
   at least one non-`completed` child.
2. Present each as `<group-id> — <title>`. If none qualify, report
   `No group plans with unbuilt children. Nothing to orchestrate.`
3. Stop until the user selects one.

## Order children

1. Run `varde-workflow readiness` on each child and order by
   `data.planning_ready` and dependency blockers; leave review blockers to the
   child build. `depends_on` holds sibling slugs only.
2. Skip completed children; completed dependencies are satisfied.
3. A missing dependency blocks its child; a cycle stops the feature. Report
   blockers before any child runs.
4. Run in the current checkout unless the user asks for a
   [feature worktree](#feature-worktree).

## Feature worktree

Use one only when the user asks and group/child plan storage is tracked;
external plan storage stays in the current checkout.

1. Load `references/build-worktree.md`, use id `orchestrate-<group-id>`, and
   validate any reused path/branch before entering it.
2. Map group, child, and task paths to their physical copies in the feature
   checkout. Pass those explicit (mapped) paths and the resolved absolute
   `<working>` and `<knowledge>` paths.

That checkout is the owning approval repository for the group and serial child
builds: initialize and review its own exact-root subjects there, and never copy
main-checkout approvals. Serial children finish their local gates and tracked
state in that checkout, so completed dependencies unlock later children; nested
task isolation that returns `created=false` stays there too.

## Approve and activate the group

1. Read the group and every child contract. Confirm the group's aggregate
   source scope, child IDs/dependencies/contracts, assumptions, and
   acceptance/verification outside Progress match them. Material drift
   updates that contract and needs fresh independent approval before any child
   runs.
2. Load `references/review-gate-plan.md`, then initialize the group's own
   subject over the aggregate source scope (§1, with the group plan and the
   owning approval repoRoot); on resume, reuse the existing subject and never
   reset its baseline.
3. Apply `references/review-gates.md` and obtain independent pre-edit approval
   of the combined contract. Keep each child's own subject and gates; group
   approval does not replace them. Batch the group contract with every child
   needing pre-edit into one reviewer session, recording one verdict per
   subject.
4. Check with `--subject <group-subject-id> --json`; a blocker stops before
   child execution:
   - backlog or blocked group: `review check --checkpoint start`, then
     transition it to active;
   - an active group uses `review check --checkpoint resume`, with no
     active-to-active transition.
5. Commit the activation when plan storage is tracked.

## Delegate children

Run the remaining children sequentially in dependency order, waiting for each
result: build plan `<compound-child-id>` (`varde-change build`, named-plan
route) in the feature location. Give each child the resolved absolute
`<working>` and `<knowledge>` paths; it uses them without re-resolving. Build
owns single-plan execution and review in that owning checkout, and skips its
own merge inside a feature worktree.

When a child blocks or fails, stop immediately: run no later child, merge
nothing, leave commits and partial state as they are, and report the failed
child, the reason, and the completed children.

## Resume

1. Recover any existing feature location, derive progress from child statuses,
   and resume at the first non-`completed` child.
2. On `worktree-create.sh` exit 3, inspect `git worktree list --porcelain`.
   Reuse `.varde/worktrees/orchestrate-<group-id>` only when that path is
   registered with branch `worktree/orchestrate-<group-id>`. A branch-only
   collision or a missing or mismatched worktree stops recovery.
3. Stop when statuses and commits disagree, such as a completed child without
   commits.

## Finish

1. **Triage escalated findings.** Load `references/build-finish.md` and triage
   all children's escalated findings in one combined table per its
   `## 3. Fix findings`.
2. **Release nested bindings.** A live nested task binding must be integrated
   and released at its owning approval checkout before group completion.
3. **Review the group.** After all children are completed:
   1. Verify the aggregate acceptance criteria and combined behavior.
   2. Route remaining findings and source, spec, and documentation edits
      through bounded `varde-change` builds, then run checks.
   3. Obtain an independent entire-group implementation review, using the
      group subject, aggregate contract, child results, and execution
      location; it records current entire-subject evidence per
      `references/review-gates.md`.
   4. Fix its findings per `references/build-finish.md` §3, then refresh the
      group evidence before Conclude (step 4).
4. **Conclude.** Run `varde-workflow review check --subject
   <group-subject-id> --checkpoint complete --json`, then `varde-workflow
   conclude <group-plan.md> --json`. Missing/stale approval or an incomplete
   child blocks conclusion: preserve the active group and recovery refs, and
   never mark it completed by a plain transition or activate it again. A
   feature checkout owning the group subject may conclude against verified
   local source; never conclude a main-checkout subject against unmerged
   feature source.
5. **Commit.** At the owning checkout, commit tracked group conclusion and
   bookkeeping before offering Merge or Push, staging only this group's
   verified paths and preserving unrelated edits.
6. **Offer one choice.** Show the aggregate diff and current branch/worktree
   state, offer the group's applicable choices per
   `references/build-finish.md`'s Finish choices, and execute only the
   one the user makes.
7. **Reflect.** Invoke `varde-knowledge reflect` as a session boundary (child
   builds already recorded their own lessons); it writes a feature-level
   handoff when anything is left for later.
