## Operations

Spec documents are concepts in the project knowledge bundle: bundle root
`memory-bank/knowledge/`, one domain per file under `specs/`, so slug
`specs/<domain>`. Use `varde-docs` for the same writes this skill does by
hand; fall back to plain Write/Edit/`git rm` on any failure. Paths are
relative to the effective `repoRoot` (the worktree path from step 1).

```bash
BUNDLE=memory-bank/knowledge

# Step 3 (per-domain agents): write each domain doc. First run of a domain is
# a create; a refresh is an OCC update (show → read "version" → update).
varde-docs concept create --bundle "$BUNDLE" specs/<domain> --file "${TMPDIR:-/tmp}/spec.md"
varde-docs concept show   --bundle "$BUNDLE" specs/<domain> --json   # note "version"
varde-docs concept update --bundle "$BUNDLE" specs/<domain> --expected-version <version> --file "${TMPDIR:-/tmp}/spec.md"

# Existing specs, to scope refresh/orphan checks.
varde-docs concept list --bundle "$BUNDLE" --field type=spec --json

# Step 4 (orphans): delete a domain whose code no longer exists. Exit 2
# (not found) means it's already gone — treat as done, not an error.
varde-docs concept delete --bundle "$BUNDLE" specs/<domain>

# Step 6 (verify): structural checks; --okf adds OKF v0.2 checks. Reports
# broken links / malformed frontmatter without blocking.
varde-docs lint --bundle "$BUNDLE" --json
```

Caveats:

- **`specs/index.md` stays a plain Write.** `index.md` is a reserved bundle
  filename the CLI treats as bookkeeping, not a concept — keep writing it
  deterministically (step 5) with Write, never `concept create`.
- **Within the worktree, OCC is belt-and-suspenders** — each domain agent
  writes a distinct file and the run is already isolated. The reason to use
  the CLI here is uniform create/update/delete/lint and consistency with the
  knowledge bundle, not clobber-protection.
- The spec **format and frontmatter** (`type: spec`, etc.) are unchanged —
  see `references/SPEC-FORMAT.md`; the CLI writes the same files.
