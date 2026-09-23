# Discover feature groups

Load this only for whole-feature requests without a named group.

List directories beneath `<working>/plans/`.
Keep plans whose frontmatter contains `shape: group`.
Discover their children through nested child directories:

```text
<working>/plans/<group-id>/<child-slug>/plan.md
```

Keep groups containing at least one non-`completed` child.
Present each as `<group-id> — <title>`.
Use the group's `goal` as its description.
Present them, then stop until the user selects one.
Do not delegate children, edit plans, or edit source.

If nothing qualifies, report:

```text
No group plans with unbuilt children. Nothing to orchestrate.
```

After selection, load `references/orchestration-run.md`.
