---
topic: varde-doc-authoring/cut-order
version: 1
summary: Weigh, cut, or script each item of an agent document in order
---

For each item and each checker flag, in order:

1. **Worth it?** Weigh its value against the cost of reading it (tokens times load frequency, plus maintenance) and of following it (tool calls, turns, reruns). When cost far exceeds value but cutting changes behavior, report cost, value, and a cheaper alternative.
2. **Cut it?** Cut or shorten it if it restates a default or spells out a method where the goal suffices. Cut it if it repeats a rule another file owns (point to it) or explains rationale the agent does not need. Cut it if it guards an edge case with no evidence of failure or describes internals of a tool the agent only calls.
3. **Script it?** Move deterministic work into a script or CLI flag and leave one line naming its invocation.
