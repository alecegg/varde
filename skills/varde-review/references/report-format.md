# Review formats

## Review folder layout

| Case | Path |
|---|---|
| Standalone (no plan id passed) | `<working>/reviews/<YYYY-MM-DD>-<slug>/` |
| Nested (review runs for a plan build, a plan id was passed) | `<plan-dir>/review.md` (one per plan; a re-check rewrites its header and appends `## Re-check`) |

A review is one `review.md`: the report header, a `## Categories` checklist
table (Category | Status [`complete` or `skipped`] | Findings), then the
findings. There are no per-category files.
Identifiers are category-local, `<CATEGORY>-<NNN>` from 001, never reused after
dismissal. The standing `deferred/` review keeps one `<CATEGORY>.md` per
category.

## Report header

```markdown
---
type: review
verdict: approved | changes-requested
reviewer: <agent role and session id>
base: <full sha of the fixed commit>
head: <full sha of the reviewed HEAD>
---
```

`varde plan conclude` exits 0 only when the merged commit equals `head` and the
verdict is `approved`. A fixes-only re-check rewrites the header and appends a
`## Re-check` section.

## Finding format

Each issue is a level-two markdown section in `review.md`. The
heading contains a category-local identifier and a short title.

```markdown
## [CORRECTNESS-001] Missing validation

**Severity:** high
**Status:** open
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

A finding is a defect confirmed by reading the code, not speculation ("this
could break"): state when it breaks and show the code path.

Imported PR feedback and scan candidates are pending triage; identify their
source and keep the reported concern distinct from a verified code defect.

- Only a reproduced or code-confirmed defect earns `high` or `critical`. An
  unverified "might" is at most `low`/`info`, or omit it.
- Show the check and its sample boundary, not only the conclusion: "Grepped
  4 of 7 call sites, all unguarded", not "Nothing guards this" or "most call
  sites".
- A claim over a set ("every writer", "the only path", "the class is closed")
  requires enumerating the set; one example supports only that example.

### Required fields

| Field | Allowed values |
|---|---|
| Severity | `critical`, `high`, `medium`, `low`, `info` |
| Status | `open`, `fixed`, `deferred`, `asked` |

A new finding starts `open`.

### Optional fields

| Field | Allowed values or shape | Meaning |
|---|---|---|
| Violates | `[<title>](/specs/<x>.md)` or a `/decision/`, `/pattern/` link | The knowledge note this finding breaks. Only when one exists; its rationale guides the fix. |

### Field rules

- Keep exact bold field names, lowercase severity, and `### Summary`/`### Solutions`;
  fix mode reads them literally.
- Use repository-relative `Location` with a stable line. CI without a local
  file may use its check URL; visual findings without known source may use a
  review-relative screenshot path. `Summary` states observed behavior; each
  solution stands alone without hiding acceptance criteria.
- Fix mode changes only `Status` (optionally adding a decision note below
  Solutions); a visual fix may append before/after evidence. Other fields stay
  intact.
- A finding appended to the standing `deferred/` review keeps
  `Status: deferred`.
