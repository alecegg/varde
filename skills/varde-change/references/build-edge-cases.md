# Decomposition edge cases

Narrow branches that do not apply to most work. Read a section only when its
trigger fired in `references/build-decomposition.md`.

## Wide refactors

The one exception to vertical slicing is a mechanical change such as renaming a
shared type. It may affect so many call sites that no single slice can pass.
Find the symbol's full impact before assuming a small scope. Use this branch
only when the result spans many *independent* packages or directories, not a
handful of related call sites.

Decompose as **expand → migrate → contract**: one expand task adds the new form
alongside the old so nothing breaks; N migrate tasks batched by blast radius (per
package or directory, using search results as batch boundaries) each depend on
expand, so CI stays green batch to batch while the old form still exists; one
contract task deletes the old form, depending on every batch. If batches cannot
stay green alone, chain them through a shared integrate-and-verify task they all
depend into — green is promised only there.

## Porting a native scan rule to TOML or SQL

Run a data-availability check *before* decomposition. Native rules can read
`entity.data` fields nothing in the current schema populates, and a task scoped
as "just port this rule to SQL" hits the gap only when the executor reads the
native source mid-task, forcing a mid-run stop.

List every `entity.data.<field>` each rule accesses. Check each field against the
persisted schema by reading the db or schema module directly — never by assuming
it matches a sibling rule's data shape. Any field not actually persisted becomes
its own upfront indexer task, a `depends_on` edge rather than an "adjust if
needed" note inside the porting task.

## Deletion tasks

Track downstream *textual* consumers, not just structural ones: dependency edges
based on shared source files miss a task whose notes merely read the file, or a
string-literal path a structural query cannot see. Run all three checks — none
subsumes the others:

- Grep every other draft task's body for the file's path; add `depends_on` per
  match.
- Grep test files for hardcoded paths under any directory the task deletes — a
  fixture, a snapshot, a `readFileSync` call; note those files as touched.
- For source paths, search for dependents and importers under the deletion
  target, catching non-textual consumers like a test importing a barrel file that
  re-exports the deleted module. Add `depends_on` edges and note those files too.
