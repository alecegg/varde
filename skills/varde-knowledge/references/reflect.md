# Reflect on finished work

Runs at a session boundary: the session is ending, the user asks to wrap up, or
a top-level plan or orchestrated feature just completed.

## Workflow

Run in order; write knowledge before the handoff.

1. **Friction.** Capture each real obstacle through the `varde-learn` skill;
   skip this step when none occurred.
2. **Knowledge.** Per `references/note.md`, record what another session
   needs, preferring updates to existing notes; note the paths for step 3.
   Skip anything that is:
   - obvious;
   - temporary;
   - already recorded;
   - easy to recover.

3. **Handoff, only when something is left for a later session:** unfinished
   plan work, and also next steps, follow-up refinements, deferred review items,
   or open questions beyond a completed plan. Follow
   `references/handoff-write.md`; pass new note paths as `kind: knowledge`
   links. When nothing is left, write none: the plan, its conclusion, and the
   commits are the record — unless the user asked for one.
4. **Check old items, only when the user asks.** Reconcile notes against
   current code per `references/reconcile.md`; route friction reconciliation
   to the `varde-learn` skill.

Report knowledge paths and any handoff ID, plus the friction item IDs
recorded or a note that friction could not be recorded. If nothing needed
recording, say so.
