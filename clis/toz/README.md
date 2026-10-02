# varde-toz — tool-output-zone

Toz keeps large tool output out of a coding agent's context. Harness hooks save long results in a local, searchable store and return a short preview with a handle. Previews highlight up to six error or warning lines with stream and line numbers. Agents use `query` to retrieve selected parts and `run` to batch commands and capture analysis in one call.

Toz supports Claude Code, pi, opencode, and Codex on macOS and Linux.

## Install

The package installs `varde-toz` and the compatibility alias `toz`. Both use
the same stores and configuration. Existing hooks and scripts keep working.

```sh
cargo install --path clis/toz/crates/toz --locked
varde-toz install claude-code       # or: pi | opencode | codex
varde-toz doctor
```

`varde-toz install` places hooks and adapters in their normal locations. It is idempotent. Rerun it after upgrading toz or a harness. `varde-toz uninstall <harness>` removes unchanged toz-owned files and hook entries while preserving local edits. Codex install removes the legacy Toz block from `~/.codex/AGENTS.md` and leaves the rest of that file intact; it no longer installs a standalone block. Run `varde-workflow instructions install` to install the shared Varde block, which includes `varde-toz note --block` output when the CLI is available. Toz no longer ships its own SessionStart hook for Claude Code or Codex; reinstalling strips a legacy Toz SessionStart entry. The `varde-toz` skill is installed separately through Varde’s `skills/install.sh` or `varde sync`; the CLI installer owns only harness adapters and usage notes. The opencode installer detects its 1.x or 2.x API from `opencode --version`; `--for-version X.Y.Z` overrides that choice.

`varde-toz note --block` prints the static Codex guidance used in Varde's shared
instruction block. The regular `varde-toz note` output may include diagnostics.

| Harness | Capture path |
|---|---|
| Claude Code | `PostToolUse` replaces tool output; the unified `varde-workflow hook session-start` hook adds guidance |
| pi | `tool_result` replaces text; the system prompt gets guidance |
| opencode | Tool hook replaces text; context hook adds guidance |
| Codex | `PostToolUse` captures supported results; structured results may keep their original content and receive a handle hint |

Pi codemode nested results are captured while their original text and structured values stay available to the calling script. For clipped shell results, Toz reads the complete `full_output_path` file before capture. An unreadable supplied file records a diagnostic and leaves the result untouched. Large direct and final codemode text results still receive the usual preview, with nontext blocks kept in place.

Prefer harness-native code mode or Programmatic Tool Calling when it can call the required tools and results remain recoverable after the script ends. Retain results before filtering and print a concise summary. If the summary omits a detail, query the retained output instead of executing the command again; `query --list` discovers handles the script did not print, and `--source` narrows searches by command.

Hooks capture only output the harness supplies, subject to capture thresholds and exclusions. Codex can clip command output before hooks inspect it. Use a verified complete persisted file for analysis, or `varde-toz run` when you need a complete capture handle. Toz captures its child command streams before the harness can truncate them; `capture: true` also retains small command results. Native code mode availability alone does not guarantee callable local tools or complete captures.

## Query stored output

```sh
varde-toz query --handle t94d "failed assertion" "panicked"  # search one capture
varde-toz query "connection refused"                       # search this project
varde-toz query --handle t94d --chunk 7                    # read one chunk
varde-toz query --handle t94d --lines 120:160              # read a line range
varde-toz query --list                                     # recent captures
```

Search results are ranked and show short snippets with line numbers. Use `--global` to search all projects, `--source` to narrow by label, and `--all` to include superseded captures. Searchable text is normalized and redacted before storage; it is not a byte-for-byte archive.

Exact bytes are a separate, opt-in store. Enable `[raw] enabled = true`, request raw retention in `vardeToz.exec({raw: true, ...})`, then use `varde-toz query --raw <raw-handle> --stream stdout|stderr`. Raw handles expire after the configured lifetime. Never-capture rules exclude content from both stores.

New capture sources and labels apply configured redaction before storage or display. Fetch metadata and messages hide URL credentials and query values. Run `varde-toz migrate-metadata` to redact older metadata in stores reachable from the current configuration and the shared fetch cache. It preserves capture handles and separate raw output. An indexed file whose path or explicit label was redacted needs manual reindexing after changes.

