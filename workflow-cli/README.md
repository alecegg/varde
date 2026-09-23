# varde-workflow

OKF (Open Knowledge Format) knowledge CLI. Lives in the [varde](../) monorepo as
the `workflow-cli` module (its own Cargo workspace).

Designed from two references, neither copied wholesale:

- **A prior generic knowledge/OKF implementation** — generic Concept CRUD, OCC
  version-checked writes, bundle validation, `note_show`/`docs_search`-style
  retrieval.
- **[pi-llm-wiki](https://github.com/zosmaai/pi-llm-wiki)** — personal + project
  vault layering, four-layer raw-source/source-page/canonical-page/meta
  pipeline, contradiction-aware lint.

## Status

Pre-alpha. Varde skills use this CLI for workflow mutations.
Read-only skill operations may degrade visibly when unavailable.

## Scope

- Generic OKF bundle/note operations: create, read, search, version-checked
  writes, validation, cleanup/lint
- Personal + project knowledge layering (see pi-llm-wiki's vault model)
- Contradiction-aware lint
- Versioned workflow artifact inspection and validation
- Explicit legacy migration and staged-write recovery
- Declarative workflow schemas, readiness, and transitions


## Workspace layout

A Rust workspace (`Cargo.toml`) with three crates:

- **`okf-core`** — library implementing OKF v0.2 Concept/Bundle CRUD, OCC
  version checks, vault layering, and `lint`.
- **`varde-workflow`** — the CLI binary (`clap`-based) that wraps `okf-core`.
- **`docwatch`** — a separate CLI binary: an in-doc agent orchestrator that
  watches a folder of documents and dispatches an agent when a trigger tag
  appears. See [docwatch](#docwatch) below.

## Build

```sh
cargo build --release
```

The binaries are written to `target/release/varde-workflow` and
`target/release/docwatch`.

## Usage

```sh
varde-workflow concept create --bundle <dir> <slug>      # reads document from stdin
varde-workflow concept create --bundle <dir> --file <path>
varde-workflow concept show --bundle <dir> <slug> [--frontmatter-only] [--json]
varde-workflow concept update --bundle <dir> <slug> --expected-version <hash> [--file <path>] [--json]
varde-workflow concept set-field --bundle <dir> <slug> <key> <value> --expected-version <hash> [--json]
varde-workflow concept delete --bundle <dir> <slug> [--json]
varde-workflow concept map --bundle <dir> [--json]
varde-workflow concept list [--bundle <dir>] [--vault personal|project] [--include-deprecated] [--limit <n>] [--offset <n>] [--all] [--json]
varde-workflow concept search [--field key=value]... [--text <query>] [--limit <n>] [--bundle <dir>] [--vault personal|project] [--json]
varde-workflow lint [--bundle <dir>] [--vault personal|project] [--okf] [--limit <n>] [--offset <n>] [--all] [--json]
varde-workflow inspect <artifact> [--json]
varde-workflow validate <artifact> [--json]
varde-workflow migrate <artifact> [--apply] [--json]
varde-workflow recover [--root <dir>] [--json]
varde-workflow graph <plan> [--limit <n>] [--offset <n>] [--all] [--json]
varde-workflow readiness <plan> [--json]
varde-workflow transition <artifact> <state> [--json]
varde-workflow conclude <plan> [--json]
varde-workflow conclusion-status <plan> [--json]
varde-workflow conclusion-retry <plan> [--json]
varde-workflow conclusion-action <plan> <reflection|friction|handoff> [--output <path>] [--failed] [--json]
varde-workflow paths [--project <root>] [--json]
varde-workflow paths set [--project <root> | --default] [--working <dir>] [--knowledge <dir>] [--json]
varde-workflow paths unset [--project <root> | --default] [--working] [--knowledge] [--json]
```

`--bundle` points at a Knowledge Bundle root directory (holds Concept `.md`
files). Commands that read across vaults (`list`, `search`, `lint`) merge the
Personal Vault (`~/.varde-workflow/`) with the Project Vault by default;
`--vault` narrows to one side. Writes (`update`, `set-field`) require
`--expected-version`, the OCC version hash last read via `show`, and reject
stale writes as a typed conflict rather than silently overwriting.

Bundle roots and their directory ancestors require trusted ownership.
Slug validation rejects traversal and existing symlink escapes. These
checks cannot prevent concurrent replacement by an untrusted actor.

`concept search` combines two composable modes: `--field key=value`
(repeatable, exact frontmatter match with AND semantics) narrows first, and
`--text <query>` ranks the remainder with lexical full-text search across
bodies and frontmatter (`--limit` caps the ranked results). `lint` runs
spec-agnostic structural checks by default; `--okf` adds OKF v0.2 spec checks
(required `type`, the §5.4 `status` enum, §5/§10 structured-field shape, and
reserved bundle filenames), and neither ever blocks a create/update.
List, lint, and graph outputs return at most 100 records per collection.
Use `--offset` for the next page or `--all` explicitly. JSON output uses
the shared `{schema_version, ok, outcome, data, meta}` envelope. Failures
store their typed error under `data.error`.

## Memory locations

Working memory (`memory-bank/working/`: plans, handoffs, reviews) and
knowledge memory (`memory-bank/knowledge/`: durable notes, specs, contracts)
default to the project tree. `paths` shows where both resolve for a project;
`paths set` redirects either one, for a single project root or for every
project (`--default`). The setting is user-scoped — it lives in
`$XDG_CONFIG_HOME/varde/paths.toml` (default `~/.config/varde/paths.toml`),
never inside a repository, because which folder holds a person's memory is a
machine choice rather than project history:

```toml
[default]                          # optional; every project
working = "~/varde-memory/{project}/working"

[project."/Users/me/src/app"]      # keyed by canonical project root
knowledge = "/Volumes/notes/app/knowledge"
```

Values expand a leading `~` and `{project}` (the root's directory name);
relative values resolve against the project root. Precedence per directory:
`VARDE_WORKING_DIR` / `VARDE_KNOWLEDGE_DIR` → `[project."…"]` → `[default]` →
built-in. `VARDE_CONFIG_DIR` relocates the config file itself.

`conclude`, `conclusion-*`, `recover`, and the schema override honour the
resolved directories: a plan may live in a redirected working directory and
its contracts, conclusions, and promotions land in the redirected knowledge
directory. The journal and lock stay in the project root.

## Workflow artifact kernel

Versioned artifacts declare these frontmatter fields:

- `schema_version`, currently `1`.
- `artifact_type` and stable `id` strings.
- Optional `status` plus required `relationships`.
- Required `provenance` describing the artifact source.

`inspect` returns the resolved envelope and content revision.
Legacy documents receive deterministic, read-only derived envelopes.
Their output sets `legacy` and `migration_required` to `true`.

`validate` reports deterministic field-level diagnostics without writes.
Valid direct edits advance the content revision automatically.
Invalid direct edits preserve every source byte unchanged.
The CLI never repairs or migrates content automatically.

`migrate` previews the complete structural rewrite by default.
Only `--apply` authorizes the rewrite. Mutation commands reject
legacy documents and return the same migration preview first.

Mutations stage content beside its target before committing.
A versioned journal records source and target hashes.
`recover` completes interrupted writes exactly once under locking.
This provides recoverability, not filesystem-wide atomicity.

Every `--json` response uses envelope schema version `1`.
Success places command payloads beneath `data`.
Failures include stable `error.code` and `error.message` fields.
Human-readable output remains separate from machine output.

## Workflow schemas

Built-in schema version `1` defines plan and task states.
Projects may add artifact types through this committed file (under the
resolved knowledge directory, by default):

```text
memory-bank/knowledge/workflow/schema.yml
```

Each addition declares states, initial state, completion states,
and allowed transitions. Project schemas cannot replace core types.

`graph` resolves sibling plan dependencies from `depends_on`.
Its output contains sorted nodes, edges, and blockers.
`readiness` reports root blockers and currently available actions.
Dependency blockers retain only the `blocked` action.

`transition` validates the current state and dependency readiness.
Rejected transitions preserve every source byte unchanged.
Accepted transitions use the recoverable staged-write journal.

## Contracts and conclusion

Plans declare contract deltas through `contract_deltas`.
Each path is relative to the plan directory.
Versioned delta frontmatter names its capability and source plan.

Delta bodies use three typed operation sections:

```markdown
## ADDED
### Requirement: stable-id

## MODIFIED
### Requirement: existing-id

## REMOVED
- retired-id
```

Existing contracts require their current OCC `base_revision`.
Merged contracts live under `memory-bank/knowledge/contracts/`.

Plans list affected domains through `observed_specs`.
Conclusion rejects stale source or aggregate hashes.
The documentation workflow regenerates stale semantic content first.

Accepted review candidates use `promotion_candidates` paths.
Their provenance fields remain searchable after promotion.

`conclude` stages contracts, promotions, conclusions, and plan status.
Its transaction journal supports idempotent partial-commit recovery.
Unchecked acceptance criteria stop conclusion before any write.

Qualitative actions follow the committed mechanical transaction.
Their status remains visible through `conclusion-status`.
`conclusion-retry` resets failed actions without duplicating outputs.
`conclusion-action` records each result idempotently.

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
`list --json` and `status --json` use the shared versioned JSON envelope.
Status includes the latest dispatch failure when one exists.
