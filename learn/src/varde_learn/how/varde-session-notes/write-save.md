---
topic: varde-session-notes/write-save
version: 1
summary: Write notes, part 3 of 3 (step 4), last - save, template; redact secrets first
---

# Write session notes: save and template

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

<the exact next invocation, e.g. "`varde-orchestrate`, resuming plan <plan-id>">
```
