---
topic: varde-improve/loop-decide
version: 1
summary: Improvement loop steps 4-5, after report - accept or reject a proposal, compare later demand
---

## 4. Decide

- `varde learn skills accept <id>` applies the stored diff only after the page's decision block was answered `approved` (otherwise exit 2 naming the page). It refuses if a file changed since the proposal.
- `skills reject <id>` marks it rejected and changes no file.
- Neither can be undone; a reverted trim is a new proposal.
- `accept --root <pkg root>` writes repo sources (installed skills otherwise).
- A baseline restore is checked against its `tree_hash` after writing (mismatch: files restored, nothing applied). A hand-edited installed skill that is not restored is listed.

## 5. Compare

After an accepted reset, run `skills reset <skill>` again with the same versions to see before and after counts. `skills demand` shows later how requests and tool calls. Repeated requests bring a step back.
