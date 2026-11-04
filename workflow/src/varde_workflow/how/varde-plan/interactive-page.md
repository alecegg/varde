---
topic: varde-plan/interactive-page
version: 2
summary: Serve the draft as a page and handle its comments
---

- Run `varde learn docs serve <plan.md>` in the background and give the user its URL.
- Run `varde learn docs watch <plan.md>` under the harness monitor; answer with
  `varde learn docs reply`. Page comments differ from runner-dashboard comments
  (topic `resume-plan`).
- On each `varde learn docs watch` line, read the open comments with `varde learn docs comments <plan.md>`
  and edit the plan; the served page refreshes on save.
- After a session restart, restart `varde learn docs watch` with `--all`.
