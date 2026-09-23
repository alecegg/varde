# Handoffs

Summarize the current conversation so a new session can continue without
repeating finished work.

A handoff carries context to the next session. Use it after completed work too.
Reflection usually reaches this procedure. A direct handoff request runs it on
its own.

Store handoffs under `<working>/handoffs/`. Writing a new handoff is
the default. When the user instead wants to pick up an open handoff, skip the
write workflow entirely and follow **Resuming a handoff** at the end of this
file.

For work in a plan, add a `kind: plan` link. Plans keep their own logs, and the
handoff points at them.

## Workflow

1. **Capture the git anchor.** Use it to resume later and check staleness. Run `git rev-parse --abbrev-ref HEAD` (branch), `git rev-parse HEAD` (`head_sha`), and `git status --porcelain` (uncommitted/untracked paths). Record all three. If the session ran inside a worktree, also note its path. If the directory is not a git repo, record `head_sha: none` and skip git-backed staleness checks on resume.
2. **Gather the handoff content.** Read the conversation and collect these facts without re-deriving them:
   - What was accomplished this session and what remains.
   - Key decisions made and *why* — including **rejected alternatives**, which are load-bearing: the next session needs to know what was already ruled out and why, or it re-litigates settled ground.
   - The current state of the work (committed, uncommitted, failing, unverified).
   - Open questions or blockers the next session needs to resolve.
   - The **Links** — only the plan, review, knowledge note, or file needed to
     resume without rediscovery. Record each as `{target, kind}`, where `kind`
     is `file`, `plan`, `review`, or `knowledge`. If a plan owns the work, its
     `kind: plan` link is the pointer the next session follows back to the
     plan's own log. A `kind: knowledge` link points at a note
     reflection harvested from this work — reference it, never restate it.

   **Keep vs. drop:** Keep reusable conclusions, not a transcript. Keep decisions
   and their rationale, rejected alternatives, blockers, verification results,
   fragile local state (worktree, uncommitted changes), and the next concrete
   steps. Drop "the command succeeded", "the file was edited", the user's
   request restated, generic framework or tooling knowledge, and transcript
   play-by-play without a reusable conclusion. Keep a detail only if the next
   session would waste time rediscovering it.

   Content that already lives in another artifact — a plan body, a review's findings file, a prototype's README, a commit diff — is referenced by Link, not copied. A copy goes stale the moment the original changes.
3. **Redact before writing anything to disk.** Strip API keys, tokens, passwords, connection strings, and any personally identifying information from quoted output or logs. If in doubt, redact.
4. **Write the doc** using the template below. Remove sections that have
   nothing to report instead of leaving empty headers. If the user gave a focus
   for the next session, tailor **What's left** and **Suggested next skill** to
   that focus instead of listing every open item.
5. **Save the doc.** Verify every collected Link resolves. Drop a missing link,
   report it, and continue writing the handoff:
   - `kind: file` → confirm the path exists (e.g. via `Read` or `Glob`).
   - `kind: plan` → confirm the plan document exists at the given path.
   - `kind: review` / `kind: knowledge` → confirm the review folder/file or
     knowledge note exists at the given path.

   Then `Write` into `<working>/handoffs/<handoff-id>/handoff.md`, where `<handoff-id>` follows the `<YYYY-MM-DD>-<slug>` convention (UTC date + kebab-case slug, same as plan IDs). Create the directory if it does not already exist. Prefix the doc with the handoff frontmatter:
   - `type: handoff`, `status: open`
   - `description` (one line identifying what the handoff resumes)
   - `timestamp` (ISO-8601 UTC creation time)
   - `cwd` (the working directory) and `keywords` (a short comma-separated list drawn from the work) — these let resume-time discovery rank candidates without reading the body.
   - `branch`, `head_sha`, and `dirty` (the uncommitted/untracked paths, or `[]`) from the git anchor in step 1. These anchor the resume and drive staleness.
   - `links` — the resolved Link array, `[{target, kind}]`.

   Report the handoff-id and repo-relative path back to the user so the next session can find the doc.

