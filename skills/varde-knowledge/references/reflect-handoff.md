# Handoffs

Carries this session's context to the next. To resume, skip to
**Resume a handoff**.

**Links** are the paths needed to resume without rediscovery, as
`{target, kind, content_hashes}`:

| `kind` | Target |
|---|---|
| `file` | A file path |
| `plan` | The plan that owns the work; its own log holds the fuller history |
| `review` | A review folder or findings file |
| `knowledge` | A note harvested from this work; reference it, never restate it |

## Write a handoff

1. **Capture the session and git anchor.** Record `cwd` from `pwd` as the
   actual session working directory; do not replace it with the repository
   root. When `git rev-parse --show-toplevel` succeeds, record that value as
   `repo_root`, the branch (`git rev-parse --abbrev-ref HEAD`), `head_sha`
   (`git rev-parse HEAD`), and dirty paths (`git status --porcelain`, or `[]`)
   plus the worktree path if any. Outside a Git repository, use the exact
   values `repo_root: none`, `branch: none`, `head_sha: none`, and
   `dirty: not-applicable`; retain the actual `cwd`.
2. **Redact, then fill the template.** Strip API keys, tokens, passwords,
   connection strings, and personally identifying information before
   writing. If the user named a focus for the next session, tailor **What's
   left** and **Suggested next skill** to it.
3. **Save it.** Prefer explicit relevant file links inside and outside the
   repository. Reserve complete directory snapshots for small owned artifact
   folders, such as one review folder. For a large target, select and link the
   relevant files instead; never omit files while claiming full-directory
   coverage. Resolve each target independently of the handoff's location;
   store absolute target paths. Confirm each exists; drop and report a missing
   one. Write to `<working>/handoffs/<YYYY-MM-DD>-<slug>/handoff.md` (UTC date,
   kebab-case slug) with this frontmatter:
   - `type: handoff`, `status: open`
   - `description`: one line identifying what the handoff resumes
   - `timestamp`: ISO-8601 UTC
   - `cwd` and `keywords` (short comma-separated list)
   - `repo_root`, `branch`, `head_sha`, and `dirty` from step 1
   - `links`: `[{target, kind, content_hashes}]`; store a snapshot of each
     target's current files, including staged and unstaged edits. Each entry
     in `content_hashes` is `{path, hash}`. For a file target, use `path: .`;
     for a directory target (such as a review folder), recursively list every
     file with its path relative to the target, sorted by path. Use a stable
     content hash for each current file. Determine Git membership from the
     target's own location, not the handoff or session directory:
     `git hash-object --no-filters -- <path>` in that worktree reads current
     contents; for external targets, hash raw file bytes with SHA-256. Preserve the algorithm in each value as
     `git-blob:<object-id>` or `sha256:<64 lowercase hex characters>`. On resume,
     compare the full path-to-hash list so added, removed, renamed, or edited
     files are detected.

   Report the handoff ID (its folder name, `<YYYY-MM-DD>-<slug>`) and path.

## Template

```markdown
# Handoff: <one-line description of the work>

## What's done

<concrete, verifiable state, not narrative>

## What's left

<next concrete steps, follow-up refinements, or deferred items, in order if order matters>

## Key decisions this session

<one line per call: chose X over Y because Z (else the next session re-litigates it); link the plan, commit, or review for detail>

## Open questions / blockers

<anything unresolved, or "none">

## Suggested next skill

<the exact next invocation, e.g. "varde-change build, resuming the <plan-id> plan">
```

The body does not restate frontmatter.

## Resume a handoff

1. List `status: open` handoffs under `<working>/handoffs/*/handoff.md`,
   reading frontmatter only, newest first, preferring a matching `cwd`, then
   `branch`, then `keywords`. If none, say so and stop.
2. With one candidate, resume it. With more than one, ask which to resume as
   an inline numbered menu with a recommendation.
3. Read it. For `repo_root: none`, compare the current `pwd` with its recorded
   `cwd` and report a mismatch as modified handoff context. Resolve each link
   target independently of the handoff's location; legacy relative targets
   resolve against recorded `cwd`. Label each link `modified`, `missing`,
   `unchanged`, or `unknown`; labels never block. Missing target → `missing`.
   With `content_hashes`, recompute the complete path-to-hash list using each
   snapshot's recorded algorithm (`git-blob` or raw-byte `sha256`), regardless
   of where the handoff is stored. Changed list → `modified`; identical list
   → `unchanged`. This detects committed, staged, unstaged, untracked, and
   ignored edits for the selected file or complete directory target.
   For legacy links without snapshots, find the target's Git root independently.
   If it matches recorded `repo_root`, the target is a tracked file, and `head_sha`
   resolves to a commit there, run from that root:
   `git diff <head_sha> -- <repo-relative-target>`.
   This includes committed, staged, and unstaged changes relative to the
   recorded commit; a nonempty diff → `modified`, an empty successful diff →
   `unchanged`. A missing/unresolvable baseline, another repository, an
   external target, legacy directory target, or failed comparison → `unknown`; timestamps alone cannot
   establish unchanged bytes. Re-read relevant unknown targets. A modified
   plan link means read that plan's log; a modified knowledge link means
   reconcile that note.
4. Summarize the context and flags, propose next steps, and wait for
   confirmation before acting. If the handoff is too thin, say what is missing.
5. Set `status: resumed`.
