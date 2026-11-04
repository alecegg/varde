---
topic: varde-skill-authoring/optimize-items
version: 1
summary: Weigh, cut, or script each skill item in order
---

For each item and each checker flag, in order:

1. **Worth it?** Weigh its value against two costs:
   - reading it: tokens times load frequency, plus maintenance
   - following it: tool calls, turns, subagents, reruns, time.

   When its cost far exceeds its value but cutting changes behavior, report the cost, value, and a cheaper alternative as an execution-cost optimization.
2. **Cut it?** Cut or shorten it if it restates a default the agent follows unprompted. Cut it if it repeats a rule another file or step owns (point to it) or explains rationale the agent does not need to act. Cut it if it guards an edge case or describes internals of a script or CLI the agent only calls.
3. **Script it?** Move remaining deterministic work into a bundled script or CLI flag: scope computation, output paging, snapshots, validation. Leave one line naming its skill-root-relative invocation and what to do with its result; give repeated outputs a template or validator.
