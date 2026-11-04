---
topic: varde-toz/troubleshoot
version: 1
summary: Toz sandbox modes, part 1 of 2, failures and the ask-before-grant rule in troubleshoot-failures
---

## Sandbox

- No `[sandbox]` section in the configuration root's `config.toml` (`varde setup doctor --json` shows the root): `run` inherits the launching shell's permissions, so `vardeToz.exec()` can launch arbitrary commands. A harness sandbox still covers them.
- `[sandbox]` present (unless `enabled = false`): `run` uses Seatbelt (macOS) or Bubblewrap (Linux) with workspace read/write and no network by default. `run` fails if the backend cannot start. Use `run` only for commands within its grants, and the harness tool otherwise.
