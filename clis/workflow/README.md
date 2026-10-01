# varde-workflow

Markdown document and workflow management CLI. Lives in the [varde](../../) monorepo as
the `workflow` module (its own Cargo workspace).

Grew out of a prior generic knowledge-bundle implementation: Concept CRUD, OCC
version-checked writes, bundle validation, and search.

## Status

Pre-alpha. Varde skills use this CLI for workflow mutations.
Read-only skill operations may degrade visibly when unavailable.

## Scope

- Generic knowledge bundle/note operations: create, read, search, version-checked
  writes, validation, cleanup/lint
- Structural lint (broken links, malformed frontmatter; orphans and missing
  indexes as warnings)
- Versioned workflow artifact inspection and validation
- Staged-write recovery
- Declarative workflow schemas, readiness, and transitions
- Reviewer-written evidence and start/resume/completion checkpoints


## Workspace layout

A Rust workspace (`Cargo.toml`) with two crates:

- **`varde-workflow-core`** (`md-core/`) — library implementing Concept/Bundle CRUD, OCC
  version checks, project path resolution, and `lint`.
- **`varde-workflow`** — the CLI binary (`clap`-based) that wraps `varde-workflow-core`.

## Build

```sh
cargo build --release
```

The binary is written to `target/release/varde-workflow`.

## Usage

```sh
varde-workflow concept create --bundle <dir> <slug>      # reads document from stdin
varde-workflow concept create --bundle <dir> --file <path>
varde-workflow concept show --bundle <dir> <slug> [--frontmatter-only] [--json]
varde-workflow concept update --bundle <dir> <slug> --expected-version <hash> [--file <path>] [--json]
varde-workflow concept set-field --bundle <dir> <slug> <key> <value> --expected-version <hash> [--json]
varde-workflow concept delete --bundle <dir> <slug> [--json]
varde-workflow concept map --bundle <dir> [--json]
varde-workflow concept list [--bundle <dir>] [--include-deprecated] [--limit <n>] [--offset <n>] [--all] [--json]
varde-workflow concept search [--field key=value]... [--text <query>] [--limit <n>] [--bundle <dir>] [--json]
varde-workflow lint [--bundle <dir>] [--require-index] [--limit <n>] [--offset <n>] [--all] [--json]
varde-workflow spec inventory --repository <root> --knowledge <dir> --working <dir> [--refresh] [--acknowledge-architecture-path <path>] [--json]
varde-workflow validate <artifact> [--json]
varde-workflow recover [--root <dir>] [--json]
varde-workflow graph <plan> [--limit <n>] [--offset <n>] [--all] [--json]
varde-workflow readiness <plan> [--json]
varde-workflow transition <artifact> <state> [--json]
varde-workflow conclude <plan> [--json]
varde-workflow review init --plan <plan> --repository <root> (--scope <path> | --artifact <absolute-file>)... [--json]
varde-workflow review init --subject <id> --contract <file> --repository <root> (--scope <path> | --artifact <absolute-file>)... [--json]
varde-workflow review inspect --subject <id> --phase <phase> [--json]
varde-workflow review record --subject <id> --expected-version <revision> --file <record.json> [--json]
varde-workflow review check --subject <id> --checkpoint <checkpoint> [--json]
varde-workflow review bind-worktree --subject <id> --binding <id> --expected-version <version> --worktree <path> --scope <path> [--scope <path> ...] [--task <task.md>] [--json]
varde-workflow review check --subject <id> --repository <parent> --worktree <path> --binding <id> --checkpoint <start|resume> [--json]
varde-workflow review inspect-worktree --subject <id> --binding <id> [--json]
varde-workflow review release-worktree --subject <id> --binding <id> --expected-version <version> --commit <sha> [--json]
varde-workflow review abandon-worktree --subject <id> --binding <id> --expected-version <version> --reason <text> [--json]
varde-workflow review contract --subject <id> --expected-version <revision> --file <contract.json> [--json]
varde-workflow review expand --subject <id> --expected-version <revision> (--scope <path> | --artifact <absolute-file>)... [--json]
varde-workflow conclusion-status <plan> [--json]
varde-workflow conclusion-retry <plan> [--json]
varde-workflow conclusion-action <plan> <reflection|friction|handoff> [--output <path>] [--failed] [--json]
varde-workflow paths [--project <root>] [--json]
varde-workflow paths set [--project <root> | --default] [--working <dir>] [--knowledge <dir>] [--toz <dir>] [--learn <dir>] [--json]
varde-workflow paths unset [--project <root> | --default] [--working] [--knowledge] [--toz] [--learn] [--json]
```