## Index files and web pages

Use `index` for local material and `fetch` for a web page you want to search alongside captured output. Both return a handle that works with `query`:

```sh
varde-toz index notes.md
varde-toz index docs/ --recursive --glob '*.md'
varde-toz fetch https://example.com
varde-toz query --handle HANDLE "example"
```

Project searches refresh indexed files when their contents change. `fetch` caches pages for 24 hours by default; use `--force` to fetch again. Replace `HANDLE` with the handle printed by `index` or `fetch`. Run `varde-toz index --help` or `varde-toz fetch --help` for the remaining options.

## Run a batch script

```sh
varde-toz run --script - <<'JS'
const files = vardeToz.exec({argv: ['/bin/ls', '-la']});
const location = vardeToz.exec({argv: ['/bin/pwd']});
print(JSON.stringify({files: files.capture.preview || files.stdout, directory: location.stdout.trim()}));
JS
```

`--code '<js>'` accepts a one-liner. A heredoc avoids shell quoting problems. `run` executes the script in QuickJS. By default, its command subprocesses inherit the permissions of the process that launched toz. `vardeToz.exec()` accepts `argv` or `shell`, plus optional `cwd`, `env`, `timeoutMs`, `capture`, and `raw`. A nonzero command exit is returned in `exitCode`; startup errors raise a script exception.

After each command finishes, the parent compares combined stdout and stderr
bytes with the configured capture threshold (not the file-read limit), capped at the 64 KiB inline
preview limit. Short output returns complete `stdout`/`stderr`,
`capture.state: "inline"`, and no handle; larger output is stored with a
searchable handle and bounded previews. `capture: true` forces searchable
capture for short output. `raw: true` also forces searchable capture and
requests exact-byte retention when enabled. Never-capture rules override both.
For captured commands, `capture.preview` contains the normal preview,
including configured output profiles. `stdout` and `stderr` remain bounded
excerpts for scripts; `capture.handle` retrieves the full stored output.

The final printed result passes through under the capture threshold. Larger
results return the normal preview and a searchable handle. `--json` renders
captured previews as JSON; under-threshold output stays as printed. `--quiet`
hides preview detail only on overflow.

Pass an existing capture with `--handle` to analyze it without bringing its body into the agent context:

```sh
varde-toz run --handle t94d --script - <<'JS'
const counts = {};
vardeToz.eachLine(line => {
  const match = line.match(/status=(\d{3})/);
  if (match) counts[match[1]] = (counts[match[1]] || 0) + 1;
});
print(JSON.stringify(counts));
JS
```

`vardeToz.eachLine(fn)` streams capture text; `vardeToz.text()` loads it up to a configured limit. `vardeToz.handle` provides metadata. `--stream stderr` selects the other stream, and `--partial` permits a running capture. Scripts have wall-clock, heap, and output limits. QuickJS has no ambient filesystem or network API, but scripts can use `vardeToz.exec()` to run commands with the worker's permissions.

## Sandbox permissions

Toz reads `~/.config/varde-toz/config.toml` by default. Its OS sandbox is off when no `[sandbox]` section exists. An existing `[sandbox]` section remains enabled for compatibility, even without an `enabled` key. Set `enabled = false` to turn it off, or enable it to add restrictions to scripts and their child commands:

```toml
[sandbox]
enabled = true               # opt in to Seatbelt or Bubblewrap
workspace = "read-write"       # none | read-only | read-write for the project root
read_roots = []                # additional absolute directories
write_roots = []               # additional absolute writable directories
network = false               # allow network for the worker and child commands
env_allow = []                # additional host environment variable names
```

When enabled, the default policy grants workspace reads and writes but no network access. The worker also gets a writable scratch directory. It receives PATH, HOME, LANG, LC_ALL, LC_CTYPE, TERM, and names in `env_allow`; TMPDIR, TMP, and TEMP point to scratch. Its descendants inherit the same restrictions.

Seatbelt enforces the enabled policy on macOS and Bubblewrap on Linux. In this mode, the parent owns the capture database and raw-output store; those paths are not granted to the worker. Toz rejects file grants that overlap a protected store path and fails closed when it cannot start the requested sandbox.

