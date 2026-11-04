# Write session notes

Session notes build up as the session goes, not at the end:

- When a rule is set or a decision opens or closes, the hand-written section is
  edited at once.
- The nudge, pre-compaction refresh, or a request is a tidy pass (dedupe, drop
  resolved), not a rewrite.
- A missing session notes file is created first; the file is re-read
  immediately before writing.
- Notes work without `varde:plan-status`; leave it to `varde plan watch` when present.
- A `status: draft` stub made by watch becomes `status: open` on the first
  hand-written write.

Validation of the saved notes:

- They are at `<working>/session-notes/<id>/notes.md`, with a UTC date and
  kebab-case slug for `<id>`; the session-notes ID and path are reported.
- Frontmatter:
  - `type: session-notes`, `status: open`;
  - `description`: one line identifying what the session resumes;
  - `timestamp`: ISO-8601 UTC;
  - `cwd` (from `pwd`) and `keywords` (short comma-separated list);
  - `repo_root`, `branch`, `head_sha`, `dirty` (porcelain paths or `[]`) inside
    Git. Outside Git, exactly `repo_root: none`, `branch: none`,
    `head_sha: none`, and `dirty: not-applicable`;
  - `links`: `{target, kind, integrity}`. `kind` is one of `file` (a path),
    `plan` (the owning plan), `review` (a review folder or findings file),
    `knowledge` (a note harvested from this work).
- Secrets (API keys, tokens, passwords, connection strings) and personally
  identifying information are stripped.
- Links hold what is needed to resume without rediscovery: absolute
  paths resolved independent of the notes' location. Drop and report missing
  targets before the snapshot script runs.
- Prefer explicit relevant file links inside and outside the repository.
  `knowledge` links reference a note and never restate it. For a large target,
  link the relevant files and never imply full-directory coverage.
- `integrity: none` is the default; `integrity: snapshot` with
  `content_hashes` (per `references/snapshot.md`) only when the user requests
  drift detection or the notes are long-lived or high risk.
- The body has sections Rules, Decisions, What's left, and Suggested next
  skill, tailored to any focus the user named. It does not restate
  frontmatter or derivable state (plans, tasks, branches, reviews, friction);
  it gives the lookup command instead.
