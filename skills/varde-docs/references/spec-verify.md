# Check and report

## Verification

After generation, read each generated spec document next to the source files
it describes and check these conditions manually:

- All generated files are under `memory-bank/knowledge/specs/`.
- No leftover scratch/staging files exist from a prior run.
- No standalone rule document exists.
- Every generated section can be traced back to real source it describes
  (spot-check operations, types, and invariants against the actual code).
- Every `sources` entry hash equals the current `git hash-object` result.
  Recompute the sorted aggregate and require it to equal `source_hash`. A
  mismatch means source changed during generation. Regenerate that dirty
  document before completing the run.
- Architecture has no flow sections.
- Links between domain documents and to source files resolve.
- Every domain document has exactly one `## Summary` inside its paired
  `<!-- varde-spec:generated:start -->` and
  `<!-- varde-spec:generated:end -->` sentinels. Report missing, duplicated,
  reversed, or unpaired sentinels as generated-boundary drift.
- Every `[[domain:<domain>]]` typed link resolves to another generated domain
  document. Report the document, link target, and broken target when it does
  not resolve.
- Every `### Crux` satisfies `references/spec-format.md`'s crux contract:
  inside a `## Flow:` section, citing a path from `sources`, quoting a literal
  byte-for-byte substring of that file with whitespace intact. A crux placed
  outside a Flow is generated-boundary drift.
- A missing or mismatched crux is drift, not a verification failure. Report its
  domain document, flow name, cited source path, and crux text, then carry on
  through the remaining documents — `varde-docs spec` exits `0` when crux drift
  is its only finding.
- Where you cannot fully confirm accuracy (large or unfamiliar domain), note
  the check as degraded and explain what could not be verified.

## Output

Report this summary:

```text
| Domain | Written | Failed | Skipped |
| --- | ---: | ---: | ---: |
| <domain> | N | N | N |
```

Also report:

- Deleted orphan domains and ambiguous domains retained.
- Broken links and write failures.
- Drift findings by domain and section (places where the document no longer
  matches the code).
- Meaning-layer drift by domain document and flow: crux mismatches, broken
  typed links, summary uniqueness, and generated-boundary findings.
- Notes on any checks that were degraded and what could not be verified.
