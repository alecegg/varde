# Scan rules and scan findings

Both halves of this file are `varde-code scan` work over the same rule
definitions in `references/scan-rule-format.md`.

| The request is | Section |
|---|---|
| Run a scan and decide what each finding actually means, then fix the real ones | **Triage scan findings** |
| Add a new check, or customize a seeded built-in | **Author a scan rule** |

A scan that turns up the same false positive over and over is a rule problem,
not a triage problem — cross over to the second section rather than re-deciding
the same finding.

## Triage scan findings

A `varde-code scan` finding is a **candidate**, not a verdict — the rule engine
flags patterns that are usually a problem, but it cannot see the context a
human/agent pass can (test fixtures, intentional cycles, public API re-exports,
trait-mandated boilerplate).

**Every finding lands in exactly one of two buckets: needs a fix, or not a real
issue with a stated reason.** Those two are the whole space. A finding you
haven't looked at is untriaged, and an untriaged finding is unfinished work —
which is what makes a large finding count a grouping problem (step 3) rather
than grounds for sampling.

### Workflow

1. **Ensure a fresh index.** Run `varde-code build --json '{"repoRoot":"<repo>"}'` if the repo hasn't been built/indexed recently (or the user says code changed since the last scan). Skip if they confirm the index is current.

2. **Run the scan.**
   ```bash
   varde-code scan --json '{"repoRoot":"<repo>"}'
   ```
   Do not pass `--apply` at this stage — triage before touching any files.

3. **Group findings** by `rule_id`. Handle one rule at a time rather than one finding at a time — findings from the same rule usually share the same false-positive pattern, so the first triage decision often resolves the rest of that group at once.

4. **Triage each finding/group.** For each, read the actual code at `location.file`:`location.span` (or the line indicated) with the Read tool — the code decides, not `message`/`evidence`. Decide using:
   - **`certainty`** (pattern rules only, `High`/`Medium`/`Low` if present) — a hint, not a verdict. Low-certainty findings deserve closer reading; high-certainty ones can still be false positives if the rule's pattern is too broad for this call site.
   - **The rule's own intent** — read the rule definition (`varde-code rules list --json '{"repoRoot":"<repo>"}'` to locate it, then read the `.toml`) to understand what it's actually guarding against, so you're judging against intent rather than guessing from the message string.
   - **Context the rule can't see** — e.g. a "hardcoded credential" match that's actually a test fixture, an "unused export" that's a public API re-export, a "circular import" that's a documented intentional cycle. This is exactly what a human/agent pass adds over the static rule.
   - When genuinely unsure, ask the user rather than guessing — false-positive triage is a judgment call, and a wrong call in either direction (suppressing a real bug, or "fixing" correct code) is costly.

5. **Record every classification as you go** — a short running list: rule id, file:line, verdict, one-line reason. The "not a real issue" verdicts are part of the deliverable too.

6. **Fix the real findings.**
   - If the rule sets `rewrite` and the finding is a straightforward pattern match, prefer `varde-code scan --apply --json '{"repoRoot":"<repo>"}'` for that rule's findings rather than hand-editing — it's the same transform, applied consistently, and gated on a clean git tree (add `--force` only if the user explicitly wants to override the dirty-tree check, and say so).
   - Otherwise fix by hand with Edit, following `agent_instructions`/`remediation` from the finding as a starting point, not a script to paste verbatim — verify the fix actually addresses the flagged code.
   - Group fixes for the same rule together; re-read surrounding code before editing so the fix fits the file's existing style.

7. **Verify.** Re-run `varde-code scan --json '{"repoRoot":"<repo>"}'` after fixes and confirm the addressed findings are gone and nothing new was introduced. If the project has a test/build command (check `AGENTS.md`/`CLAUDE.md`), run it to confirm the fixes didn't break anything.

8. **Report a summary covering every finding from the scan**, not just the ones fixed: findings fixed (rule id + file:line), findings judged not a real issue (with the one-line reason from step 5), and anything left for the user to decide. Every finding from step 2 appears somewhere in that summary.

### Gotchas

- `scan --apply` only touches findings whose rule has a `rewrite` template; it silently skips (with `rewrite_status`) everything else — don't assume `--apply` alone resolves a rule group.
- `scan --apply` refuses to touch files with uncommitted changes unless `--force` is passed (dirty-tree safety gate) — surface this to the user rather than reaching for `--force` by default.
- A finding's `evidence`/`message` is generated from the rule template, not a proof of correctness — always read the real code before deciding real vs. false positive, especially for `sql` rules where the message may summarize an aggregate across multiple locations.
- If the same not-a-real-issue pattern recurs across many findings from one rule, that's a signal the rule itself may need tightening (see **Author a scan rule** below) rather than something to triage finding-by-finding forever — flag this to the user instead of repeatedly making the same judgment call.
- The bar for "not a real issue" is that the flagged code is not the problem the rule describes. An inconvenient fix is still a fix.

## Author a scan rule

Walk through the format collaboratively with the user rather than silently
generating a file. Thresholds, severity, and pattern shape are all judgment
calls for the user to confirm.

### Workflow

1. **Understand the check.** Ask the user what they want flagged, with a concrete example of code that SHOULD and should NOT match. Vague requests ("catch bad error handling") need a concrete before/after example before you can pick a rule type.

