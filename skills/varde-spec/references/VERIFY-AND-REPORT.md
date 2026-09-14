# Verify and report

## Verification

After generation, read each generated spec document next to the source files
it describes and check these conditions manually:

- All generated files are under `memory-bank/knowledge/specs/`.
- No leftover scratch/staging files exist from a prior run.
- No standalone rule document exists.
- Every generated section can be traced back to real source it describes
  (spot-check operations, types, and invariants against the actual code).
- Architecture has no flow sections.
- Links between domain documents and to source files resolve.
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
- Notes on any checks that were degraded and what could not be verified.
