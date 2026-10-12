---
type: spec
status: active
title: "hooks install: unified Varde hooks for agent harnesses"
related:
  - "reference/nav-map"
---

# hooks install: unified Varde hooks for agent harnesses

`varde setup hooks install` and `varde setup hooks remove` manage a SessionStart,
a PostToolUse and a UserPromptSubmit hook per harness. All call the app-owned
dispatcher `varde hook session-start|post-tool-use|user-prompt-submit --harness <h>`,
which runs the providers configured in `~/.config/varde/config.toml` in process
and never fails the harness. The older per-feature Toz, code and session
installers are retired.

OpenCode has no per-user-prompt hook that adds context: its `context` hook runs
on every model call, and its `chat.message` hook is not given the message parts.
`install` therefore reports `user-prompt-submit` unsupported for OpenCode;
Claude, Codex and Pi get it. The UserPromptSubmit hook prints the main address's
unread inbox one-liners once and prints nothing when the inbox is empty.

## Invocation

```
varde setup hooks install [--harness <name>]... [--force]
varde setup hooks remove [--harness <name>]... [--force]
```

`--harness` accepts `claude`, `codex`, `opencode`, `pi`; repeat it for several.
It defaults to all four. Both commands are idempotent. An entry or file the
user edited is kept and reported with its fix, and is replaced or removed only
with `--force`.

## Providers (`[hooks]` config)

```toml
[hooks.session_start]
providers = ["nav_map", "toz_note"]  # default

[hooks.post_tool_use]
providers = ["capture"]

[hooks.user_prompt_submit]
providers = ["inbox"]  # default
```

`nav_map` times out after five seconds and produces the session-start
orientation specified below; `capture` is Toz's PostToolUse output capture;
`inbox` prints the main address's unread one-line messages, prefixing each with
`inbox: `, and advances that cursor so the next prompt prints only new ones.
`toz_note` runs when no configured instruction target holds the managed block. Legacy `orchestration` session-start entries are skipped. With no
configured instruction targets, the SessionStart hook reports a setup warning.

## Targets

| Harness | Kind | Target |
|---|---|---|
| `claude` | JSON merge | `~/.claude/settings.json`: `hooks.SessionStart`, `hooks.PostToolUse` and `hooks.UserPromptSubmit` entries |
| `codex` | JSON merge | `~/.codex/hooks.json`: the same three entries. Codex needs `hooks = true` in `~/.codex/config.toml` and asks you to trust the hooks. |
| `opencode` | Whole-file write | `~/.config/opencode/plugin/varde.ts` (the 1.x or 2.x plugin, chosen from `opencode --version`); SessionStart and PostToolUse only, `user-prompt-submit` is unsupported |
| `pi` | Whole-file write | `~/.pi/agent/extensions/varde.ts` (or under `PI_CODING_AGENT_DIR`) |

A JSON entry is Varde's when its command runs `varde` with `hook <event>`. A
whole-file plugin is Varde's when its first line records the hash of the rest.
Merges keep unrelated keys and their order.

## Migration

`varde setup sync` first retires the per-feature hooks that earlier versions
wrote, in process and only where the file or entry is unchanged: the Toz
Claude plugin and the Toz opencode and pi adapters (matched by their install
manifest), the Toz Codex hook entries and `AGENTS.md` block, the code `nav_map`
hooks, and the workflow session entries and plugin files. It then installs the
unified hooks. A legacy file the
user edited is kept and reported; delete it, then rerun `varde setup sync`.
Where sync retires a legacy SessionStart entry it passes `--skip-event
SessionStart` so that event keeps its retired state; the UserPromptSubmit event
is installed on the same run. An install that predates the event is reported by
`varde setup doctor` as a missing `UserPromptSubmit` entry with its install fix
(OpenCode's event is reported unsupported), and stays that way until the unified
install is rerun.

## What the session-start hook injects

The `nav_map` provider runs
`varde map nav_map --json '{"repoRoot":"<cwd>"}' --format text --with-project-knowledge`
in process, with `<cwd>` resolved at hook-run time (each session's actual working
directory), not baked in at install time. When the project has a durable
knowledge bundle, the text output points to `memory-bank/knowledge/` without
loading its contents. The hook always emits the same compact Varde orientation,
with a few entrypoints and shallow flows plus `varde` commands for
retrieving an expanded map, context, dependency graph, and hotspot data. When
Toz capture succeeds, it appends the handle and `varde run query` commands for
searching or reading the expanded map (still subject to per-section hard
caps). When Toz is disabled, unavailable, or capture fails, the orientation
is unchanged.

## Non-goals

- Auto-detection of which harnesses are installed on the machine; `install`
  runs explicitly, optionally scoped with `--harness`.
- A generic "run arbitrary command at session start" framework: providers are
  the built-in ones named above.
