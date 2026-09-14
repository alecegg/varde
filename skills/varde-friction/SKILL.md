---
name: varde-friction
description: >
  TRIGGER: Capture concrete agent friction when an obstacle, workaround,
  repeated confusion, missing guidance, failed operation, or avoidable rework
  should be recorded for later improvement.
  SKIP: Skip friction capture when no concrete obstacle or reusable lesson
  occurred, or when the observation is only a vague preference or speculation.
  Example phrases: "capture this friction" or "review this session for friction".
---

## Scope

Capture concrete friction items for later distillation — the default motion
only records observations. It does not cluster items or edit skills, docs,
commands, or application code. The one exception is **reconcile mode** (below),
invoked by `varde-reflect`, which retires items whose obstacle the code has
since fixed — an evidence-gated status transition, still not a code edit.
Review only the invoking agent's current conversation and working memory; do
not parse external transcript logs or infer events outside that context.

Capture friction when the session contains a concrete (not vague, not
ordinary task complexity — see SKIP above):

- obstacle or failed operation;
- workaround, repeated manual step, or avoidable rework;
- missing, stale, or misleading skill, documentation, command, or API detail;
- confusing workflow, tool behavior, or recurring decision point;
- positive signal worth generalizing: a technique/rule/approach that worked
  well, or an explicit user confirmation of a non-obvious choice (e.g. "yes
  exactly") — these validate what to keep, not just what to fix.

## Storage and persistence

Items are plain Markdown under the project's `memory-bank/friction/` — in-repo,
so they show in `git status` and travel with the branch. They **persist and
survive uninstalling this skill** (uninstalling removes the skill, not the
captured items), and they may quote source, file paths, and error text from the
repo where they were captured. Retire them through reconcile mode; don't leave a
growing pile assuming it self-cleans.

## Entry point dispatch

| Invocation | Action |
|---|---|
| Immediate self-invocation (friction becomes clear mid-session) | Capture it right away: summarize the event, impact, workaround/cost, and likely improvement target. Use the current skill or task as `source`. |
| Closing-step review (`varde-reflect` — or another skill directly — invokes this at a work-unit close, e.g. "review this session for friction in the use of the `X` skill") | Scope the review strictly to that invocation's own execution — the calling skill's workflow steps, its subagent calls, and its own tool output — not the full conversation or turns from other skills. Use the named skill as `source`. Capture each distinct item; if none exists, report that and make no write. |
| Standalone or manual review (user or agent invokes this skill directly) | Review the current conversation and working memory retroactively; capture concrete items found there. Ask for clarification only when the source or event cannot be stated accurately from that context. |
| Reconcile (`varde-reflect` invokes with `mode=reconcile` at a boundary) | Don't capture — run the **Reconcile mode** flow below: retire open items whose obstacle the work has since fixed, evidence-gated and confirm-gated. |

## Workflow

1. **State the friction.** One precise sentence. If you cannot name a concrete,
   reusable obstacle (or positive) in one sentence — only a vague "there was
   some confusion" — **stop and report no capture**. An empty or vacuous item
   is noise, not a recurrence; refuse it visibly rather than writing junk. (A
   genuine *duplicate* of an existing item is the opposite — keep it; see
   step 6.)
2. **Record evidence.** From the current context.
3. **Describe the impact.** User or agent impact.
4. **Name the improvement target.** If known.
5. **Capture the provenance anchor.** Run `git rev-parse --short HEAD` for
   `head_sha` (record `none` outside a repo) and derive `session_label` (the
   session name, else the sanitized first prompt capped at 46 chars). These
   stamp the item so a later reconcile pass can anchor it — see
   `references/ITEM-FORMAT.md`.
6. **Search for an existing match.** Use `Glob` on `memory-bank/friction/*.md`
   and `Grep` across those files for a matching open item (same recurring
   obstacle or target, `status: open`).
7. **Write or append the item.** Full procedure: `references/ITEM-FORMAT.md`.
   On a match, **append a new occurrence** (recurrence is intentional signal —
   never merge or dedup it away), stamping the occurrence with its own
   provenance so the count stays legible.
8. **Re-verify.** Re-read the file with `Read` before reporting success.
9. **Report and stop.** State the item file paths captured, or that no
   concrete friction was found. Never change an item's status during
   capture, and do not cluster, promote, dismiss, or auto-remediate — those
   are the reconcile motion (below), not capture.

## Reconcile mode

Invoked by `varde-reflect` at a work boundary (`mode=reconcile`) to check open
items against what the work just changed — capture writes items, reconcile
retires them. This is the one motion allowed to change an item's `status`, and
it is **evidence-gated and confirm-gated**:

1. **Read the open items** in scope (`status: open`), preferring those whose
   `head_sha` predates current `HEAD`.
2. **Look for evidence the obstacle is gone.** For each item, run
   `git log <head_sha>..HEAD -- <path>` over the paths it names, and read the
   current code/guidance. The claim "this is resolved" must cite a commit, a
   now-present file, or fixed guidance. **No evidence → leave it untouched.**
   This is what keeps the pass bounded and honest.
3. **Propose transitions with their evidence, and confirm before writing.**
   Present each candidate as "item #N looks resolved because <evidence>" and
   change nothing until the user confirms the specific items.
4. **Transition, don't delete.** On confirmation, `Edit` the item's `status`
   `open` → `resolved` (and later `archived`). This skill does the status
   Edit; it does **not** write knowledge notes (no `Skill` tool here). When a
   `positive` or a durable lesson is still worth keeping, flag it for promotion
   and let the caller (`varde-reflect`, which owns both leaves) write the note
   via `varde-knowledge` **first**, then have this skill archive the item. The
   unit of a promote is the *whole* move: the note must exist before the item
   is retired, so the lesson never lands in neither store.

## Gotchas

- Friction items need no special database or tooling — they're plain Markdown
  you Glob/Grep/Edit directly; see `references/ITEM-FORMAT.md` for the
  frontmatter and append convention.
