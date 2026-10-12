# varde-workflow

Markdown document and workflow management exposed through the unified `varde`
CLI. The `varde-workflow` and `varde-workflow-core` packages are members of the
workspace in [`clis/Cargo.toml`](../Cargo.toml).

Grew out of a prior generic knowledge-bundle implementation: Concept CRUD, OCC
version-checked writes, bundle validation, and search.

## Status

Pre-alpha. Varde skills use this CLI for workflow mutations.
Read-only skill operations may degrade visibly when unavailable.
`varde plan status` can append `stalled <elapsed>m` to a task row when its
validated worktree, task, and optional task note show no recent activity.
Configure the positive-minute threshold with `[orchestration] stall_minutes`
in `~/.config/varde/config.toml`; it defaults to `20`. Invalid values use the
default and print a notice. Status only reads this evidence.

## Scope

- Generic knowledge bundle/note operations: create, read, search, version-checked
  writes, validation, cleanup/lint
- Structural lint (broken links, malformed frontmatter; orphans and missing
  indexes as warnings)
- Versioned workflow artifact inspection and validation
- Declarative workflow schemas, readiness, and execution waves
- Task ownership checks (`owns` plus plan `shared:`)
- One review report per plan or change, gated by `plan conclude`


## Workspace layout

A workspace module with two packages:

- **`varde-workflow-core`** (`md-core/`) — library implementing Concept/Bundle CRUD, OCC
  version checks, project path resolution, and `lint`.
- **`varde-workflow`** — the `clap`-based workflow CLI package, routed by `varde`.

## Build

```sh
cd clis && cargo build -p varde-workflow --release --locked
```

The unified `varde` executable routes lifecycle commands under `varde plan`, knowledge-bundle commands under `varde knowledge`, and `paths`, `instructions` and session hooks under `varde setup`.

## Usage

```sh
varde knowledge concept create --bundle <dir> <slug>      # reads document from stdin
varde knowledge concept create --bundle <dir> --file <path>
varde knowledge concept show --bundle <dir> <slug> [--frontmatter-only] [--json]
varde knowledge concept update --bundle <dir> <slug> --expected-version <hash> [--file <path>] [--json]
varde knowledge concept set-field --bundle <dir> <slug> <key> <value> --expected-version <hash> [--json]
varde knowledge concept delete --bundle <dir> <slug> [--json]
varde knowledge concept map --bundle <dir> [--json]
varde knowledge concept list [--bundle <dir>] [--include-deprecated] [--limit <n>] [--offset <n>] [--all] [--json]
varde knowledge concept search [--field key=value]... [--text <query>] [--limit <n>] [--bundle <dir>] [--json]
varde knowledge lint [--bundle <dir>] [--require-index] [--limit <n>] [--offset <n>] [--all] [--json]
varde doc spec inventory --repository <root> --knowledge <dir> --working <dir> [--refresh] [--acknowledge-architecture-path <path>] [--json]
varde plan validate <artifact> [--json]
varde plan graph <plan> [--limit <n>] [--offset <n>] [--all] [--json]
varde plan check-task-ownership --task <file> --commit <ref> [--repo-root <dir>] [--json]
varde plan execution-wave <plan-dir> [--repo-root <dir>] [--max-workers <n>] [--json]
varde plan readiness <plan> [--json]
varde plan status [--json]
varde plan now <plan> <TEXT> [--json]
varde plan now <plan> --clear [--json]
varde msg send --from <name> --to <address> --kind <kind> [--notes <path>] <TEXT>
varde msg read [--as <address>] [--all] [--json]
varde plan conclude <dir> [--merged <rev>] [--repo <path>] [--json]
varde setup instructions install [--target <path>]... [--max-agents <n>] [--dry-run]
varde setup instructions targets
varde setup instructions remove [--dry-run]
varde setup paths [--project <root>] [--json]
varde setup paths set [--project <root> | --default] [--working <dir>] [--knowledge <dir>] [--toz <dir>] [--learn <dir>] [--json]
varde setup paths unset [--project <root> | --default] [--working] [--knowledge] [--toz] [--learn] [--json]
```

`check-task-ownership` audits one source commit against a task's `modifies`,
`creates`, and both rename endpoints. Paths use exact Git spelling; the task
file itself is excluded when it resolves inside the repository. Repository
root defaults to the current directory. Root commits include their files;
merge commits are rejected. Missing ownership fields or `kind: spike` skip
commit inspection; present empty lists still audit every changed source path.

Plain output is `{status, stray, declared, changed}` JSON. `--json` wraps the
same data in the shared success envelope, including a `stray` result. Exit 0
means `ok` or `skipped`; exit 2 means stray paths (also command-line syntax
errors); task, revision, Git, and merge errors exit 1 with typed errors in
JSON mode. The command writes no repository or workflow state.

