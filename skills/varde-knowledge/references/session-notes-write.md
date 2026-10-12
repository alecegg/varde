# Write session notes

Build session notes as you go, not at the end:

- When a rule is set or a decision opens or closes, Edit the hand-written
  section at once.
- The nudge, pre-compaction refresh, or a request is a tidy pass (dedupe, drop
  resolved), not a rewrite.
- If no session notes file exists, create it from Steps 1-4 first.
- Re-read the file immediately before writing.
- Notes work without `varde:plan-status`; leave it to `varde plan watch` when present.
- A `status: draft` stub made by watch becomes `status: open` on the first
  hand-written write.

## Steps

1. **Capture the session and git anchor.** Record `cwd` from `pwd`. Inside Git,
   also record `repo_root`, `branch`, `head_sha`, and dirty porcelain paths (or
   `[]`); outside Git use exactly `repo_root: none`, `branch: none`,
   `head_sha: none`, and `dirty: not-applicable`.
2. **Redact, then fill the template.** Strip API keys, tokens, passwords,
   connection strings, and personally identifying information, and tailor
   **What's left** and **Suggested next skill** to any focus the user named.
3. **Choose links.** Links identify what is needed to resume without
   rediscovery, as `{target, kind, integrity}`:

   | `kind` | Target |
   |---|---|
   | `file` | A file path |
   | `plan` | The plan that owns the work; its own log holds the fuller history |
   | `review` | A review folder or findings file |
   | `knowledge` | A note harvested from this work; reference it, never restate it |

   Use `integrity: none` by default; add `content_hashes` (per
   `references/session-notes-snapshot.md`) with `integrity: snapshot` when the user
   requests drift detection or the notes are long-lived or high risk. Prefer
   explicit relevant file links inside and outside the repository; for a large
   target, link the relevant files and never imply full-directory coverage.
   Resolve each target independently of the notes' location, store absolute
   paths, and drop and report any missing one before running the snapshot
   script.
4. **Save it** to `<working>/session-notes/<id>/notes.md`. Use a UTC date and
   kebab-case slug for `<id>`, then report the session-notes ID and path:
   - `type: session-notes`, `status: open`;
   - `description`: one line identifying what the session resumes;
   - `timestamp`: ISO-8601 UTC;
   - `cwd` and `keywords` (short comma-separated list);
   - `repo_root`, `branch`, `head_sha`, and `dirty` from step 1;
   - `links`: links from step 3.

## Template

```markdown
# Session notes: <one-line description of the work>

## Rules

<standing instructions set this session, one line each>

## Decisions

<pending: the question and your recommendation; resolved: chose X over Y because Z. Link the plan, commit, or review for detail>

## What's left

<next concrete steps not derivable from `varde plan status`, in order>

## Suggested next skill

<the exact next invocation, e.g. "`varde-change`, resuming plan <plan-id>">
```

The body does not restate frontmatter or derivable state (plans, tasks,
branches, reviews, friction); give the lookup command instead.
