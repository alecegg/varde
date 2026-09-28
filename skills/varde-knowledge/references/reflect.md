# Reflect on finished work

Runs at a session boundary: the session is ending, the user asks to wrap up, or
a top-level plan or orchestrated feature just completed. Mid-run lessons from
other skills go to their owner: record obstacles with the `varde-learn` skill
and durable lessons with `references/note.md`.

## Workflow

Run in order; write knowledge before the handoff.

1. **Friction.** Capture each real obstacle through the `varde-learn` skill.
   Do not write friction Markdown from this workflow.
2. **Knowledge.** Record a decision, fact, pattern, or definition another
   session needs, per `references/note.md`. Skip what is obvious, temporary,
   already recorded, or easy to recover; prefer updating an existing note.
   Note the paths for step 3.
3. **Handoff, only when something is left for a later session:** unfinished
   plan work, and also next steps, follow-up refinements, deferred review items,
   or open questions beyond a completed plan. Follow
   `references/reflect-handoff.md`; pass new note paths as `kind: knowledge`
   links. When nothing is left, write none: the plan, its conclusion, and the
   commits are the record — unless the user asked for one.
4. **Check old items, only when the user asks.** Reconcile notes against
   current code per `references/reconcile.md`; route friction reconciliation
   to the `varde-learn` skill.

Report knowledge paths and any handoff ID, plus the Learn item IDs recorded or
that friction could not be recorded. If nothing needed recording, say so.
