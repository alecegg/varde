# Review agent documents

Report findings before edits unless the user asked for changes. Apply this list
to `SKILL.md`, agent guidance, and references.

## When it applies

- Is the description concrete, user-worded, and specific about when it applies?
- Is model invocation worth its permanent description cost?
- Is the scope one coherent task?
- Does every allowed tool appear in the body, and vice versa?

## Loading and references

- Does the root contain only always-needed instructions?
- Does every conditional reference have an explicit load condition?
- Are files read together consolidated into one phase reference?
- Do all local paths resolve inside the skill?
- Does the document repeat the same rule across body, gotchas, and references?
- Is an environment fact a stale-prone cache rather than a needed convention?

## Instruction quality

- Would the agent likely fail without each instruction?
- Are generic rules replaced by a project procedure or removed?
- Is there a clear default where several methods could work?
- Are hard rules reserved for fragile or destructive operations?
- Is the desired action stated positively where possible?
- Are concrete gotchas inline and easy to find?
- Do repeated outputs have a template or validator?

## Workflow checks

For ordered work, read `WORKFLOW-SKILLS.md`. Verify the dispatch table names
the actual discovery mechanism and the workflow contains one imperative action
per step.

## Final checks

- Run `uv run scripts/validate-frontmatter.py <skill-dir>` after frontmatter edits.
- Check changed pointers and renamed files repository-wide.
- Check authored files for stray literal `</content>` lines.
- Add structured evals only after the workflow has stabilized.
