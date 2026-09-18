# Review formats

## Review folder layout

Each review uses one dated folder:

```text
memory-bank/working/reviews/
  <YYYY-MM-DD>-<branch>-<target>/
    review.md
    index.md
    CORRECTNESS.md
    CODE.md
    ARCHITECTURE.md
```

Only active review categories need files. The reviewer writes separate
files, so category work does not contend for one shared document.

### Folder name

Use the review start date, branch, and target. Replace path separators and
spaces with hyphens. Keep the target short and recognizable.

### review.md

Create `review.md` before category reviews begin. It carries the review concept's YAML frontmatter:

```yaml
---
title: Review of feature/auth
type: review
date: 2026-08-04
branch: feature/auth
target: main
status: in-progress
categories:
  - CORRECTNESS
  - CODE
triage_status: pending
---
```

The body records category progress and finding counts:

```markdown
# Review of feature/auth

## Categories

| Category | Status | Findings |
|---|---|---:|
| CORRECTNESS | complete | 2 |
| CODE | in-progress | 0 |

## Triage

Status: pending
```

The coordinator updates `review.md` as category work completes. Generate the sibling `index.md` as nav-only metadata containing the category order and current counts. It does not carry the review concept frontmatter.

### index.md

The generated `index.md` is for navigation only. List active categories,
their status, and finding counts.

### Category files

Each category file is a `review-category` concept: YAML frontmatter (below)
followed by a heading. Use the category name as the file name in uppercase.
Finding sections follow the `## Finding format` section below.

```markdown
---
title: CORRECTNESS findings
type: review-category
description: CORRECTNESS review findings
resource: memory-bank/working/reviews/<review-folder>
tags:
  - review
  - correctness
timestamp: <ISO 8601>
created_at: <ISO 8601>
edited_at: <ISO 8601>
---

# CORRECTNESS
```

Findings follow the frontmatter as level-two sections — see the
`## Finding format` section below for the field structure. Identifiers are local to their category file. Use the category name and a
one-based sequence number. Do not reuse an identifier after dismissal.

### Review lifecycle

1. Create the review folder and `review.md`.
2. Generate the nav-only `index.md`.
3. Run one review agent per active category.
4. Append findings to each category file.
5. Mark category status in `review.md`.
6. Run the automated fix pass for labeled findings.
7. Run the triage pass for deferred findings.
8. Mark review and triage statuses complete in `review.md`.

The review folder is the long-term, readable record.

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

A finding is a defect confirmed by reading the code, not a speculation. "This
could break" is not a finding; "this breaks when X — here is the code path" is.

- Only a reproduced or code-confirmed defect earns `high` or `critical`. An
  unverified "might" is at most `low`/`info`, or omit it.
- Treat each finding as a claim. Show the check, not just the conclusion:
  "grepped 4 call sites, all unguarded" shows evidence. "Nothing guards this"
  does not.
- A claim over a set ("every writer", "the only path", "the class is closed")
  requires enumerating the set. One example supports only that example — call a
  sample a sample.
- Numbers carry the boundary of their sample: "3 of 7 call sites", not "most
  call sites".
- Calibration: if a review's findings keep dismissing as empty on inspection,
  raise the bar on what earns a finding rather than lowering it. Auditing
  everything is where false findings breed — scope to the change and its
  consumption path.

### Required fields

| Field | Allowed values or shape | Meaning |
|---|---|---|
| Severity | `critical`, `high`, `medium`, `low`, `info` | Impact if unresolved. |
| Label | `auto-fix` or `triage` | Post-review handling path. |
| Disposition | `blank`, `fix`, `dismiss`, `action-item` | Human outcome. |
| Location | File path and optional line or symbol | Affected code. |
| Summary | Markdown paragraph | Concise issue explanation. |
| Solutions | Ordered Markdown list | Concrete remediation options. |

Use `blank` until a human chooses an outcome. An `auto-fix` finding still
records its disposition after the automated pass.

### Optional fields

| Field | Allowed values or shape | Meaning |
|---|---|---|
| Escalated | `spec-conflict — <reason>` or `scope-creep — <reason>` | Set only by a fix pass running under `varde-change build`, when its escalation gate rejects an automatic fix. Place it directly after `Location`. Absent otherwise. |

### Field rules

- Keep severity lowercase and use one allowed value.
- Use repository-relative paths in `Location`.
- Include a line number when the location is stable.
- Describe observed behavior in `Summary`.
- Make each solution independently understandable.
- Do not hide acceptance criteria inside a solution.
- Preserve the identifier when editing its disposition.

### Stable parsing markers

Use the exact bold field names shown above. The triage workflow identifies
finding sections by level-two headings and reads fields until the next
heading. Keep `Summary` and `Solutions` as level-three headings.

### Disposition edits

Update only the `Disposition` value during triage. Keep the original
severity, label, location, summary, and solutions intact. Add a short
decision note below the solutions when useful.

## Category file format

A new review category is defined in its own file, `CATEGORY-<KEBAB-NAME>.md` —
uppercase prefix for discoverability, kebab-case descriptor, e.g.
CATEGORY-API-DESIGN.md. It carries a `# Category: <Name>` heading followed by
the sections below, in that order, written as the built-in categories in
`references/report-categories.md` write them — use any of those ten as the
worked example rather than reconstructing the shape from prose.

`references/report-categories.md`'s "Rules for every category" already covers
evidence bar, the generic read-the-full-body sweep, and the auto-fix principle.
A new category states only what those rules don't.

### Section rules

Each section opens with its name in bold followed by a colon — `**Look for:**`,
not `**Look for.**`. The colon reads as "here is what this label covers"; a
period starts a sentence the gloss then interrupts. Imperative step labels
elsewhere in these skills are complete sentences and keep their period.

| Section | Contents |
|---|---|
| When relevant | 2–5 sentences: which file types, layers, or change shapes trigger this category, and when it can be safely skipped |
| Look for | One short paragraph naming the checks, not explaining them. Name the concept and trust the reader to know it ("N+1 calls", "unbounded memory growth"). Spend the words instead on the check particular to this category that a reader would not think of unprompted. |
| Severity calibration | What pushes a finding up or down in severity *for this category*; do not restate the generic scale |
| How to check | The one check particular to this category, beyond the generic sweep |
| Auto-fix | Optional. Only this category's exceptions to the general principle |
