# Friction items

## Record a real problem

Record useful observations in `memory-bank/friction/`. Each item is plain
Markdown in the repository. A monorepo whose modules each own a `memory-bank/`
gets one store per module — write the item under the module whose work hit the
friction, not the repo root.

Capture a real event, not a general impression. Good examples:

- A command failed because documentation was stale.
- An agent repeated a manual workaround.
- A tool behaved in a surprising way.
- A documented technique worked especially well.

This pass only captures. Grouping, promoting, and dismissing belong to
`references/reflect-distill.md`; fixing the underlying problem belongs to the
target skill. Source from the current conversation and working memory alone.

## Scope the review

| Situation | What to do |
|---|---|
| Friction appears during work | Record it now. Use the current task or skill as `source`. |
| A calling skill asks for a closing review | Review that skill's work, tool output, and subagent work only. Use that skill as `source`. |
| A user asks for a friction review | Review the current conversation and working memory. Ask only if the event or source is unclear. |
| Reflection asks for a reconcile pass | Follow **Reconcile open items**. Capture no new items. |

If no concrete event exists, say so and write nothing.

## Capture an item

1. State the event in one clear sentence.
2. Record evidence from the current context.
3. Describe the cost or impact.
4. Name a possible improvement target, if known.
5. Run `git rev-parse --short HEAD`. Use `none` outside Git.
6. Set `session_label` to the session name, or a sanitized first prompt capped
   at 46 characters.
7. Search every friction store for an open match with `Glob` and `Grep` —
   `**/memory-bank/friction/*.md`, not just the root one. A repeat recorded
   under another module is still a repeat.
8. Read `references/note-friction-format.md` before writing or appending.
9. Create an item, or append a new occurrence. A captured item keeps whatever
   `status` it already had.

Keep genuine repeats. They show how often a problem occurs.

## Reconcile open items

Use this during a reconcile pass only.

1. Read open items in scope. Prefer items older than `HEAD`.
2. Check whether the named problem was fixed: run
   `git log <head_sha>..HEAD -- <path>` for each named path, then read the
   current code or guidance.
3. An item stays open until evidence shows the problem is gone.
4. For each candidate, explain the evidence and ask the user.
5. After confirmation, change `open` to `resolved` or `archived`.

Items retire by status. Archiving keeps the record; deletion loses it.

For a positive item or durable lesson, write the knowledge note first
(`references/note.md`), then archive the item.

## Gotchas

- Friction items outlive this skill's installation.
- They may include paths, quotes, and error text.
- Read `references/note-friction-format.md` only before item mutations.
