# Write agent documents

## Use project evidence

Ground project-specific instructions in completed tasks, runbooks, schemas,
incidents, review comments, or code history. Record only corrections the
repository does not make obvious. If a project-specific claim lacks evidence,
ask for a source before making it a rule.

For project workflows, state the default action, explain choices where judgment
matters, and give exact commands only for fragile operations.

**No source, no project context** (e.g. a generic "best practices" skill): say
a draft would only restate model defaults. Instead find what is specific —
ask, one question at a time, about the environment and tools actually used,
failures or near-misses and how they were fixed, team conventions a newcomer
gets wrong, and steps done by hand or often forgotten. Draft only what those
answers make non-default: exact commands, decision rules, gotchas,
verification steps. Offer a completed task or runbook as a faster alternative
to the interview.

## Keep reading focused

Confirm what the target harness loads at startup, on activation, and by
reference. Make the entry file a run sheet; move detailed procedures, tables,
and long templates to references, each with a load condition. Weight detail by
load frequency; state each rule once (`reviewing.md`).

Bundle a script only to replace repeated parsing or validation; name its exact
skill-root-relative invocation where it runs, and pin dependencies inline (PEP
723).

## Scope and content

Avoid skills too small to use alone or too broad to select precisely. Cut
generic background and stale environment facts; reserve prohibitions for hard
boundaries, with the alternative.
