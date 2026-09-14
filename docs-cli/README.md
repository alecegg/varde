# varde-docs

OKF (Open Knowledge Format) knowledge CLI. Lives in the [varde](../) monorepo as
the `docs-cli` module (its own Cargo workspace).

Designed from two references, neither copied wholesale:

- **A prior generic knowledge/OKF implementation** — generic Concept CRUD, OCC
  version-checked writes, bundle validation, `note_show`/`docs_search`-style
  retrieval.
- **[pi-llm-wiki](https://github.com/zosmaai/pi-llm-wiki)** — personal + project
  vault layering, four-layer raw-source/source-page/canonical-page/meta
  pipeline, contradiction-aware lint.

## Status

Pre-alpha. Now the `docs-cli` module of the [varde](../) monorepo; whether/how the
varde skills depend on or migrate to this tool is still an open decision, not
assumed up front.

## Scope (draft)

- Generic OKF bundle/note operations: create, read, search, version-checked
  writes, validation, cleanup/lint
- Personal + project knowledge layering (see pi-llm-wiki's vault model)
- Contradiction-aware lint

Out of scope for now: workflow-specific bundle types (plans, findings, handoffs,
scan/review workflows) — this CLI stays a generic OKF store.

## Workspace layout

A Rust workspace (`Cargo.toml`) with three crates:

- **`okf-core`** — library implementing OKF v0.2 Concept/Bundle CRUD, OCC
  version checks, vault layering, and `lint`.
- **`varde-docs`** — the CLI binary (`clap`-based) that wraps `okf-core`.
- **`docwatch`** — a separate CLI binary: an in-doc agent orchestrator that
  watches a folder of documents and dispatches an agent when a trigger tag
  appears. See [docwatch](#docwatch) below.

## Build

```sh
cargo build --release
```

The binaries are written to `target/release/varde-docs` and
`target/release/docwatch`.

## Usage

```sh
varde-docs concept create --bundle <dir> <slug>      # reads document from stdin
varde-docs concept create --bundle <dir> --file <path>
varde-docs concept show --bundle <dir> <slug> [--frontmatter-only] [--json]
varde-docs concept update --bundle <dir> <slug> --expected-version <hash> [--file <path>] [--json]
varde-docs concept set-field --bundle <dir> <slug> <key> <value> --expected-version <hash> [--json]
varde-docs concept delete --bundle <dir> <slug> [--json]
varde-docs concept list [--bundle <dir>] [--vault personal|project] [--include-deprecated] [--json]
varde-docs concept search [--field key=value]... [--text <query>] [--limit <n>] [--bundle <dir>] [--vault personal|project] [--json]
varde-docs lint [--bundle <dir>] [--vault personal|project] [--okf] [--json]
```

`--bundle` points at a Knowledge Bundle root directory (holds Concept `.md`
files). Commands that read across vaults (`list`, `search`, `lint`) merge the
Personal Vault (`~/.varde-docs/`) with the Project Vault by default;
`--vault` narrows to one side. Writes (`update`, `set-field`) require
`--expected-version`, the OCC version hash last read via `show`, and reject
stale writes as a typed conflict rather than silently overwriting.

`concept search` combines two composable modes: `--field key=value`
(repeatable, exact frontmatter match with AND semantics) narrows first, and
`--text <query>` ranks the remainder with lexical full-text search across
bodies and frontmatter (`--limit` caps the ranked results). `lint` runs
spec-agnostic structural checks by default; `--okf` adds OKF v0.2 spec checks
(required `type`, the §5.4 `status` enum, §5/§10 structured-field shape, and
reserved bundle filenames), and neither ever blocks a create/update.

## docwatch

`docwatch` is a separate binary in the same workspace: an in-doc agent
orchestrator. It watches a registered folder of documents and, when an
unresolved trigger tag appears in a Markdown file, dispatches a coding agent
scoped to that file.

- **Trigger tags** — a line like `@c: <prompt>` (Claude) or `@cx: <prompt>`
  (Codex) queues a dispatch. Tags already followed by a `@c-reply:`/
  `@cx-reply:` marker or ending in ` [done]` are treated as resolved and
  skipped, as are tags inside fenced code blocks or blockquotes.
- **Change-scope guard** — each agent run is bracketed by a pre-run snapshot
  and a post-run diff of the repo root; any write the agent made outside the
  target document is reverted (files with pre-existing uncommitted changes
  are reported, never force-reset).
- **Background service** — `add` registers the folder in
  `~/Library/Application Support/docwatch/watchers.json` and installs a
  per-folder launchd job that runs the debounced watch loop; a heartbeat
  state file backs `status`.

```sh
docwatch add <folder>                 # register a folder and start watching
docwatch remove <folder|id>           # stop watching and unregister
docwatch list [--json]                # list registered watchers and run state
docwatch status <folder|id> [--json]  # show run state, queue, and recent log
docwatch logs <folder|id> [-n <N>]    # tail the watcher's log file
```

`add`/`remove`/`status`/`logs` accept either the folder path or the
registration id shown by `list` (useful once a folder has been deleted from
disk). launchd support is macOS-specific.
