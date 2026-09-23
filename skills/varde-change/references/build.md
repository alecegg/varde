# Build mode

Choose one branch. Open only its reference.

| The request is | Read |
|---|---|
| A named bug or regression has no explicit mode | `references/debugging-entry.md` |
| An explicit diagnosis-only request names a bug or regression | `references/debugging-entry.md` |
| A clear, bounded micro-change | `references/build-micro-change.md` |
| A named existing plan | `references/build-existing-plan.md` |
| Any plan, uncertain change, refactor, or spike | `references/build-plan.md` |

A micro-change names one concrete behavior or target.
It needs no planning, decomposition, or review cycle.
Unclear scope belongs to the plan branch.
Plan branches resolve `execution=<auto|inline|fresh|parallel>` before tasks begin.
Plan branches announce the selected execution strategy and task count.
The strategy selector accepts `auto`, `inline`, `fresh`, or `parallel`.

`parallel` requires a task manifest. The manifest proves dependency readiness,
owned paths, renames, and verification resources. `auto` selects `parallel`
only when the first ready wave is complete and conflict-free. Otherwise it
keeps the existing sequential choice.

Automatic debugging routing applies only when no explicit exploration,
diagnosis-only, or build mode is present. See
`references/debugging-entry.md` for the evidence gate before fixes.

Testing profile selection follows direct user instructions, repository policy,
then decomposition. Use `scripts/resolve-testing-profile.sh` to make that
precedence deterministic before recording task metadata.
