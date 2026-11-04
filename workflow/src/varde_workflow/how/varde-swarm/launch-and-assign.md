---
topic: varde-swarm/launch-and-assign
version: 1
summary: Start the watcher, assign slots, issue address markers, and launch or replace orchestrators
---

## Launch and assign

- Run `varde msg` at the repo root. Use pipeline mode by default for approved multi-task plans; per-task workers remain the fallback.
- Use `varde-plan` before starting when scope is unsettled.
- For each plan, load `varde-orchestrate`: use your skill tool.
- At session start, run `varde plan watch`. Per plan: `varde plan assign <PLAN> <SLOT>`; `varde msg address new <SLOT> --plan <PLAN>` and put the printed marker in the orchestrator's first prompt; confirm a merge only with `varde plan merged <PLAN>`.
- Launch each assigned plan with `varde-runner agent launch --role <ROLE> --workspace <ID> --prompt <PROMPT> --slot <SLOT> --plan <PLAN>`; the runner adds the address marker.
- Load `references/varde-workflow-cli.md` and `references/workflow-state.md` when needed; use `references/main-agent-replies.md` for the progress reply format.
