## Operations

The knowledge bundle root is `memory-bank/knowledge/`; a note's slug is its
type-first path minus the `.md` suffix (e.g. `pattern/code-review`). Every
by-hand operation in this skill has a CLI equivalent — use it when
`varde-docs` is present, otherwise use the plain-file flow described in the
skill body.

```bash
BUNDLE=memory-bank/knowledge

# Find candidate notes — ranked full-text over bodies + frontmatter, instead
# of a manual grep sweep. --field narrows by frontmatter first when useful.
varde-docs concept search --bundle "$BUNDLE" --text "<query>" --limit 10 --json
varde-docs concept search --bundle "$BUNDLE" --field type=decision --text "<query>" --json

# Read one note (frontmatter + body + the version hash needed to write it).
varde-docs concept show --bundle "$BUNDLE" <type>/<slug> --json

# Create a new note. Write the full markdown (frontmatter + body) to a temp
# file first — the same content the skill body specifies (type, description,
# generated, etc.).
varde-docs concept create --bundle "$BUNDLE" <type>/<slug> --file "${TMPDIR:-/tmp}/note.md"

# Edit an existing note conflict-safely: show → read its "version" from the
# JSON → edit → update with that hash. On exit 3, re-show and reconcile before
# retrying (see the OCC contract).
varde-docs concept show --bundle "$BUNDLE" <type>/<slug> --json   # note the "version" value
varde-docs concept update --bundle "$BUNDLE" <type>/<slug> --expected-version <version> --file "${TMPDIR:-/tmp}/note.md"

# Retire a note — prefer the status field over deletion (OKF §5.4).
varde-docs concept set-field --bundle "$BUNDLE" <type>/<slug> status deprecated --expected-version "$HASH"

# Health check: structural by default, --okf adds OKF v0.2 spec checks.
varde-docs lint --bundle "$BUNDLE" --json
varde-docs lint --bundle "$BUNDLE" --okf --json
```

Notes:

- **This does not change the note conventions** in the skill body — type-first
  paths, required `type`/`description`/`generated` frontmatter, markdown
  (not wiki-) links, reserved `index.md`/`log.md`. The CLI is a safer
  read/write path for the same files, not a different format.
- `search --text` replaces the `grep -ril` sweep with ranked results; still
  `show` (or Read) the full note before acting on it.
- Prefer `update`/`set-field` over Edit when the binary is present: the OCC
  hash prevents clobbering a concurrent edit (e.g. a user editing the same
  note). Fall back to Edit on any failure.
