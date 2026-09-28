# varde-learn

`varde-learn` runs skill trigger and output evaluations and maintains a global
friction store.

## Install

```sh
cargo install --path crates/varde-learn
```

Or run `varde sync` from the repository root once this module is wired in.

## Evaluations

```sh
varde-learn eval trigger <skill-name> <queries.json> --harness {claude,codex,opencode} [--runs N] [--skill-path PATH]
varde-learn eval output <skill-dir> [--harness {codex,claude}] [--model MODEL] [--judge-model MODEL] [--runs N] [--iteration N] [--workspace DIR] [--eval ID]... [--timeout-seconds N] [--sandbox-dir DIR] [--no-baseline]
```

Output evaluations default to the official Codex CLI with `gpt-6-luna`. The
judge uses the same harness and model unless `--judge-model` overrides it.
Use `--harness claude` explicitly for Claude evaluations; without `--model`,
Claude uses its own default. A missing client or unavailable model fails the
run; the runner never falls back to another harness or model. Authentication
stays in the official client.

```sh
varde-learn eval output skills/varde-change --eval 3 --no-baseline --runs 1
varde-learn eval output skills/varde-change --harness claude --model sonnet --eval 3 --no-baseline
```

Each run uses a fresh disposable sandbox. Codex evaluation isolates personal
configuration, instruction files, and discovered skills from the candidate
snapshot. The Codex judge runs read-only. Preserve the raw event trace when checking
review provenance: a prose claim of independent review is not execution evidence.
Results establish behavior only for the selected harness/model. Usage metadata
may report token counts without dollar cost; missing cost is not zero cost.

Every eval launches one or more billed harness sessions; usage and charges
scale with `--runs`. Codex trigger evaluation uses a substring proxy because
Codex has no documented skill-invocation event. Run `varde-learn eval --help`
for details.

## Session diagnosis

`diagnose inspect` reads bounded local Codex, Claude, or OpenCode session
evidence without starting another harness client or opening the friction
store. `diagnose capture` records a reviewed event in that store. Choose
exactly one live selector and an explicit harness:

```sh
varde-learn diagnose inspect --harness codex --session <THREAD_ID> \
  --snapshot-out <new-private-path>/bundle.json --json

varde-learn diagnose inspect --harness claude --path <TRANSCRIPT.jsonl> --json
varde-learn diagnose inspect --harness opencode --session <SESSION_ID> --json
```

`--current`, `--session`, and `--path` are mutually exclusive. `--current`
requires verified harness context; OpenCode currently returns an unavailable
result for `--current`. The CLI does not infer current identity from the newest
file or database row. Check `data.overlap` (`current`, `not_current`,
or `unknown`) and `data.coverage` before analysis. A current-session alias or
unknown overlap requires an independent analyst, including when the target was
specified by ID or path. Current analysis uses an explicit pre-orchestration
anchor in `--cutoff-anchor`; without a verified cutoff, report incomplete
coverage. See the `varde-learn` skill's `references/diagnose.md` for the bounded
handoff, report template, and capture procedure.

`--snapshot-out` writes a new bounded normalized bundle and refuses to replace
an existing path. Save its `data.snapshot.digest`, and page the same frozen
bundle with `--snapshot-in <bundle.json> --offset <N> --limit <N> --json`.
`--limit` is 1 to 1,000, default 100. Inspect returns source and session
identity, verified children, record anchors, overlap, coverage warnings, and
page metadata. Its snapshot digest detects edits to the bundle; it does not
authenticate its contents. Limits include 16 MiB per source, 32 MiB per
family, 256 KiB per record, 10,000 records, 32 linked children plus the
selected root (up to 33 sessions), 5,000 discovery entries, and a 2 MiB
snapshot. Incomplete tails, malformed or unsupported
records, and discovery limits remain visible as partial coverage.
Multiple Codex rollouts identifying the same linked child also make coverage
partial; ambiguous child branches are omitted, with a warning.

Capture one reviewed incident from a strict JSON file:

```sh
varde-learn diagnose capture --file <incident.json> --json
```

The file carries the snapshot path and digest, canonical session ID, one
inspect record's source anchor, one incident kind (`failed-tool`,
`repeated-work`, or `workflow-deviation`), one existing item ID or new item
fields, and concise observed evidence. Unknown fields are rejected; the file
is limited to 64 KiB and evidence to 8 KiB. Capture records an occurrence and
does not change item status. Its result reports `created` or `already-recorded`
with item and occurrence IDs, original event time and cwd, and repository/HEAD
fields that this implementation leaves null rather than inferring from the
current checkout. Incident identity is separate from the snapshot digest or
report path. It uses a verified native event ID or an independently revalidated
append-stable JSONL line position and digest; uncertain or inherited identity
stays report-only.

Diagnosis reports stay under the configured working store until explicitly
removed. Reports and bundles can contain private source excerpts and paths;
review them before sharing. Diagnosis is separate from evaluations, which
still require explicit approval before any billed harness session.

## Friction store

The friction store is global to the user, not scoped to the current project.
It uses a SQLite database named `learn.db`. The store directory resolves in
this order:

1. `VARDE_LEARN_STORE`
2. `[default].learn` in `config.toml`
3. `learn/` under the varde config directory

The config directory is `VARDE_CONFIG_DIR`, then `$XDG_CONFIG_HOME/varde`,
then `~/.config/varde`. Use `varde-workflow paths set --learn <directory>`
to set `[default].learn`; `varde-workflow paths --json` reports its resolved
path and source. A leading `~` expands, and relative paths resolve from the
current directory.

