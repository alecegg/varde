---
type: task
parent: root-varde-init
status: done
verified: passed
depends_on: ["init-command"]
modifies:
  - AGENTS.md
  - README.md
creates:
  - memory-bank/knowledge/reference/varde-init.md
---

Document the root wiring entry point.

Amend the repository conventions to name `varde init` as the only root
wiring entry point while retaining the no-root-build-or-test rule. Add concise
root usage guidance and a durable reference concept for the user-visible flow.

#### Out of scope

- Module-level installer documentation rewrites.
- Build or test instructions at the repository root.

#### Verification

- assert: `rg -q 'varde init' AGENTS.md README.md memory-bank/knowledge/reference/varde-init.md` → exits 0
- assert: `rg -q 'no root build or test entry point' AGENTS.md` → exits 0
- retrieve: `AGENTS.md README.md memory-bank/knowledge/reference/varde-init.md` → guidance matches the implemented interface

#### Progress

- Documented `varde init` as the root wiring entry point.
