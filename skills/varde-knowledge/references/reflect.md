# Reflect on finished work

Review finished work and decide what to keep. Reflection itself writes nothing;
each record type has its own procedure file.

Use this after a workflow and after direct investigation alike.

## What to record

| Type | Record it when | Procedure |
|---|---|---|
| Friction | Work hit an obstacle, needed a workaround, exposed bad guidance, or proved a useful approach | `references/note-friction.md` |
| Knowledge | Work produced a decision, finding, pattern, or definition another session needs | `references/note.md` |
| Handoff | Work is stopping or pausing, or a long run just ended | `references/reflect-handoff.md` |

## How much to consider

| Situation | Consider |
|---|---|
| A session is ending, or the user asks to wrap up | All three. Always consider a handoff. Recheck stored items if code changed. |
| Another skill calls this at the end of its own run | Friction and knowledge only. Recheck stored items if that skill changed code. Write no handoff. |

Create a handoff only at the outermost stopping point. A child build inside an
orchestrated run is not a stopping point, so use the second row.

## Workflow

Run these steps in order. Write knowledge before the handoff. Check old items
before the handoff.

1. **Friction:** If work revealed a real obstacle or useful technique, follow
   `references/note-friction.md`. When another skill called this, review only
   that skill's run; otherwise review the work just done. Record only friction
   that actually occurred.

2. **Knowledge:** If work produced a decision, research finding, reusable
   pattern, or domain term, follow `references/note.md`. Skip facts that are
   obvious, temporary, already recorded, or easy to recover. Prefer updating an
   existing note. Keep paths to any notes written.

3. **Check old items.** If code changed and could have fixed old items, reconcile
   them — the **Reconcile open items** section of `references/note-friction.md`
   for friction, and the **Check notes against code** section of
   `references/note.md` for knowledge. Both require evidence and user
   confirmation. If a friction item needs a lasting note, write the note first,
   then archive the item.

4. **Handoff:** At a session boundary, follow `references/reflect-handoff.md`. A
   completed run can still need one. Pass new knowledge-note paths as
   `kind: knowledge` links.

5. **Report.** Say what each step did, with paths and handoff IDs, and say when
   a step had nothing to record.

## Distilling recurring friction

When the user explicitly asks to review recurring friction and propose an
improvement, follow `references/reflect-distill.md` instead of this workflow. It
never runs automatically and never applies a change without human approval.

## Gotchas

- Each procedure owns its own format; compose its document there, not here.
- Keep one record per observation.
- These stores outlive the skill's installation. Each procedure explains its own
  retention rules.
