# Review formats

## Review folder layout

Standalone (no plan id passed): `<working>/reviews/<YYYY-MM-DD>-<slug>/`.
Nested (the review runs for a plan build, a plan id was passed):
`<working>/plans/<plan-id>/<review-id>/`, where `<review-id>` =
`review-<YYYY-MM-DD>` (append `-2`, `-3`, ... on a same-day collision in that
plan folder). `<fix-id>` = `<review-id>-fixes`. `review.md` frontmatter:
`type: review`, date, branch, target, `status` (`in_progress` until roll-up,
then `complete`), categories[], triage_status; body `## Categories` table
(Category | Status [`complete` or `skipped`] | Findings). One file per
category, `<CATEGORY>.md`; identifiers are category-local,
`<CATEGORY>-<NNN>` from 001, never reused after dismissal.

## Finding format

Each issue is a level-two markdown section inside a category file. The
heading contains a category-local identifier and a short title.

```markdown
## [CORRECTNESS-001] Missing validation

**Severity:** high
**Label:** triage
**Disposition:** blank
**Location:** `src/auth/token.ts:42`

### Summary

The parser accepts expired tokens.

### Solutions

1. **Reject expired tokens**
   Add the expiration check before returning the decoded token.
2. **Add a regression test**
   Cover expired and valid token inputs.
```

### Finding discipline

A finding is a defect confirmed by reading the code, not speculation. "This
could break" is not a finding. State when it breaks and show the code path.
Imported PR feedback and scan candidates are pending triage; identify their
source and keep the reported concern distinct from a verified code defect.
Their initial severity is a routing priority, not a claim that the defect is
confirmed.

- Only a reproduced or code-confirmed defect earns `high` or `critical`. An
  unverified "might" is at most `low`/`info`, or omit it.
- Treat each finding as a claim. Show the check, not only the conclusion.
  "Grepped 4 call sites, all unguarded" shows evidence. "Nothing guards this"
  does not.
- A claim over a set ("every writer", "the only path", "the class is closed")
  requires enumerating the set. One example supports only that example — call a
  sample a sample.
- Numbers carry the boundary of their sample: "3 of 7 call sites", not "most
  call sites".
### Required fields

| Field | Allowed values |
|---|---|
| Severity | `critical`, `high`, `medium`, `low`, `info` |
| Label | `auto-fix` or `triage` |
| Disposition | `blank`, `fix`, `dismiss`, `action-item`, `escalated` |

Use `blank` until a human chooses an outcome.

### Optional fields

| Field | Allowed values or shape | Meaning |
|---|---|---|
| Violates | `[<title>](/specs/<x>.md)` or a `/decision/`, `/pattern/` link | The knowledge note this finding breaks. Only when one exists; its rationale guides the fix. |
| Escalated | `spec-conflict — <reason>`, `scope-creep — <reason>`, or `human-only — <category>` | Set only by the build-mode escalation gate in `references/fix-pass.md`. Absent otherwise. |

### Field rules

- Keep exact bold field names, lowercase severity, and `###` Summary/Solutions
  headings; fix mode reads them literally.
- `Location` is repository-relative, with a line number when stable; a CI
  finding without a local file may use its check URL, and a visual finding
  without known source may use a screenshot path relative to its review folder.
  `Summary`
  describes observed behavior; each solution stands alone and hides no
  acceptance criteria.
- Triage edits only `Disposition`, optionally adding a decision note below the
  solutions; identifier, severity, label, location, summary, and solutions stay
  intact. A visual fix may append before/after verification evidence below the
  solutions without changing those fields.
- `escalated` marks a source finding copied into the standing deferred review;
  the copy keeps `Disposition: blank` for future triage.
