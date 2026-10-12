# varde-doc

The `varde-doc` package checks agent-facing Markdown through the unified
`varde` CLI: `varde doc lint` for prose layout, `varde doc frontmatter` for
`SKILL.md` frontmatter, and `varde doc flow` for how a skill loads its files.

## Install

```sh
cd clis && cargo install --path varde --locked --force --target-dir target
```

The same installation provides every Varde module command.

## Lint

```sh
varde doc lint <path>... [--json]
```

A directory expands to `SKILL.md` plus `references/**/*.md`; a file is checked
as given. The checks cover long prose units, inline lists, long sections, prose
share, and layout problems.

| Exit | Meaning |
|---|---|
| 0 | No errors; warnings may be listed |
| 1 | At least one error |
| 2 | Bad input: a missing path or no Markdown found |

Text output prints one line per finding and a summary line. With `--json`, exit
0 prints a success envelope whose `data.findings` lists the warnings. Exit 1
prints a negative-result envelope (`ok: false`) with every finding under
`data.error.details.findings`. Exit 2 prints a tool-error envelope to stderr.

## Frontmatter

```sh
varde doc frontmatter <path>... [--json]
```

Each path is a skill directory, a `SKILL.md`, or a directory of skill
directories (searched one level deep). The checks follow the agentskills.io
spec: valid YAML without duplicate keys; `name` (at most 64 characters,
lowercase alphanumerics and single hyphens, equal to the directory name);
`description` (required, at most 1024 characters, one double-quoted physical
line); optional `compatibility` (at most 500 characters), `metadata` (string to
string map) and `allowed-tools` (string). Beyond the spec, the optional
`requires` and `recommends` keys are flow lists of sibling skill directory
names (`requires: [varde-code]`): each name must exist and must not be
`varde-manage`, and `requires` must resolve without an unknown name or a cycle.
Unknown top-level keys and bodies past 500 lines are warnings.

| Exit | Meaning |
|---|---|
| 0 | Every skill passed; warnings may be listed |
| 1 | At least one skill failed |
| 2 | Bad input: a missing path or no `SKILL.md` found |

Text output prints `OK` or `FAIL` and the path per skill, then its errors and
warnings. With `--json`, exit 0 prints a success envelope with `data.results`
(`path`, `ok`, `errors`, `warnings` per skill). Exit 1 prints a negative-result
envelope with the same list under `data.error.details.results`. Exit 2 prints a
tool-error envelope to stderr.

YAML is parsed as 1.2, so 1.1-only scalars such as `yes` stay strings. The
divergences from the retired Python script are listed at the top of
`crates/varde-doc/src/frontmatter.rs`. They include: a tab after `:` is
accepted; `1:` and `"1":` count as one key; `!!` tags are found by a raw scan.

## Flow

```sh
varde doc flow [--mermaid | --json | --write | --check] <skill-dir>...
```

Maps how each skill's Markdown files load one another: routes, estimated token
costs, structure measures and findings (the retired `skill-flow.py` ported to
Rust; its module docs in `crates/varde-doc/src/flow/mod.rs` list the edge kinds
and findings). The modes are mutually exclusive.

| Mode | Output |
|---|---|
| (none) | Text report per skill, blank-line separated |
| `--mermaid` | One Mermaid flowchart per skill |
| `--json` | Envelope whose `data` is the list of per-skill analyses |
| `--write` | Writes `FLOW.md` beside each `SKILL.md` |
| `--check` | Prints `stale: <path> (run varde doc flow --write <dir>)` for each missing or outdated `FLOW.md` |

| Exit | Meaning |
|---|---|
| 0 | Done; with `--check`, every `FLOW.md` is current |
| 1 | A skill has a missing-target finding (text, `--mermaid`, `--json`), or `--check` found a stale `FLOW.md` |
| 2 | Bad input: a directory without `SKILL.md`, an unwritable `FLOW.md`, or a usage error |

With `--json`, exit 0 prints a success envelope; exit 1 prints a
negative-result envelope with the list under `data.error.details`; exit 2
prints a tool-error envelope to stderr. The list matches the script's `--json`
output by value; serde_json writes non-ASCII text as-is where Python escapes
it. Text, `--mermaid` and the `FLOW.md` body match the script byte for byte;
the `FLOW.md` header names `varde doc flow --write` instead of the script.

### Ledger

```sh
varde doc flow ledger hash|validate|score|check <ledger.json> [--root DIR] [--route NAME] [--json]
```

Decision ledgers (the `ledger` half of the retired `skill-flow.py`) list a
procedure's decisions with cited source lines. Cyclomatic is 1 + the sum of
branch units; cognitive is the sum of units x (1 + depth). `--root` is where
source paths resolve (default: the Git top level).

| Action | Does |
|---|---|
| `score` | Prints scores per phase; `--route` keeps that route's phases (an unknown route exits 2) |
| `validate` | Prints one line per problem: duplicate ids, wrong units or depth, hash mismatches, missing files, unresolved local calls |
| `check` | Prints one line per decision whose cited lines changed, moved or vanished |
| `hash` | Rewrites the ledger in place with each decision's hash (exit 1 if cited lines are missing) |

`validate` and `check` exit 1 when they print anything. `hash` writes the
script's `json.dumps(indent=2)` bytes, including `\uXXXX` escapes for non-ASCII
text. With `--json`, `score` and the clean results print a success envelope;
findings print a negative-result envelope with the list under `data.error.details`.
`varde doc flow` with neither skill directories nor `ledger` is a usage error (exit 2).
