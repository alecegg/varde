---
name: varde-handoff
description: >
  TRIGGER: Compact the current conversation into a handoff document so another
  agent or a later session can resume with full context.
  SKIP: Skip only when no session context needs preserving and the user wants
  implementation, review, or planning work now.
  Example phrases: "write a handoff" or "save context before compacting".
---

## Instructions

Summarize the current conversation into a handoff document a fresh agent session can read cold and continue from. Do not re-derive or re-litigate what's already settled — the whole point is that the next session doesn't have to.

A handoff carries context forward across a **session boundary** — it is not only for unfinished work. A long run that *completed* its goal still leaves decisions, pointers, and a git anchor worth carrying, so the next session can start cheaply from a compact doc instead of reloading the whole transcript. `varde-reflect` is the usual caller (it writes the handoff at a boundary after harvesting friction and knowledge), but this skill is equally valid invoked directly.

## Entry point dispatch

There is one kind of handoff: a standalone doc under `memory-bank/working/handoffs/`. It has two modes — **create** (the default) and **resume**.

| Argument | Mode |
| --- | --- |
| `mode=resume` | resume — pick up an open Handoff (see Resume mode below) |
| *(none, or a focus description)* | create — write a new handoff |

Don't special-case work that belongs to a plan. Plans keep their own logs (`run-state.md`), so the handoff only needs a **pointer** back — record the plan as a `kind: plan` link (step 2) and let the next session follow it. The handoff never writes into a plan's files.

With `mode=resume`, skip the write workflow below and follow the Resume mode flow instead — the write path never runs.

## Workflow

1. **Capture the git anchor.** This is what lets a later session resume cold and is the basis for staleness checks. Run `git rev-parse --abbrev-ref HEAD` (branch), `git rev-parse HEAD` (`head_sha`), and `git status --porcelain` (uncommitted/untracked paths). Record all three. If the session ran inside a worktree, also note its path. If the directory is not a git repo, record `head_sha: none` and skip the git-backed staleness path on resume.
2. **Gather what belongs in the doc.** Read back through the conversation and collect, without re-deriving:
   - What was accomplished this session and what remains.
   - Key decisions made and *why* — including **rejected alternatives**, which are load-bearing: the next session needs to know what was already ruled out and why, or it re-litigates settled ground.
   - The current state of the work (committed, uncommitted, failing, unverified).
   - Open questions or blockers the next session needs to resolve.
   - The **Links** — only the plan, review, knowledge note, or file needed to
     resume without rediscovery. Record each as `{target, kind}`, where `kind`
     is `file`, `plan`, `review`, or `knowledge`. If a plan owns the work, its
     `kind: plan` link is the pointer the next session follows back to the
     plan's own log. A `kind: knowledge` link points at a note
     `varde-reflect` harvested from this work — reference it, never restate it.

   **Keep vs. drop.** A handoff carries reusable conclusions, not a transcript. *Keep:* decisions and their rationale, rejected alternatives, blockers, verification results, fragile local state (worktree, uncommitted changes), and the next concrete steps. *Drop:* "the command succeeded", "the file was edited", the user's request restated, generic framework/tooling knowledge, and any transcript play-by-play that carries no reusable conclusion. When in doubt, ask "would the next session waste time rediscovering this?" — if not, drop it.

   Do not duplicate content that already exists in another artifact (a plan body, a review's findings file, a prototype's README, a commit diff) — reference it by Link instead, since a duplicate just goes stale when the original changes.