`--bundle` points at a Knowledge Bundle root directory (holds Concept `.md`
files); when omitted, `list`, `search`, and `lint` default to the project's
resolved `<knowledge>` directory (same resolution as `varde-workflow paths`).
Writes (`update`, `set-field`) require
`--expected-version`, the OCC version hash last read via `show`, and reject
stale writes as a typed conflict rather than silently overwriting.

Bundle roots and their directory ancestors require trusted ownership.
Slug validation rejects traversal and existing symlink escapes. These
checks cannot prevent concurrent replacement by an untrusted actor.

`concept search` combines two composable modes: `--field key=value`
(repeatable, exact frontmatter match with AND semantics) narrows first, and
`--text <query>` ranks the remainder with lexical full-text search across
bodies and frontmatter (`--limit` caps the ranked results). `lint` runs
spec-agnostic structural checks, and neither ever blocks a create/update.
A `lint` orphaned Concept (zero incoming links) is a `Warning`: links from a
bundle's `index.md` count as incoming to their targets, but `index.md`
itself is never a Concept and is never checked for orphan status. Pass
`--require-index` to also flag, as a `Warning`, a directory with Concept
files but no `index.md`.
List, lint, and graph outputs return at most 100 records per collection.
Use `--offset` for the next page or `--all` explicitly. JSON output uses
the shared `{schema_version, ok, outcome, data, meta}` envelope. Failures
store their typed error under `data.error`.

`spec inventory` classifies domain specs against current nonignored source
paths and provenance. It caches verified results under the supplied working
directory, rechecks changed inputs before reusing unaffected domains, and
periodically performs full validation. `--refresh` forces a full check after
spec regeneration. Warm `unclassified_paths` lists changed paths outside domain
roots; full checks list all of them. An unknown new path outside architecture
roots yields `architecture_status: inspect` and appears in
`architecture_inspect_paths`. After inspecting an unrelated path,
`--acknowledge-architecture-path` records its current hash and clears that
status; a content change requires inspection again. Its cache is advisory;
`conclude` still validates source hashes and covered paths independently.

## Memory locations

Working memory (plans, tasks, handoffs, reviews, journals) and knowledge memory
(durable notes, specs, contracts) have built-in defaults in the project tree.
We recommend redirecting working memory outside source repositories to a shared
storage root with distinct project folders. Prefer a separate Git repository
or storage with version history; project knowledge can stay committed in its
source repository. `paths` shows their resolved locations and the global
friction store for a project;
`paths set` redirects either one, for a single project root or for every
project (`--default`). The friction store is always global: `--learn` sets or
unsets `[default].learn` even without `--default`, and cannot be combined with
`--project`. The setting is user-scoped — it lives in
`$XDG_CONFIG_HOME/varde/config.toml` (default `~/.config/varde/config.toml`),
never inside a repository, because which folder holds a person's memory is a
machine choice rather than project history:

```toml
[default]                          # optional; every project
working = "~/varde-memory/{project}/working"
learn = "~/varde-memory/learn"

[project."/Users/me/src/app"]      # keyed by canonical project root
knowledge = "/Volumes/notes/app/knowledge"
```

