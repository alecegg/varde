---
topic: varde-swarm/select-plans
version: 1
summary: List plan sets, order ready plans by queue order, and check overlap before launching
---

## Select and order plans

- List plan sets that have unfinished plans using `scripts/select-plans.py --working <working>`; report exclusions and wait for the user's choice. Send a named non-plan request to `varde-build` and stop.
- A plan set is a folder grouping related plans; `varde plan status` lists them together.
- When main picks the next plan, read `<working>/queue-order.json` and apply its category order, dropping ids no longer waiting. Then append unlisted eligible ids in plan-id order. Missing or invalid versioned data falls back to plan-id order, and category limits still constrain launches.
- `varde plan readiness <plan.md> --json` reports what is ready. Missing dependencies or cycles block affected plans.
- Start ready plans in the chosen set one at a time in the selected order; each started plan counts as running for the next check.
- Start a ready plan with `varde-orchestrate`, passing the resolved absolute `<working>` and `<knowledge>` paths.
