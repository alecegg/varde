---
type: task
parent: root-varde-init
status: done
verified: passed
depends_on: []
modifies:
  - skills/install.sh
  - agents/install.sh
creates:
  - varde
  - tests/varde-init-test.sh
---

Implement the root `varde init` wiring command.

Add POSIX shell argument parsing and config-directory detection for Claude,
Codex, and OpenCode. It must only delegate writes to the module installers.
Support `--agents`, `--yes`, `--dry-run`, `--list-agents`, and `-h`. Extend
the installers only where necessary for non-interactive and dry-run delegation.
Keep foreign target files untouched and make repeated invocation idempotent.

#### Out of scope

- A root build or test command.
- Changes to harness instruction files.
- Any harness besides claude, codex, and opencode.

#### Verification

- assert: `tests/varde-init-test.sh` → exits 0 and covers dry-run, no-TTY, repeated install, foreign-file preservation, and harness listing
- assert: `sh -n varde && bash -n skills/install.sh && bash -n agents/install.sh` → exits 0
- retrieve: `./varde init --list-agents` → exact supported harness list

#### Progress

- Added the POSIX `varde init` wiring command and installer dry-run delegation.
