---
topic: varde-skill-authoring/classify-steps
version: 1
summary: Sort each HOW step into tool, short reference, or drop
---

Start from the no-how baseline: treat every HOW step of every skill in scope as removed. Return one to the body only with cited evidence (an add-back). Classify each removed step:

- **tool:** deterministic work (scope computation, paging, snapshots, validation); move it into a bundled script or `varde` CLI flag and leave one line naming the invocation.
- **short reference:** a judgment step the agent failed without; move it to a topic under `<module>/how/<skill>/<step>.md` with a `how:` line.
- **drop:** restates a default, repeats a rule another file owns, explains rationale, or guards an edge case with no evidence of failure.

A judgment step cannot become a tool. Answer the three questions of `references/criteria.md` (Optimize each item) in order. Report the counts as `N steps: T tool, R short reference, D drop`.
