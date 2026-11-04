---
topic: varde-manage/config-settings
version: 1
summary: Where each requested Varde setting lives and the command that sets it
---

| Setting | Where |
|---|---|
| Memory/store paths (working, knowledge, learn) | `varde setup paths set`; project scope for project settings, `--default` only for an authorized shared default; `--learn` always writes `[default]`. New setups follow the working-memory-setup topic. |
| Toz main config | `config.toml` in the config root (override with `VARDE_TOZ_CONFIG_DIR`). |
| Toz capture store | `varde setup paths set --toz`. |
| Capture privacy | `[capture]`, `[redact]`, `[raw]` sections in the installed config. |
| Runner switch | `varde runner off\|on\|status`; see the runner-commands topic. |

After a change, confirm with `varde setup doctor --json` for hook and store
wiring and re-read `varde setup paths --json` for changed paths.
