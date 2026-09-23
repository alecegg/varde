---
type: spec
status: active
title: "Rule autofix/rewrite"
related:
  - "reference/pattern-rule-engine"
  - "reference/rule-pack-format"
  - "reference/scan-cli-reference"
---

# Rule autofix/rewrite

Pattern rules can carry a `rewrite` template that mechanically rewrites
matched source spans when `scan` runs with `--apply`. This is the codemod
counterpart to the `fix` field: `fix` is free-text remediation guidance for
an agent (informational only, never applied), while `rewrite` is a
meta-variable template that `scan --apply` substitutes and writes to disk.

Rewrite is **pattern rules only** — SQL rules keep `fix` as guidance text
and never gain mechanical rewrites (their findings are not anchored to a
single source span).

## `rewrite` TOML field

Sibling to `pattern`, `message`, and `fix` on a pattern rule:

```toml
[[definition/rule]]
id = "log-to-info"
kind = "pattern"
severity = "warning"
message = "use console.info"
pattern = "console.log($MSG)"
rewrite = "console.info($MSG)"
```

- Syntax: the same `$VAR` / `$$$VAR` token syntax as `pattern`.
  `$VAR` substitutes the single matched capture's text; `$$$VAR` joins the
  variadic capture's bound node texts (no separator, same binding semantics
  as `collect_captures`/`bind_sequence` in `find_pattern.rs`).
- Load-time validation: every `$VAR`/`$$$VAR` token in `rewrite` must name
  a capture declared in `pattern` (token-name comparison — either sigil
  form satisfies it). A rewrite referencing an undeclared capture rejects
  the rule at load as a skip-and-report `Diagnostic` naming the capture.
- A rule without `rewrite` behaves exactly as before; a rewrite-bearing
  rule run without `--apply` is read-only.

## `scan --apply` / `--force`

```text
varde-code scan --json '{repoRoot, apply?, force?}' [--apply] [--force]
```

- `--apply` (or JSON `apply: true`): mechanically apply every matching,
  non-overlapping rewrite to disk. **Default is off** — a scan without it
  stays read-only: matches reported, nothing written.
- `--force` (or JSON `force: true`): with `--apply`, also write files that
  have uncommitted git changes. Without `--force`, dirty files are skipped
  as `skipped-dirty`. The flag is inert without `--apply`.
- An explicit JSON `apply`/`force` field is honored as-is; a passed CLI
  flag overrides it.

### Git gating

Per file, the git work tree gates the write: a clean (tracked, unmodified)
file is written; a dirty file — modified, staged, or untracked (including
git-ignored) — is skipped as `skipped-dirty` unless `--force`. The check is
per-file — other clean files in the same run are still applied. Target files
are resolved to canonical absolute paths before the check, so a relative
`repoRoot` gates exactly like an absolute one, and symlinked entries gate
on their own path while the rewrite lands on the link's real target.

Failure semantics:

- **Outside any git repo (or no `git` binary):** treated as clean — there is
  no git state to be undone against.
- **Git repo present but unreadable** (corrupt index, unreadable `.git`):
  every file is treated as dirty and skipped — failure-closed, never a
  silently ungated write.

### Overlap handling

Multiple rewrite matches in one file (from one rule or several) are
planned in a single pass, sorted by byte span. First-sorted wins; a later
match whose span overlaps an applied one is skipped and reported as
`skipped-overlap` — never applied, never a crash. Adjacent spans
(`[0,5)` then `[5,10)`) do not overlap and both apply.

### Atomic writes

Each file write is atomic: content is written to a temp file in the same
directory, then renamed over the original — no partial writes on crash
mid-`--apply`. The original file's permission bits are preserved across the
swap (an executable stays executable; a read-only file stays read-only).
Content outside matched/rewritten spans is preserved byte-exact; source
must be UTF-8 (already implied by tree-sitter parsing). A symlinked entry
is rewritten through the link: the real target's content is replaced and
the symlink itself is left in place (never silently de-symlinked).

## Output envelope

`--apply` reuses the existing scan JSON envelope — one shape, no second
schema. On top of the usual `findings` / `diagnostics`:

- Each pattern-rule finding whose rule carries a `rewrite` template gains a
  `rewrite_status` field set to one of:

  | value | meaning |
  |---|---|
  | `applied` | the matched span was replaced and the file written |
  | `skipped-dirty` | the file has uncommitted git changes and `--force` was not passed |
  | `skipped-overlap` | the match's span overlapped an earlier-applied span in the same file |
  | `skipped-conflict` | unreadable file, non-UTF-8-boundary span, or write failure |

- Findings with no applicable rewrite — SQL-rule findings, pattern rules
  without `rewrite`, and every finding in a non-`--apply` run — omit the
  field entirely (never `null`), keeping their exact old JSON shape.
- A top-level `rewrite_summary` object counts findings per status, using
  the same kebab-case status names, present only in `--apply` runs:

  ```json
  {"ok": true, "data": {
    "findings": [{"id": "…", "rule_id": "log-to-info", "rewrite_status": "applied", …}],
    "rewrite_summary": {"applied": 2, "skipped-dirty": 1}
  }}
  ```

## Exit code

`--apply` keeps the existing severity-gating convention, applied-aware: a
finding whose `rewrite_status` is `applied` is **resolved** and does not
trip the gate; every other finding (skipped-dirty/overlap/conflict, or any
finding without a rewrite status) gates exactly as before — the process
exits non-zero when an error-severity finding remains unresolved at/above
`severityThreshold` (default `error`). Non-`--apply` runs emit no
`rewrite_status`, so their exit behavior is unchanged.

## Out of scope

- Interactive per-match confirm mode (`--interactive`) — separate plan.
- SQL-rule autofix — SQL rules keep `fix` as guidance text only.
- A dedicated dry-run diff-preview UI — plain `scan` without `--apply` is
  the read-only preview.
- Multi-file/cross-file rewrites or coordinated multi-match edits.
- New tree-sitter language grammars.
- Editor/LSP integration.