## Template

```markdown
# Handoff: <one-line description of the work>

**Session ended:** <date>
**Git anchor:** `<branch>` @ `<head_sha>` — <N> uncommitted paths (list them, or "clean tree")

## What's done

<bullet list — concrete, verifiable state, not narrative>

## What's left

<the next concrete steps, in order if order matters — or "nothing; work completed" plus any optional follow-ups. A completed run still warrants a handoff for the context it carries.>

## Key decisions this session

<one line per decision: the call made and why. Include rejected alternatives ("chose X over Y because Z") — they stop the next session re-opening settled questions. Link to the plan/commit/review that holds the detail — don't restate it.>

## Open questions / blockers

<anything unresolved that blocks progress, or "none">

## Pointers

<the collected Links — file paths (`kind: file`), plan paths (`kind: plan`), review folder paths (`kind: review`), knowledge notes (`kind: knowledge`) — the next session's map, not a copy of their contents. A `kind: plan` link points at the plan whose own log holds the fuller history; a `kind: knowledge` link points at a harvested durable note. The same entries are carried machine-readably in the frontmatter `links` array.>

## Suggested next skill

<the exact next invocation to run, e.g. "varde-change build, resuming the <plan-id> plan" — name the skill and the target, not just the skill>
```

## Resuming a handoff

To resume, list open Handoffs instead of writing a new one. Let the human pick
one, then recompute and label every Link's staleness. A stale Link does not block
resume; label it and continue.

1. **List and rank open Handoffs.** `Glob` `<working>/handoffs/*/handoff.md`. For each, read **only the frontmatter** — the leading `---` block — and keep those with `status: open`. If nothing comes back, report that there are no open Handoffs and stop. Rank the survivors so the most likely resume floats to the top, using the frontmatter fields: same `cwd` as the current directory first, then matching `branch`, then `keywords` overlapping the user's stated focus, then most recent `timestamp`. Bodies stay unread until the human picks — ranking off frontmatter alone keeps this cheap when many handoffs are open.
2. **Let the human pick.** Present each candidate's `description` in ranked order as an inline numbered menu in your message text, one option per Handoff, with a recommendation:

```text
Which Handoff should this session resume?

  1. <description>  (<branch> · <relative age> · <"here" if cwd matches>)
  2. <description>  (...)
  ...
  n. Other — describe what you want

Recommendation: <n> — <one-sentence reason>.
```

3. **Re-resolve every Link against the git anchor.** Read the picked Handoff's body and its `head_sha`. For each entry in the `links` array, derive a real staleness label rather than guessing:
   - If `head_sha` is present and the path is tracked, run `git log <head_sha>..HEAD -- <target>`: no commits touch it → `unchanged`; commits touch it → `modified`. Also confirm the path still exists on disk; gone → `missing` (overrides the log result).
   - If `head_sha` is `none`/absent (handoff written outside a repo) or the path is untracked, fall back to existence only: present → `unchanged`, absent → `missing`.
   - `kind: plan` / `kind: review` / `kind: knowledge` targets use the same rules — they are paths like any other. A `modified` `kind: plan` link is the cue to read that plan's own log for what changed since; a `modified` `kind: knowledge` link is the cue to reconcile that note against the code it now describes.
4. **Label before surfacing.** Before showing the Handoff, prepend one label —
   `unchanged`, `modified`, or `missing` — to each Link entry. The labels inform
   the resuming session and never block the read. Also say when the current
   `HEAD` is newer than `head_sha`.
5. **Orient, then wait.** After ingesting the Handoff, summarize the recovered context, note which Links are `modified`/`missing`, and propose the next concrete steps — then stop and wait for the user to confirm the direction before touching files, builds, or another workflow. If the Handoff is too thin to orient from, say what's missing rather than inventing a plan.
6. **Transition the Handoff.** Edit the Handoff's `handoff.md` frontmatter, changing `status: open` to `status: resumed`. That is resume's only transition; archiving belongs elsewhere.