Keep the live database local and outside Git repositories. The CLI refuses a
store path inside a Git worktree or repository. Avoid cloud-syncing the live
SQLite database; Markdown export/import moves friction items and their
occurrence/status history, but omits the adoption ledger, its item links,
target-file/commit metadata, stored eval JSON, and recurrence attribution.
Exports can contain private evidence, so review them before sharing or
committing.

Store schema 3 adds optional versioned incident provenance for historical
diagnosis occurrences. Migration preserves existing items and occurrences
without inventing provenance for them. The `varde-friction-item` version 1
Markdown export includes provenance when present; import validates and keeps
it, while legacy Markdown imports remain unprovenanced.

```sh
printf '%s\n' 'The check omitted a required path.' | \
  varde-learn friction add --source varde-change --title "Missing path guidance" --target skills/example/SKILL.md --json
printf '%s\n' 'Seen again after the latest edit.' | varde-learn friction add --item 42

varde-learn friction list --repo /path/to/project --status open --source varde-change --limit 100 --json
varde-learn friction show 42 --limit 100 --json
varde-learn friction set-status 42 resolved --reason "The instructions now name the required path."
```

New items are scoped to the current repository by default; use `--global` to
leave the repository scope empty. `--source` accepts a skill or tool name.
`friction add` reads evidence from stdin. To record another occurrence, use
`--item <ID>` without the create-only options.

`friction list` filters by `--status` (`open`, `resolved`, `promoted`, or
`archived`), exact `--source`, `--repo <ROOT>` or `--global`, and case-insensitive
literal `--text` in titles or evidence. `--repo` and `--global` cannot be
combined. `friction set-status` requires `--reason` and records every update
in status history, including a repeat of the current status.

List, show, and import results are paged. They default to 100 rows and accept
`--offset` and `--limit` (1 to 1000). Show uses the same offset and limit for
occurrences and status history. With `--json`, use `meta.next_offset` and
`meta.truncated` to continue until all pages are read. Export includes complete
history and is not paged.

## Adoption ledger

After applying an approved change, record it against its source items:

```sh
varde-learn adopt record --items 42,43 --summary "Clarify store path resolution" \
  --files "skills/varde-learn/SKILL.md,skills/varde-learn/references/distill.md" \
  --commit abc123 --eval-before before/benchmark.json --eval-after after/benchmark.json --json
```

`--items` and `--files` accept comma-separated values. The optional eval flags
take paths to benchmark JSON files; the CLI validates and stores their contents,
not the paths. Pass eval files only after their runs were separately approved
and completed; this command does not run evaluations. Recording an adoption,
linking its items, promoting them, and adding status history happen in one
transaction. Schema 2 forward-migrates
schema-1 stores while preserving existing friction data; a newer unsupported
schema is rejected.

Check later occurrences with `varde-learn adopt recurrence --json`. Each row is
a historical occurrence strictly later than its latest preceding adoption; it
does not prove the issue is still present and never triggers a revert. Supported
fixed timestamps beginning with `YYYY-MM-DD` are compared by SQLite; date-only
values compare at midnight UTC, and parseable timezone offsets compare as
instants. Relative values such as `now`, and other invalid or unsupported
timestamps, are omitted and counted in `meta.skipped_invalid_timestamps`.
Results default to 100 rows and accept `--offset` and `--limit` (1 to 1000);
follow `meta.next_offset` while `meta.truncated` is true.

## Import and export

Import is manual; it does not edit or remove the Markdown source files. For
legacy notes, first preview the files in the old friction directory, such as
`<working>/friction`:

```sh
varde-learn friction import /path/to/working/friction --repo /path/to/project --dry-run --json
```

If the report is correct, repeat without `--dry-run` to import. The required
`--repo` associates legacy occurrences with a repository. Dry-run validates
the source and configured store path but does not create or change the store.
Malformed or unsupported Markdown files are reported as skipped. Re-imports
skip slugs already present.

Export every item, including its occurrences and status history, to a new
directory with `varde-learn friction export <directory>`. Export files use the
versioned `varde-friction-item` Markdown format; import accepts that format as
well as legacy files with `type: friction` or `type: friction-item`. Use a new
directory for each export: the command preserves unrelated files and refuses
to overwrite an existing item path. This transfer contains friction items and
their occurrence/status history only; adoption records, their item links,
target-file/commit metadata, stored eval JSON, and recurrence attribution are
not included.

Add `--json` to friction commands for a versioned JSON envelope. On errors,
JSON details go to stderr and the command exits nonzero. Store path checks run
`git`; in a restrictive sandbox, allow that check and use a writable store
directory outside the checkout.

## Build and test

```sh
cargo build --workspace
cargo test --workspace
```

### Per-case environment

An output case in `evals/evals.json` may include an `env` object of string values.
Keys must be valid shell environment identifiers; `EVAL_*` keys and NUL values
are rejected before sessions launch. `{sandbox}` expands to that run's fresh
absolute sandbox directory; other braces remain literal. The same overrides
apply to setup, the evaluated client, and deterministic verification. Other
inherited variables, including client authentication, remain available. The
judge does not receive case overrides. Cases without `env` retain their current
environment behavior.

For isolated Varde fixture storage, use:

```json
"env": {
  "VARDE_CONFIG_DIR": "{sandbox}/.varde-eval-config",
  "VARDE_WORKING_DIR": "{sandbox}/memory-bank/working",
  "VARDE_KNOWLEDGE_DIR": "{sandbox}/memory-bank/knowledge",
  "VARDE_LEARN_STORE": "{sandbox}/.varde-eval-learn"
}
```