2. **Choose the rule kind.** See `references/scan-rule-format.md` "Choosing pattern vs sql" for the decision criteria. Summary:
   - **`pattern`** — the check is a syntactic shape in one file/AST node (a specific call, a specific declaration form, a specific literal assignment). Runs per-file at scan time via the ast-grep-style matcher.
   - **`sql`** — the check is about aggregates, thresholds, or relationships across the persisted index (complexity, churn, fan-in/out, import graphs, cross-file joins). Runs as a read-only query against the built DB.
   - If the request needs both a structural shape AND a cross-file relationship, prefer `sql` joining `entities`/`resolved_edges` — the SQL engine has the full graph; the pattern engine only sees one file at a time.

3. **For `pattern` rules** — draft the `pattern` string and `languages` list. Read `references/scan-rule-format.md` "Pattern syntax" for `$VAR`/`$$$VAR` capture syntax, `constraints` (per-capture regex), and optional `rewrite` template. Look at `crates/varde-code/src/rules/builtin/hardcoded_credential_literal.toml` for a worked multi-pattern, multi-constraint example.

4. **For `sql` rules** — identify which table(s)/columns the check needs. Read `references/scan-rule-format.md` "SQL surface" for the full schema (tables, columns, `entities.kind`/`resolved_edges.kind` integer codes) and query conventions (`file` + `line` columns required in the SELECT, `:threshold_name` binds to `thresholds`/`strings`). Look at `crates/varde-code/src/rules/builtin/complexity.toml` (aggregation) and `circular_import.toml` (self-join) for worked examples.

5. **Fill in every required and relevant optional field.** Full field reference (types, required/optional, semantics) in `references/scan-rule-format.md` "Rule fields". Required: `id`, `kind`, `severity`, `message`. Strongly recommended: `name`, `description`, `remediation`. Confirm `severity` (`error`/`warning`/`info`) and any `thresholds`/`strings` defaults with the user — these are the knobs a repo/user override would typically tune.

6. **Write `[[test]]` self-tests.** Every rule should ship at least one positive and one negative case. Format differs by kind — see `references/scan-rule-format.md` "Test entries". Pattern rules use `valid`/`invalid` snippet lists (plus `expect_rewrite` if `rewrite` is set); SQL rules use an inline `[test.fixture]` file tree plus `expect_rows`.

7. **Pick the target file and scope.**
   - New standalone custom rule → one file, either `<repo_root>/.varde-code/rules/<id>.toml` (repo-scoped, this project only) or `~/.config/varde-code/rules/<id>.toml` (user-scoped, applies everywhere). Ask which the user wants if unclear — default to repo-scoped for anything tied to this codebase's conventions.
   - Customizing a seeded built-in → the user should run `varde-code rules seed --json '{"repoRoot":"<repo>"}'` first (writes editable copies of every built-in pack into `.varde-code/rules/`), then edit the seeded file with the same `id` in place. A same-id file in repo/user scope silently overrides the embedded built-in — no separate "override" mechanism needed.

8. **Validate.**
   ```bash
   varde-code rules test --json '{"rulesDir":"<dir-containing-the-toml>"}'
   ```
   Exits non-zero on any failing `[[test]]` case; fix and re-run until clean. Then confirm the rule actually loads and shows correct provenance:
   ```bash
   varde-code rules list --json '{"repoRoot":"<repo_root>"}'
   ```
   Check the new/edited rule's `"source"` field (`custom`, `override`, or `builtin`) matches expectations.

9. **Dry-run against real code (optional but recommended for `sql` rules).** Run `varde-code build --json '{"repoRoot":"<repo>"}'` then `varde-code scan --json '{"repoRoot":"<repo>"}'` and check the new rule's findings look right — no false positives on the repo's own code, catches the cases the user described in step 1.

### Gotchas

- `pattern` rules are language-agnostic by default (match every file whose parse succeeds) unless `languages` is set — set it explicitly for anything language-specific, or a JS-shaped pattern will silently no-op (never crash) on Python files.
- Regex `constraints` use Rust `regex` — no lookaheads/lookbehinds. Anchor with `^...$` or matches become substring searches, not whole-capture matches (see the credential-literal built-in's comment block for why this matters for false positives).
- SQL rule queries must alias a `file` column (source path) and a `line` column (1-indexed) in the SELECT — these are what `Finding` rendering expects. `1 AS line` is fine when the check has no natural line (e.g. whole-file aggregates).
- `thresholds`/`strings` keys bind as named SQL parameters `:key` — a threshold declared but never referenced in `query` is dead; a `:name` referenced in `query` but missing from `thresholds`/`strings` fails at scan time, not load time.
- `fix`/`rewrite` are different: `fix` is free-text remediation guidance (always informational). `rewrite` is a live meta-variable template applied when `scan --apply` runs (pattern rules only) — only set it if the fix is safe to auto-apply, and validate every `$VAR` in it appears in `pattern` (the loader rejects `rewrite` referencing an unknown capture).
- One rule pack file can hold multiple `[[rule]]` entries — group closely related checks (e.g. multiple pattern shapes for the same concept, like the credential-literal assignment vs. declaration split) in one file rather than one-rule-per-file, matching the built-in packs' convention.