`execution-wave` reads `<plan-dir>/tasks/*.md` and proposes an ordered wave
of ready tasks. The default width is `[orchestration] builders` (minimum 1);
`--max-workers` accepts any positive integer, and 0 is rejected with a hint to
omit the flag. Repository discovery uses Git; pass `--repo-root` when the plan
is outside a Git checkout.
Plain output is the scheduler JSON object (`schema_version: 3`); `--json`
places that object in the shared envelope's `data` field. Input errors exit
1, command-line syntax errors exit 2, and dependency cycles exit 3.

Writes, transitive code reach, and verification resources determine conflicts.
The command uses the installed `varde-code` through `PATH`, with bounded
read-only queries and Git basename fallback for successful empty graphs.
Failed queries exclude that task from parallel candidates; uncertain ownership
keeps the whole wave serial. With no parallel wave, the first eligible ready
task runs alone. Tasks mentioning another unfinished task's created or renamed
path are held pending an explicit dependency. Every nonempty wave selects
`worktree` mode, including a single task; an empty wave retains `single`.
It dispatches nothing, writes no workflow state, and starts no index or watcher.

Findings deferred to `<working>/reviews/deferred/<CATEGORY>.md` stay there; the
deferrer appends directly, and no CLI command moves them.

`--bundle` points at a Knowledge Bundle root directory (holds Concept `.md`
files); when omitted, `list`, `search`, and `lint` default to the project's
resolved `<knowledge>` directory (same resolution as `varde setup paths`).
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

## Instruction block

`varde setup sync` installs or refreshes the managed Varde block in configured global
instruction files. Pass one or more `--instructions-target <file>` values to
install the block at explicit targets. This block is
required: Varde will not work as designed until it is installed. Use one
canonical `AGENTS.md` in a standard global or personal Git-tracked location, then
symlink it into each harness.

```sh
varde setup instructions install --target <path>
varde setup instructions install --max-agents <n>
varde setup instructions targets
varde setup instructions remove
```

`--target` can be repeated and replaces the configured target list. Targets are
persisted, so `varde setup sync` refreshes them on later runs. `--max-agents`
persists the new cap and rewrites the blocks; after editing
`[orchestration].builders` by hand, rerun `varde setup sync`. `targets` prints the configured files, and `remove`
strips the managed block from each target and clears `[instructions].targets`.

### Presets and sync features

Sync derives instruction sections and hook features from the selected skills'
`requires` closure. With no saved selection, sync selects all skills.

#### Upgrade behavior

For configured instruction targets and synced harnesses, `workflow`, `full`,
and default all-skills installs retain orchestration. A hand-picked list without
`varde-change` drops orchestration and the inbox hook on the next sync.
Use `varde doc spec inventory` for domain spec inventory.

## Session-start hook

`varde hook session-start --harness claude|codex|opencode|pi` prints
session-start context for one harness. It runs the providers listed in
`~/.config/varde/config.toml` in order, and reports
a failed or timed-out provider as a notice in the context. It always exits 0.

```toml
[hooks.session_start]
providers = ["nav_map", "toz_note"]  # default
```

`nav_map` times out after five seconds. `toz_note` runs when no configured instruction target holds the managed block. Legacy `orchestration` entries are skipped. The orchestration
brief is in the managed Varde instruction block.

## Session notes

Post-tool-use providers default to `capture`, then `session_notes`; an
explicit provider list replaces that default. The `session_notes` provider
reads the latest bounded context sample and nudges once on each upward crossing
at or above the absolute token threshold. `[session].notes_at_tokens` defaults
to `250000`; set it to `0` to disable. Invalid values use the default with a
notice.

For one release, `context_handoff` remains an alias for `session_notes`, and
`[session].handoff_at_tokens` remains an alias for
`[session].notes_at_tokens`. The new provider and key take precedence when both
names are set. `varde plan watch --handoff <path>` also remains an alias for
`--notes`; aliases print a deprecation notice and are removed one release after
this rename ships.

The crossing state is stored per harness and session. It re-arms only after
usage drops below the threshold. Session start prints the validated session ID
and a stable reserved path under
`<working>/session-notes/`; the main agent creates or refreshes that note and
advises the user to compact. The hook never compacts automatically. Run
`varde setup migrate-session-notes` to move existing
`<working>/handoffs/<id>/handoff.md` notes without changing their contents.

`varde setup hooks install|remove` writes or removes the unified hook entries
(Claude `settings.json`, Codex `hooks.json`, opencode `plugin/varde.ts`, Pi
`extensions/varde.ts`). The installer accepts `--features change,toz,learn,code,knowledge`;
`varde setup sync` derives hook features from the selected skills and their
`requires` closure. Sync first retires the older per-feature
code, Toz and session hooks, including the legacy workflow session entries and
plugin files, then installs the unified hooks. For Codex it
also drops leftover `varde map nav_map` SessionStart entries from `hooks.json`.
The workflow crate no longer installs hooks.

### Child sessions

The brief is for main sessions; harnesses handle child sessions differently:

- **Claude Code:** subagents were verified not to receive the brief.
- **OpenCode v1:** the plugin skips child sessions (`Session.parentID`), as does the
  v2 plugin (`session.get`). Both bound the lookup at 2s and inject on failure.
