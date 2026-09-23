# Companion plan

Create one plan per category for action items from one review. Create the plan
when the category gets its first action item. For a standalone review, name
each plan:

```text
  <working>/plans/<YYYY-MM-DD>-review-fixes-<target>-<category-lowercase>/plan.md
```

For a review nested inside a plan bundle, create:

```text
  <working>/plans/<plan-id>/<fix-id>/plan.md
```

Set `type: review-fix` and `source_review: <plan-id>/<review-id>` in the
plan's frontmatter. Keep its tasks and later child concepts inside the same
parent bundle. For a standalone review, keep the plan at the top-level path
above. Add each later action item from that category as another task in the
same plan. Pre-fill each task's acceptance criteria with the finding title,
location, summary, and selected solution. Link the task from the finding block.

## Next steps for companion plans

After completion or archiving, tell the user what to do with each companion
plan. Nested companion plans are children of the originating plan. They must
reach `completed` or `archived` before that parent plan can complete.

Review-fix tasks already have a chosen solution, concrete acceptance criteria,
and scope boundaries from triage. They do not need a planning session. Invoke
`varde-change build` directly for each companion plan.

Recommend `varde-change plan` first only when a task is underspecified. This
means its acceptance criteria are vague, its solution is marked "discuss
further", or it depends on a design decision that was explicitly deferred.
Otherwise, build it directly.

Name each companion plan and its tasks in the closing output. Give the user a
clear list of what to run next.
