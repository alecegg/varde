# Patterns Evaluation

Shared procedure for checking code against `memory-bank/knowledge/pattern/`.

Use this reference from any skill that needs to compare existing code with
project patterns. Do not restate these rules inline.

## Inputs

- `repo_root`: current repository root
- `target_files`: existing files to inspect
- `mode`: either `review` or `drift`

## Preconditions

Check whether `memory-bank/knowledge/pattern/` exists on disk.

If the caller requires patterns, treat a missing directory as a hard stop.
If the caller treats patterns as optional, skip pattern evaluation when the
directory is missing.

## Procedure

1. Load `memory-bank/knowledge/pattern/`.
2. For each pattern file, read each file in `target_files` and compare it
   against the pattern manually — naming, import ordering, test file
   location, function signature shape, comment style, script invocation,
   and any other observable convention the pattern describes.
3. Treat only concrete contradictions found by this manual comparison as
   findings.
4. When in doubt, do not flag.

## Review mode

Use `review` mode when producing a normal `/varde-review` report.

For each concrete violation, write a finding immediately. Use the Finding
format defined in `FINDING-FORMAT.md`.

## Drift mode

Use `drift` mode before task execution.

Only inspect files the task already modifies, and only if they exist on disk.
Do not inspect files listed only under `creates`.

For each concrete contradiction, report:

```text
Patterns drift detected in <filename>:
- PATTERNS.md says: <entry>
- Observed: <what the file actually does>
```

After reporting all drift findings, invoke `/varde-knowledge` to write or update the
relevant `pattern`/`decision` note and reconcile the project patterns before execution
continues.