With toz's OS sandbox off, the worker and its child commands keep the launching process's filesystem, network, and environment access. If Codex launches `varde-toz run` through a sandboxed shell or exec call, Codex's restrictions also apply to the worker and its children. If that call is escalated, they receive the escalated permissions. A direct terminal launch uses the terminal's permissions. Hooks and separately launched servers have their own launch paths; their permissions do not determine those of a later `varde-toz run` call.

QuickJS has no direct filesystem or network API, but a script can run arbitrary commands through `vardeToz.exec()`, including commands that read toz's database or raw-output files when the launching process can access them. Enable toz's OS sandbox if the script must be isolated from those files. When enabled, its restrictions combine with any outer harness sandbox; toz cannot grant access that the outer sandbox denies.

When the OS sandbox is enabled, use `run` for project work whose commands and dependencies fit the granted paths. On macOS, Apple Git may load files under `/Applications/Xcode.app` and read user Git configuration, which that policy does not grant. Other tools installed outside the system paths can have similar dependencies. Grant the required directories when appropriate; otherwise invoke those commands through the harness's normal tools.

Those tool calls remain eligible for toz's capture hook because the hook runs outside `run`'s sandbox. The hook can save only output the harness delivers; Codex may truncate long command output first.

## Usage stats

`varde-toz stats --json` reports capture input bytes, preview bytes, query counts,
query readback bytes, and net saved bytes. Net savings subtract every successful
`query` stdout byte from the original capture savings, including repeated reads.
Historical query reads are not reconstructed. Query stdout is a proxy for model
context: a pipe or terminal may consume fewer bytes than toz emitted. If usage
logging fails on a read-only store, the query still succeeds and warns that its
readback was not counted.

`varde-toz stats --events 100 --json` includes the 100 newest query events per
project; add `--session` to narrow them to the current session. Events record
the requested capture handle, returned project/handle IDs, search and filter shapes,
result counts, retrieval position, outcome, and emitted bytes. Failed attempts
remain visible but do not count as successful reads. Search terms, source-filter
values, result snippets, and command text are not stored in query events. Raw
handles are stored only as one-way fingerprints because they grant access to
exact retained bytes.

## Storage and configuration

Default project databases live under `~/.config/varde-toz/<project-key>/toz.db`. Database files use `0600`; parent directories use `0700`. Harness adapters use this primary store by default. If access fails and the user declines the needed permission, `VARDE_TOZ_FALLBACK_DIR` or `--fallback-dir` opts into an external store. Toz tries it only after a primary-store access error. Use the same fallback for hooks, `query`, and `run`; it cannot recover captures that a failed hook never saved. `VARDE_TOZ_CONFIG_DIR` relocates the primary store.

Capture hooks pass output under the default 4 KiB threshold through unchanged.
Above it, they save normalized, redacted text and return a preview. File reads
use a higher limit: 16 KiB, or the global `threshold` if larger. A file read is
a tool named `read` (any case) or, in any harness, a single simple shell
`cat`, `head`, `tail`, `nl`, or `sed -n` command with no pipe, redirect, `;`,
`&` (covers `&&`), `||`, `$(`, backtick, or newline. `[thresholds] read = N` overrides the
read limit; an exact tool key such as `Read = N` wins over both.
`vardeToz.exec()` uses the completed command's actual byte count and the same
configured threshold, capped at 64 KiB. The normal store strips ANSI escapes,
normalizes line endings, and replaces invalid UTF-8. Raw retention requires an
explicit request and is disabled by default.

`varde-toz capture --defer-index` uses the same chunk store but postpones full-text indexing until the first term search. Line-range reads and scripts can use the handle immediately. Use it when capture latency matters more than the first search latency; ordinary captures still index as they are stored.

Other configuration sections include `[retention]` for age and size limits, `[redact]` for secret patterns, `[capture]` for never-capture rules, `[script]` for runtime limits, and `[raw]` for exact-byte retention. Use `varde-toz doctor` to inspect installation and store health.

## Output profiles

A profile shapes how one kind of capture gets sectioned, previewed, and optionally mined for structured records. Profiles load from three scopes and merge by `id`, later scope winning.