- **Pi:** the extension skips sessions with no session file or with a
  `parentSession`. So `--no-session`, `/fork`, and `/clone` main sessions get
  no brief, and a persisted child of a `--no-session` main session does.
- **pi-subagents:** Varde's Pi agents use `prompt_mode: replace`, so they get
  no brief. Agents in `append` mode (for example its default
  `general-purpose`) inherit the parent's final system prompt, brief and toz
  note included, by that package's design.

## Memory locations

Working memory (plans, tasks, session notes, reviews) and knowledge memory
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
varde setup paths set --default --working '~/varde-memory/{project}/working'
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
env override and no built-in fallback in this crate — Toz resolves its own
default when the key is unset. `paths --json` reports it as `data.toz` /
`data.toz_source`, both `null` when unset. Unlike working/knowledge, toz
does not fall back to resolving a relative value against the project root:
after `~`/`{project}` expansion the `toz` value must be absolute, or toz
treats the key as unset and falls back to its own default store location.

An existing `paths.toml` remains readable until the first `paths` write
migrates its entries to `config.toml`.

`conclude`, `status`, and the schema override honour the resolved
directories: a plan may live in a redirected working directory and its review
report and plan files stay in that working directory. `--repo` names the
repository whose commits the review report's `head` must match.

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

Every `--json` response uses envelope schema version `1`.
Success places command payloads beneath `data`.
Failures include stable `error.code` and `error.message` fields.
Human-readable output remains separate from machine output.

## Workflow schemas

Built-in schema version `1` defines plan and task states.
Plan statuses are `backlog`, `active`, `blocked`, `cancelled`, `completed`;
task statuses are `todo`, `in_progress`, `blocked`, `done`.
Projects may add artifact types through this committed file (under the
resolved knowledge directory, by default):

```text
memory-bank/knowledge/workflow/schema.yml
```

Each addition declares states, initial state, completion states,
and allowed transitions. Project schemas cannot replace core types.

Plan `plan.md` frontmatter may add `shared: []` (paths any task may touch,
accepted by ownership checks), `reviewed_commit: <sha>`, and
`reviewed_on: <YYYY-MM-DD>` (recorded at Finalize; `status` reads them for its
advisory staleness notice).

`graph` resolves sibling plan dependencies from `depends_on`.
Its output contains sorted nodes, edges, and blockers.
`readiness` is read-only: a task is ready when its status is `todo` and every
`depends_on` task is `done`. `execution-wave` reports the ready tasks and
conflicts across `owns` patterns (glob intersection, ignoring `shared:`);
`check-task-ownership` accepts directories, globs, and exact files in `owns`
plus the plan's `shared:` paths on a candidate commit.

## Review report and conclusion

One independent review covers the whole diff of a plan or change since a fixed
commit and writes one `review.md` with a header naming `verdict` (`approved` or
`changes-requested`), `reviewer`, `base`, and `head`. A fixes-only re-review
answers behaviour-changing fixes (new findings block only at critical or high
severity); any other fix gets a header-only re-check that rewrites `head`.

`varde plan conclude <dir> [--merged <rev>] [--repo <path>]` is the only gate:
it exits 0 only when `<dir>/review.md` says `verdict: approved` and the merged
commit (default `HEAD`, override with `--merged`) equals `head`; otherwise it
exits 1 naming the verdict or both shas, or `review commit <sha> not found in
<repo>`. On success in a plan directory the plan's `status` becomes `completed`.

`varde plan status` and `varde plan now` stay advisory: they print one line per
plan when `git log <reviewed_commit>..HEAD` touches the plan's `owns` paths (or
`shared:` when a plan has no `owns`) or `reviewed_on` is over 7 days old, and
they never exit non-zero for it. An unknown `reviewed_commit` prints
`review commit <sha> not found in <repo>`.

`varde msg send` appends one message line to the per-machine inbox for a
recipient address; `varde msg read` prints a reader's unread messages and
advances its cursor, and `--all` prints every message without moving a
cursor. Non-main readers pass `--as`.

Migrated plan files keep validating through legacy-field tolerance:
`modifies`/`creates`/`renames`/`verification_resources` on tasks pass
`validate`, and the dropped `observed_specs` and `shape: group` fields are
ignored.

## Worktree wave execution

Each parallel task runs in its own worktree and branch created by
`scripts/worktree-wave.sh start`; a serial single writer may use the plan
worktree. `integrate` audits each worker commit with `check-task-ownership`,
merges workers in task order, runs one combined check, bisects a failure to the
culprit task (exit 5 with `culprit=`, `verified_prefix=`, and
`untouched_remainder=`), and fast-forwards the plan branch. `release` removes
the task and integration worktrees. Sync conflicts exit 3 naming the conflicting
paths; dirty, moved, detached, or missing checkouts exit 4. Workers never merge
or mutate plan state; the plan branch's owner holds both.
