---
topic: varde-manage/agent-models
version: 1
summary: Review and change the effective model of installed agents after sync
---

Sync prints each installed agent as "Installed varde-builder -> <path>".

1. List each installed agent with its effective model. Use the `model:` line
   (Claude, OpenCode, Pi) or `model =` and `model_reasoning_effort =` (Codex
   TOML), or "inherits the main session's model" when absent.
2. Ask the user to keep or change each one.
3. Apply changes by editing the installed agent file. Later `varde setup sync`
   runs keep `model` and Codex `model_reasoning_effort`; any other edit to an
   installed agent file is replaced.