Built-in profiles ship with toz. The user file is `~/.config/varde/toz/profiles.toml`, resolved via `$VARDE_CONFIG_DIR`, else `$XDG_CONFIG_HOME/varde`, else `~/.config/varde`.
The project file is `.varde/toz-profiles.toml` at the repo root.

A project profile's `script` only runs when the user's `profiles.toml` lists the project root under a top-level `trusted_projects = ["/abs/path", ...]`; otherwise the script is dropped and `varde-toz doctor` reports why.

Each `[[profile]]` entry sets:

- `id` — merge key across scopes.
- `match` — `{ command = "<glob>" }` (hook command line) or `{ source = "<glob>" }` (any capture's origin string); exactly one.
- `sections` — `{ heading = "<regex>" }`, `{ start = "<regex>" }`, or `{ jsonl_key = "<field>" }`; exactly one.
- `merge_small` — merge undersized sections (default `true`).
- `preview` — `{ kind = "toc" | "head", items_per_section, item }`.
- `script` — a QuickJS program (see below), optional.
- `[[profile.test]]` — inline cases: `name`, `input`, `expect_records = { <kind> = [...] }`, `expect_preview_contains = [...]`.

A declarative TOC profile, no script:

```toml
[[profile]]
id = "pytest-summary"
match = { command = "pytest*" }
sections = { heading = "^(PASSED|FAILED|ERROR) " }
preview = { kind = "toc", items_per_section = 3 }
```

A script profile that records one entry per test line from `cargo test` output:

```toml
[[profile]]
id = "cargo-test-summary"
match = { command = "cargo test*" }
script = '''
let pass = 0, fail = 0, ignored = 0;
const failures = [];
vardeToz.eachLine(line => {
  const m = /^test (\S+) \.\.\. (ok|FAILED|ignored)$/.exec(line);
  if (!m) return;
  const [, name, status] = m;
  vardeToz.record("test", { name, status });
  if (status === "ok") pass++;
  else if (status === "ignored") ignored++;
  else { fail++; failures.push(name); }
});
print(`${pass} passed, ${fail} failed, ${ignored} ignored`);
if (failures.length) print("failed: " + failures.join(", "));
'''

[[profile.test]]
name = "counts and records one failure"
input = "test a::b ... ok\ntest c::d ... FAILED\n"
expect_records = { test = [{ name = "a::b", status = "ok" }, { name = "c::d", status = "FAILED" }] }
expect_preview_contains = ["1 passed, 1 failed"]
```

A profile script runs exec-free QuickJS: no `vardeToz.exec()`, a 1-second timeout, a 64 MB heap, and a 4 KB preview budget. It gets `vardeToz.eachLine(fn)`, `vardeToz.text()`, `vardeToz.handle`, `print(...)`, and `vardeToz.record(kind, obj)`. A script failure falls back to the normal preview and reports a diagnostic through `varde-toz doctor`.

`varde-toz profile list [--json]` shows loaded profiles (id, scope, file, whether they carry a script) and load diagnostics. `varde-toz profile test [--file <path>] [--json]` runs every `[[profile.test]]` case, printing `pass: <id> / <case>` or `FAIL: <id> / <case>: <reason>` and exiting 1 on any failure. `varde-toz query --handle <H> --records <kind>` prints a matched profile's recorded entries of that kind as JSONL.

## Hook diagnostics

Hooks record capture outcomes in `~/.config/varde-toz/diagnostics.jsonl`, or in the configured harness fallback directory when that path is unavailable. The log stores only time, harness, outcome, reason, tool name, and byte count. It does not store tool input, output, or error text. The file rotates at 1 MiB and keeps one previous file. `varde-toz doctor --json` reports retained outcomes from the last seven days and warns when captures failed or records cannot be read. A later agent session also gets a short notice. If a handle is missing or retrieval fails, include the doctor report, the command, and the expected and actual result in a bug report. Hooks still pass through the original output when capture fails.

## Development

```sh
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

## License

MIT

Compatibility: legacy `TOZ_*` environment inputs remain accepted; `VARDE_TOZ_*` inputs take precedence. The default settings/store root is `~/.config/varde-toz`; an existing `tool-output-zone` root remains in use until migrated. `vardeToz` and `toz` refer to the same script API object.
