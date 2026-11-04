---
topic: varde-orchestrate/finish-steps
version: 1
summary: Ordered steps for the plan implementation review and finding resolution
---

## Implementation review

1. Record `base`, the commit from which the plan branch started.
2. If plan HEAD has not already passed a task gate, run `varde plan gate <last-task.md> --commit HEAD` for the last integrated task. The gate takes a task file, not a combined wave commit. Serial plans check the net diff against plan `scope`; parallel waves check each task's `owns`.
3. Dispatch `varde-reviewer` over `<base>..HEAD` in architecture mode (in pipeline mode this review is the queued `<plan>-plan-review` item; do not dispatch a second). This is the only agent review: it covers code, architecture, and conformance to the plan and tasks. Include the plan, tasks, gate summary, and resolved paths; it writes `<plan-dir>/review.md` in the required format, with conformance in a `## Conformance` section.
4. For skill or agent-document changes, have the reviewer also run the `varde-skill-authoring` review route (`varde-doc-authoring` for a doc).

## Resolve findings

Load `varde-review` (skill tool or `../../varde-review/SKILL.md`) and apply its fix workflow. The user decides grouped intended-behaviour changes.