To configure the recommended shared working default:

```sh
varde-workflow paths set --default --working '~/varde-memory/{project}/working'
```

Changing paths does not migrate existing artifacts or create version history.
Manage migration and Git commits or storage history separately. Review private
evidence before committing or sharing working artifacts; the shared root is for
the user's projects and harnesses and need not be public or team-shared.

Linked Git worktrees share the main repository's working and knowledge memory,
including its project config entry. `paths --project <worktree>`, `paths set`,
and `paths unset` resolve to that repository. Legacy worktree-specific entries
are ignored; existing files and config entries are not moved or deleted.
For separate Git metadata, `core.worktree` must identify the main checkout
(relative paths resolve against the common Git directory). Without it, Git's
inventory supplies the metadata directory as the memory root because Git has
no record of the main checkout's location. Worktrees of a bare repository use
the bare repository as their memory root.

Working and knowledge values expand a leading `~` and `{project}` (the root's
directory name); relative values resolve against the project root. Precedence
per directory: `VARDE_WORKING_DIR` / `VARDE_KNOWLEDGE_DIR` → `[project."…"]` →
`[default]` → built-in. The learn store uses `VARDE_LEARN_STORE` →
`[default].learn` → `learn/` beside `config.toml`; any `learn` value in
`[project."…"]` is ignored. Learn paths expand a leading `~`; relative values
resolve against the current directory, matching `varde-learn`. `paths --json`
reports `learn` and `learn_source` (`env`, `default`, or `builtin`).
`VARDE_CONFIG_DIR` relocates the config file itself.

Existing environment and project overrides still take precedence over a new
default. Check `paths --json` for each affected project. Give same-named
repositories distinct project overrides so `{project}` does not merge their stores.

`config.toml` can also hold a `toz` key (`paths set --toz <dir>`), recording
where toz's output-capture store lives. Unlike working/knowledge it has no
env override and no built-in fallback in this crate — toz resolves its own
default when the key is unset. `paths --json` reports it as `data.toz` /
`data.toz_source`, both `null` when unset. Unlike working/knowledge, toz
does not fall back to resolving a relative value against the project root:
after `~`/`{project}` expansion the `toz` value must be absolute, or toz
treats the key as unset and falls back to its own default store location.

An existing `paths.toml` remains readable until the first `paths` write
migrates its entries to `config.toml`.

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

`validate` reports deterministic field-level diagnostics without writes,
including the resolved envelope and content revision on success.
Valid direct edits advance the content revision automatically.
Invalid direct edits preserve every source byte unchanged.
An artifact missing `schema_version` is a validation failure.

Mutations stage content beside its target before committing.
A versioned journal records source and target hashes.
`recover` completes interrupted writes exactly once under locking.
This provides recoverability, not filesystem-wide atomicity.
On Unix, journal-managed replacements preserve existing permission bits.
Stages are created with mode `0600` (subject to umask); new journal-managed
documents keep that private mode.

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

## Review evidence and gates

`review init` creates a local subject and immutable source baseline for a
persisted plan or bounded JSON contract. It requires the canonical repository
root and at least one repository-relative `--scope` or absolute external-file
`--artifact`. `review inspect` returns
the contract and baseline fingerprints, current change fingerprint, and an
OCC `version`. The independent reviewer writes evidence and submits it with
`review record --expected-version`; there is no coordinator approval flag.
Review evidence and baseline blobs live under the configured working store.

External documents, including files in external working memory, need explicit
file scopes. Artifact-only initialization and additive expansion use:

```bash
varde-workflow review init --subject <id> --contract <contract.json> --repository <root> --artifact <absolute-file> --json
varde-workflow review expand --subject <id> --expected-version <revision> --artifact <absolute-file> --json
```

