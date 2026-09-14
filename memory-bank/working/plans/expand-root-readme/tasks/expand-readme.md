---
type: task
parent: expand-root-readme
status: backlog
verified: pending
depends_on: []
modifies:
  - README.md
creates: []
---

# Expand root README as monorepo guide

Make the root README a detailed, accurate navigation document.
Use module README files as the source of truth.

#### Out of scope

- Changing module implementation or packaging.
- Adding a repository-wide build system.
- Rewriting module-level documentation.

#### Verification

- assert: `cd skills && ./install.sh -h` → installer help succeeds.
- assert: `cd agents && ./install.sh -h` → installer help succeeds.
- assert: `cd code-cli && cargo build && cargo test` → build and tests pass.
- assert: `cd docs-cli && cargo build && cargo test` → build and tests pass.
- assert: `for target in AGENTS.md LICENSE skills/README.md agents/README.md code-cli/README.md docs-cli/README.md; do test -e "$target"; done` → all linked targets exist.
- retrieve: `rg -n 'self-contained module|no root build|cargo build|cargo test|install\\.sh|varde-code|varde-docs|docwatch' README.md` → confirm key guide terms exist.

#### Progress

