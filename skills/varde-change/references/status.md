# Change status

Read-only: change no plan, task, or session note. Show:

- **Plans:** run `varde plan status` and include its `**Progress**` block.
- **Session notes:** list open `<working>/session-notes/*/notes.md` files, then
  legacy `<working>/handoffs/*/handoff.md` files, newest first within each
  group, up to 5 plus a remaining count. Empty: `No open session notes.`
- **Next mode:** use `varde plan readiness <plan.md> --json` for blockers and
  actions. Recommend one mode as
  `Recommended next mode: <mode>`, then stop; never run it:
  - `plan`: unplanned work or a draft to resume;
  - `build`: one ready plan;
  - `orchestrate`: ready plans in a plan set;
  - `verify`: aggregate evidence.

Format replies with the compact progress layout: the `**Progress** HH:MM` block
from `varde plan status` (or `**Progress** HH:MM: no change since last check.`
when it matches the prior block ignoring time), one `Agents:` line, bold
`**My work**`, and bold `**Needed from you**`.
