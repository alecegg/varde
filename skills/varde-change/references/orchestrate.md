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

Run in the current checkout. Use a feature worktree only when the user asks
and group/child plan storage is tracked; external plan storage stays in the
current checkout. Load `references/worktree.md`, use id
`orchestrate-<group-id>`, and validate any reused path/branch before entering it.
For tracked storage, map group, child and task paths to their physical copies
in the feature checkout. That checkout is the owning approval repository for
the group and serial child builds: initialize/review its own exact-root subjects
there, retain child gates, and do not copy main-checkout approvals. Pass explicit
physical plan paths and the resolved memory locations, without re-resolving
memory storage. Serial children finish their local gates and tracked state in
that checkout, so completed dependencies unlock later children. Nested task
isolation that returns `created=false` stays in this owning checkout.

Run `varde-workflow readiness` on each child (blockers = unmet deps);
`depends_on` holds sibling slugs only. Completed dependencies are satisfied;
skip completed children. A missing dependency blocks its child; a cycle stops
the feature. Report blockers before any child runs.

## Approve and activate the group

Read the group and every child contract. Confirm the group's aggregate source
scope, child IDs/dependencies/contracts, assumptions, and acceptance/verification
outside Progress match them. Material drift updates that contract and obtains
fresh independent approval before any child runs.

Initialize the group's own subject with `varde-workflow review init --plan
<group-plan.md> --repository <owning-approval-repoRoot> --scope <path> [--scope <path> ...]
--json`, covering the aggregate source scope. Reuse an existing subject on
resume; never reset its baseline. Apply `references/review-gates.md` and obtain
independent pre-edit approval of the combined contract. Keep each child's own
subject and gates; group approval does not replace them.

Run the group's `review check --checkpoint start` before transitioning a
backlog or blocked group to active. An active group uses
`review check --checkpoint resume` without an active-to-active transition.
Use `--subject <group-subject-id> --json` for both checks. A blocker stops before
child execution. Commit the activation when plan storage is tracked.

## Delegate children

Run the remaining children sequentially in dependency order — build plan
`<compound-child-id>` (`varde-change build`, named-plan route) — in the
feature location, waiting for each result. Give each child the resolved absolute
`<working>` and `<knowledge>` paths; it uses them without re-resolving. Build owns single-plan execution and review in that owning checkout, and skips
its own merge inside a feature worktree.

When a child blocks or fails, stop immediately: run no later child, merge
nothing, leave commits and partial state as they are, and report the failed
child, the reason, and the completed children.

## Resume

Recover any existing feature location, derive progress from child statuses,
and resume at the first non-`completed` child. `worktree-create.sh` exit 3 on
resume → inspect `git worktree list --porcelain` and reuse
`.varde/worktrees/orchestrate-<group-id>` only when that path is registered
with branch `worktree/orchestrate-<group-id>`. A branch-only collision or a
missing or mismatched worktree stops recovery; do not treat an arbitrary
directory as the execution location. Stop when statuses and commits disagree,
such as a completed child without commits.

## Finish

If children returned escalated findings, present one combined triage table
for all of them (fix.md's human-triage format) and apply the answers as
build-plan-finish step 3 does.

A live nested task binding must be integrated and released at its owning
approval checkout before group completion. The enclosing feature checkout
itself owns the group subject: its group may conclude against verified local
source, then the feature owner offers Merge/Push/Keep for that checkout.
Do not conclude a main-checkout subject against unmerged feature source.

After all children are completed, verify the aggregate acceptance criteria
and combined behavior. Finish findings, source/spec/documentation edits, and
checks before an independent entire-group implementation review. The reviewer
uses the group subject, aggregate contract, child results and execution
location, and records current entire-subject evidence directly per
`references/review-gates.md`. Any subsequent covered fix requires affected
checks and fresh final evidence.

Run `varde-workflow review check --subject <group-subject-id> --checkpoint
complete --json`, then `varde-workflow conclude <group-plan.md> --json`.
Missing/stale approval or an incomplete child blocks conclusion. Preserve the
active group and recovery refs while blocked; never mark it completed by a
plain transition or activate it again at finish.

Commit tracked group conclusion and bookkeeping changes at the owning checkout
before offering Merge or Push; the conclusion journal commits file transactions,
not Git commits. Stage only this group's verified paths and preserve unrelated edits.

Show the aggregate diff and current branch/worktree state. Offer one set of
applicable **Merge**, **Push and open PR**, or **Keep as is** choices for the
group, following `references/build-plan-finish.md`'s choice rules. Recommend
Merge for a worktree this run created and Keep as is in the user's checkout;
hide Merge when no separate branch/worktree exists and hide Push and open PR
when `gh` is unavailable. Only execute the choice the user makes.

Finally invoke `varde-knowledge reflect` as a session boundary; child builds
already recorded their own lessons. It writes a feature-level handoff when
anything is left for later.
