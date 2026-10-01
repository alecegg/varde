# Write a handoff

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
   `references/handoff-snapshot.md`) with `integrity: snapshot` when the user
   requests drift detection or the handoff is long-lived or high risk. Prefer
   explicit relevant file links inside and outside the repository; for a large
   target, link the relevant files and never imply full-directory coverage.
   Resolve each target independently of the handoff's location, store absolute
   paths, and drop and report any missing one.
4. **Save it** to `<working>/handoffs/<YYYY-MM-DD>-<slug>/handoff.md` (UTC
   date, kebab-case slug) with this frontmatter, then report the handoff ID
   (the folder name) and path:
   - `type: handoff`, `status: open`;
   - `description`: one line identifying what the handoff resumes;
   - `timestamp`: ISO-8601 UTC;
   - `cwd` and `keywords` (short comma-separated list);
   - `repo_root`, `branch`, `head_sha`, and `dirty` from step 1;
   - `links`: links from step 3.

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
