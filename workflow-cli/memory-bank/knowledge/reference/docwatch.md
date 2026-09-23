---
type: reference
title: "docwatch — in-doc agent triggers"
---

# docwatch

`docwatch` lets you trigger agent work by writing directly in a markdown
document — no switching devices, no manually invoking an agent CLI. Write a
trigger line in a note (e.g. from an iPhone editing over SMB/SFTP), and a
background watcher on the Mac detects it, runs a scoped headless agent
against the surrounding repo, and writes the answer or edit back into the
same document.

`docwatch` manages one background watcher per registered folder. Each
watcher runs as a macOS LaunchAgent (via `launchd`), watches every file
under that folder for changes, and on each save scans for unresolved
trigger tags. When it finds one, it dispatches a single scoped agent run
and writes the result back into the triggering document.

v1 supports doc-editing only: the dispatched agent may read anything in the
repository for context, but is restricted to writing the triggering
document.

## Trigger syntax

Write a trigger as its own line, addressed to one of two agent backends:

- `@c: <question or request>` — dispatches Claude.
- `@cx: <question or request>` — dispatches codex.

The line may be indented (e.g. inside a list item); indentation is
preserved when the trigger is later resolved.

A trigger is **unresolved** (and eligible for dispatch) until it is
resolved one of two ways:

- The agent appends a new line immediately under the trigger line, prefixed
  `@c-reply: ` or `@cx-reply: `, containing its answer.
- For edit requests, the agent applies the edit directly to the surrounding
  text and appends ` [done]` to the end of the trigger line itself.

Once a trigger line has a `-reply:` line under it, or ends in ` [done]`, it
is treated as resolved and is not redispatched — even if the file changes
again for an unrelated reason.

### Avoiding self-triggering

Text that merely *documents* the `@c:`/`@cx:` syntax (such as this file)
does not itself get dispatched. The scanner tracks two kinds of "inert"
context line-by-line while it reads a document:

- **Fenced code blocks** — any trigger-looking line between a pair of
  ` ``` ` fence markers is skipped.
- **Blockquotes** — any line starting with `>` is skipped.

So writing `@c: example syntax` inside a fenced code block or a `>` quote
is safe and will never dispatch an agent run.

## CLI commands

`docwatch` exposes four user-facing subcommands (`add`, `remove`, `list`,
`status`). A fifth, hidden `_run-watcher` subcommand is the actual
long-running watch-loop process that `launchd` execs on your behalf — you
never invoke it directly.

### `docwatch add <path>`

Registers `<path>` (must exist and be a directory) as a watched folder:
generates a stable id, writes a `launchd` plist, bootstraps the job
(`launchctl bootstrap`) so it starts running immediately, and records the
folder in the watcher registry. Prints the new watcher's id, folder, and
log path. Fails if the folder is already registered — no duplicate jobs
are created for the same folder.

### `docwatch remove <path|id>`

Accepts either a folder path or a registered watcher id. Stops the
`launchd` job (`launchctl bootout`), deletes its plist file, and removes
the entry from the registry. Fails clearly if the folder/id isn't
registered.

### `docwatch list [--json]`

Lists every registered watcher: id, live status (`running`/`stopped`, read
from `launchctl list`), folder, and the time it was added. Prints
`no watchers registered` when the registry is empty. `--json` gives
machine-readable output.

### `docwatch status <path|id> [--json]`

Shows one watcher's live status (`running (pid <pid>)` or `stopped`) plus
the last ~20 lines of its log file — useful for seeing recent trigger
activity or errors without digging through `~/Library/Logs/docwatch/`.

## Safety model

Because the dispatched agent is given read access to the whole repository
(so it has enough context to answer well), several guards keep its writes
scoped to just the triggering document.

### Change-scope guard

Every dispatch is bracketed by a snapshot of the repo before the run and a
diff after it:

- Any file that changed during the run and was **clean beforehand**, other
  than the triggering document, is automatically reverted (`git checkout
  --` for tracked changes, or removed for new untracked files).
- Any file that **already had uncommitted changes** before the run and was
  modified further during it is left untouched — auto-reverting it could
  destroy your own unsaved work — but it is named for manual review.
- When either case occurs, the trigger line is replaced with
  `@<tag>-error: run touched files outside this document; <affected
  paths> — see <log path>` instead of a normal reply, so the failure is
  visible directly in the document.
- In a git working tree this diff uses `git status --porcelain`. Outside a
  git working tree it falls back to a plain pre/post walk recording each
  file's path, mtime, and size, restoring changed files from an in-memory
  backup taken before the run.

This same mechanism doubles as the **self-write-loop guard**: the
watcher's own expected write (the `-reply:` line or `[done]` marker it
just added to the triggering document) is recognized as the run's own
output, not a new change to react to — so the watcher does not re-dispatch
against its own reply.

### Locking

Each file has its own lock, held for the duration of one agent run. If a
save arrives for a file while a run is already in progress against it, no
second run is started — the trigger stays unresolved and is picked up on
the next scan once the lock is released, including the scan triggered by
the in-progress run's own completion write.

### Retry cap

Each unresolved trigger line is tracked by an in-memory attempt counter,
keyed by the file and the trigger line's exact text. Any dispatch that
doesn't end in a normal reply/edit or an already-handled change-scope-guard
error counts as a failed attempt. After 3 consecutive failures, the trigger
line is replaced with `@<tag>-error: agent run failed after 3 attempts —
see <log path>`, which both stops further retries and surfaces the failure
in the document. Editing the trigger line's text (asking a different
question) resets its attempt counter.

### Dispatched agents run sequentially

If a document has multiple distinct unresolved triggers (e.g. one `@c:`
and one `@cx:`), they are dispatched one at a time rather than
concurrently, avoiding concurrent-write collisions on the same file.