Repeat or combine `--scope` and `--artifact`. Artifact scopes cover exact files,
including planned files whose ancestors do not exist yet. Directories, traversal,
symlink aliases (including ancestors), and Unix hard-linked files are rejected.
Use `--scope` for files inside the repository. Review evidence and generated
workflow state cannot be artifacts. External scopes use the same immutable
baselines, OCC and final fingerprint checks; they grant no task or worktree
ownership. Repository root `--scope .` never implicitly covers external files.

`review check` accepts `start`, `resume`, or `complete` and reports readiness,
typed blockers, and consumed evidence revisions. Missing, blocked, invalid,
stale-contract, and stale-change evidence rejects the checkpoint with exit
code 4; OCC conflicts exit 3. `readiness` exposes dependency-based
`planning_ready` separately from review-gated `implementation_ready`, so
approval gaps do not hide plans from planning but do prevent implementation.
Workflow transitions and `conclude` enforce the corresponding checkpoint
before their writes. Tasks inherit their parent plan's approval. A verified
task may finish while a required aggregate plan review is pending; the plan
may not complete until current full-subject implementation evidence passes.

Explicit worktree bindings inherit current parent approval for a declared source
scope while preserving ordinary subjects' exact checkout identity. Run
`bind-worktree` from the parent with its current pre-edit inspection version.
The linked worktree must be registered in the same Git repository, clean at the
parent HEAD, and within approved coverage without excluded paths. For plan
work, the parent plan must be active; `--task` names an original `in_progress`
task and its binding scope must match declared writes (both rename paths).
Standalone bounded work may omit `--task`. Changes to task ownership,
dependencies, verification or parent approval invalidate authorization.

Workers run the explicit binding `check` from their registered checkout, for
start/resume only. Their baseline and manifest are separate from the parent's.
Out-of-scope committed, unstaged and untracked changes reject the check. Workers
return evidence and source commits; the parent owns task transitions after
successful source integration. The integration checkout combines and verifies
source only. The parent then inspects each binding again and releases it using
that version and the integrated worker HEAD. Release verifies ancestry and
matching source content, archives evidence, and permits worktree cleanup.
Active bindings prevent parent completion. Aggregate implementation evidence
covers the current parent change plus archived authorization evidence; releasing
or changing bindings makes earlier final review stale. Ordinary linked-worktree
subjects remain independent, and unregistered access to parent evidence fails.

Every binding archive requires a fresh aggregate implementation record before
parent completion, even if the original pre-edit verdict was low risk.
`inspect-worktree` reports stale execution blockers alongside evidence and an
OCC version. After new independent parent approval, `release-worktree` may
archive integrated original-scope source without renewing obsolete task or
approval pins; start/resume still reject those pins. Original scope must remain
covered by current approval. If integration is abandoned or a worktree is
missing, use `abandon-worktree` with its inspection version and a concrete
reason. This requires an active, independently approved parent and archives
available evidence without deleting source, branch or worktree. It records
unavailable source explicitly, does not recreate missing directories, and
requires final aggregate review. A released or abandoned binding cannot be
reused for editing; new execution needs a fresh binding.


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
Merged contracts live under `../../memory-bank/knowledge/contracts/`.

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

Post-conclusion `--output` accepts descriptive labels and existing relative paths
unchanged. Absolute paths inside the configured stores or invoking checkout are
stored as `<working>/path`, `<knowledge>/path`, or `<repo>/path`. The deepest
matching root wins (working, knowledge, then checkout for ties). References must
have a nonempty suffix of normal path components. External absolute paths and
file URIs are rejected; use a portable description identifying an external source.
Unresolved or escaping symlinks and traversal are rejected before any update.

`conclusion-status` adds `output_references` for stored root references, with
`reference`, current resolved `path`, and `available`. Missing artifacts are
unavailable; resolution errors report a null path and an `error`. These values
are read-only status data, never stored in the document. Changing configured
stores changes resolution without rewriting references or copying their contents.
The referenced document remains authoritative; a missing private document on
another machine is reported unavailable.