3. **Redact before writing anything to disk.** Strip API keys, tokens, passwords, connection strings, and any personally identifying information from quoted output or logs. If in doubt, redact.
4. **Write the doc** using the template below. Trim sections that have nothing to report rather than leaving them as empty headers. If the user passed a description of what the next session will focus on (an argument, or stated in chat), tailor **What's left** and **Suggested next skill** to that focus rather than listing everything open.
5. **Save the doc.** Verify every collected Link resolves. Drop a missing link,
   report it, and continue writing the handoff:
   - `kind: file` → confirm the path exists (e.g. via `Read` or `Glob`).
   - `kind: plan` → confirm the plan document exists at the given path.
   - `kind: review` / `kind: knowledge` → confirm the review folder/file or
     knowledge note exists at the given path.

   Then `Write` into `memory-bank/working/handoffs/<handoff-id>/handoff.md`, where `<handoff-id>` follows the `<YYYY-MM-DD>-<slug>` convention (UTC date + kebab-case slug, same as plan IDs). Create the directory if it does not already exist. Prefix the doc with the handoff frontmatter:
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

<the exact next invocation to run, e.g. "/build plan=<plan-id>" or "/plan" to resume a draft — not just the skill name>
```

## Resume mode

`mode=resume` picks up an open Handoff instead of writing a new one: list what's open, let the human pick, then surface the chosen doc with every Link's staleness recomputed and labeled. Unlike write time, resume never blocks on a stale Link — it labels only.

1. **List and rank open Handoffs.** `Glob` `memory-bank/working/handoffs/*/handoff.md`. For each, read **only the frontmatter** (the leading `---` block — do not read bodies yet), and keep those with `status: open`. If nothing comes back, report that there are no open Handoffs and stop. Rank the survivors so the most likely resume floats to the top, using the frontmatter fields: same `cwd` as the current directory first, then matching `branch`, then `keywords` overlapping the user's stated focus, then most recent `timestamp`. Bodies stay unread until the human picks — ranking off frontmatter alone keeps this cheap when many handoffs are open.
2. **Let the human pick.** Present each candidate's `description` in ranked order as an inline numbered menu — don't use a harness's native question-prompt tool, since it renders outside the continuous transcript — one option per Handoff, with a recommendation:

```text
Which Handoff should this session resume?

  1. <description>  (<branch> · <relative age> · <"here" if cwd matches>)
  2. <description>  (...)
  ...
  n. Other — describe what you want

Recommendation: <n> — <one-sentence reason>.
```

3. **Re-resolve every Link against the git anchor.** Read the picked Handoff's body and its `head_sha`. For each entry in the `links` array, derive a real staleness label rather than guessing:
   - If `head_sha` is present and the path is tracked, run `git log <head_sha>..HEAD -- <target>`: no commits touch it → `unchanged`; commits touch it → `modified`. Also confirm the path still exists on disk; gone → `missing` (overrides the log result). This gives a git-backed verdict, not an eyeball comparison.
   - If `head_sha` is `none`/absent (handoff written outside a repo) or the path is untracked, fall back to existence only: present → `unchanged`, absent → `missing`.
   - `kind: plan` / `kind: review` / `kind: knowledge` targets use the same rules — they are paths like any other. A `modified` `kind: plan` link is the cue to read that plan's own log for what changed since; a `modified` `kind: knowledge` link is the cue to reconcile that note against the code it now describes.
4. **Label before surfacing.** Prepend a per-Link label — `unchanged`, `modified`, or `missing` — to each Link entry in what the agent reads, before the Handoff's content is surfaced. Resume never blocks on a stale Link; the labels inform the resuming session, they don't gate the read. Also surface the anchor itself: if the current `HEAD` has moved past `head_sha`, say so, so the session knows it is resuming onto newer code.
5. **Orient, then wait.** After ingesting the Handoff, summarize the recovered context, note which Links are `modified`/`missing`, and propose the next concrete steps — then stop. Do not edit files, run builds, or invoke another workflow until the user confirms the direction. If the Handoff is too thin to orient from, say what's missing rather than inventing a plan.
6. **Transition the Handoff.** Apply a targeted `Edit` to the Handoff's `handoff.md` frontmatter, changing `status: open` to `status: resumed`. Re-read the file immediately before editing to catch any concurrent change, and merge around it if one landed. `open` → `resumed` is the only transition resume makes — it never archives.
