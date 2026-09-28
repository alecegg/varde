---
type: spec
status: active
title: "hooks install: session-start nav_map injection for agent harnesses"
related:
  - "reference/nav-map"
---

# hooks install: session-start nav_map injection for agent harnesses

`hooks install`/`hooks remove`/`hooks list` are CLI subcommands (parallel to
`skills install`/`skills remove`/`skills list`) that wire `varde-code report
nav_map` into an agent harness's session-start mechanism, so nav-map
orientation is injected automatically at the start of every session instead
of requiring an agent to know to run it. Flat-flag convention, no `--json`
envelope.

## Invocation

```
varde-code hooks list
varde-code hooks install [--agent <name>]... [--force] [--dir <override>]
varde-code hooks remove [--agent <name>]... [--force] [--dir <override>]
```

`--agent` accepts `claude`, `codex`, `opencode`, `pi` — repeatable
(`--agent claude --agent codex`) or comma-separated (`--agent claude,codex`).
Defaults to all 4 when omitted. `--dir` overrides the install target
directory (primarily for testing); without it, each agent resolves its real
per-OS, user-level default.

## Supported agents and install targets

| Agent | Kind | Target | Injected content |
|---|---|---|---|
| `claude` | JSON merge | `~/.claude/settings.json` | `SessionStart` hook entry under `hooks.SessionStart[].hooks[].command` |
| `codex` | TOML merge | `~/.codex/config.toml` | `[hooks.session_start]` table with a `command` key |
| `opencode` | Whole-file write | `~/.config/opencode/plugin/varde-code-nav-map.js` | Embedded plugin JS, session-start-equivalent handler via opencode's `$` executor |
| `pi` | Whole-file write | `~/.pi/agent/extensions/pi-extension.js` | Embedded extension JS, `pi.on("session_start", ...)`, returns `{ systemPrompt }` |

Every target's injected command is
`varde-code report nav_map --json '{"repoRoot":"<cwd>"}' --format text`,
with `<cwd>` resolved at hook-run time (each session's actual working
directory), not baked in at install time.

All 4 targets install at **user-level scope** by default — not
project-local. Codex specifically avoids project-local (`.codex/config.toml`)
because of a known upstream reliability bug with project-local hooks; the
other 3 agents follow the same user-level convention for consistency.

## Merge vs whole-file semantics

- **claude, codex (merge targets):** `install` merges one hook entry into
  the existing config file without touching unrelated keys/tables (JSON via
  `serde_json`, TOML via `toml-edit` to preserve the user's comments and
  formatting). `remove` deletes only the injected entry, identified by a
  stable `__source: "varde-code"` marker — the rest of the file is
  untouched.
- **opencode, pi (whole-file targets):** `install` writes a dedicated plugin/
  extension file; `remove` deletes that file entirely (same whole-file
  semantics as `skills_remove`).

## Content-diff protection

Both install and remove are idempotent and protect local edits: if the
previously-installed entry (merge targets) or file (whole-file targets) has
been modified since install, `install`/`remove` leave it in place and report
it as skipped, rather than clobbering the user's changes. Pass `--force` to
override this and install/remove anyway, discarding the local edit.

## `hooks list`

Prints the 4 supported agents and their install target path — no filesystem
writes, no install/remove side effects. Use it to check targets before
running `install`.

## Round-trip example

```
varde-code hooks install --agent claude --dir /tmp/test-claude
cat /tmp/test-claude/settings.json   # SessionStart entry present
varde-code hooks remove --agent claude --dir /tmp/test-claude
cat /tmp/test-claude/settings.json   # entry gone, any pre-existing unrelated keys untouched
```

## Known follow-up gap

The opencode and Pi targets are implemented **best-effort** against each
harness's documented plugin/extension API — this pass does not include a
live opencode or Pi install verification. If the shape of either harness's
plugin API has drifted from what's documented, the installed file may need
manual adjustment. Not a blocker for this feature; tracked as a follow-up,
not solved here.

## Non-goals

- Auto-detection of which agents are installed on the machine — `install`
  always runs explicitly, optionally scoped with `--agent`.
- Version migration or uninstall-on-upgrade logic for the injected hook
  content — same content-diff protection as `skills_remove`, not a
  versioned migration system.
- A generic "run arbitrary command at session start" framework — this hook
  always injects `nav_map` specifically.
