# Changelog

## Unreleased

- Support OpenCode 2.x from 2.0.18, warn for earlier 2.x versions, and honor `XDG_CONFIG_HOME` for sync paths.
- Lower the default session note nudge to 200k tokens and describe the orchestrator handoff.
- Record nested and hidden subcommands (for example `plan task set`, `plan merged`) in call rows so guardrail `command` entries can match them.
- Record non-fastpath `varde` calls and blocked worktree tool-install and pending-inbox hook firings in the learn store.
- Add the mailman agent profile and generated harness files for the
  `varde-mailman` relay skill.
- Add hook handling for relay delivery receipts and mailman status banners.
