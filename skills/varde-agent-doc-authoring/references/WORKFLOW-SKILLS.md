# Workflow skill layout

Use this reference for multi-step, ordered work.

## Entry point dispatch

Add an entry-point table when a skill has multiple invocation shapes. Each
action cell must name the actual discovery method, operation, or reference.
Do not describe only an outcome. An eager agent may act from the table before
reading the workflow.

## Workflow

Use one numbered, imperative workflow. Each step should state one action and
point to the reference that owns its detail. Keep a short gate inline only when
the agent must evaluate it before deciding whether to read the reference.

Keep a short ordered sub-checklist inline when it has three to five simple
items. Move it to the step reference when it grows branches or its own
procedure. Keep literal templates inline or in `assets/`.

Put a short `## Gotchas` section at the end of `SKILL.md`. It records concrete
corrections that must be visible whenever the skill fires.

## Reference fan-out

Navigation, not raw word count, often loses the agent. Measure how many files a
single phase requires.

- One workflow step should usually map to one self-contained reference.
- Merge files always read together during a phase.
- Split a reference only when its branches have separate triggers.
- Avoid a chain where one step needs several peers that cross-reference each
  other.
- Do not cut dense, load-bearing directives merely to hit a percentage target.

When a workflow is short and has little branching, keep it together. A split
must improve routing, not merely reduce the root line count.
