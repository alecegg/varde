# Scan rules and scan findings

This file covers two `varde-code scan` tasks. Both use the rule definitions in
`references/scan-rule-format.md`.

| The request is | Section |
|---|---|
| Run a scan and decide what each finding actually means, then fix the real ones | **Triage scan findings** |
| Add a new check, or customize a seeded built-in | **Author a scan rule** |

If a scan repeats the same false positive, the rule needs work. Use the second
section instead of re-deciding the same finding.

## Triage scan findings

A `varde-code scan` finding is a **candidate**, not a verdict. The rule engine
flags patterns that are usually problems. It cannot see context such as test
fixtures, intentional cycles, public API re-exports, or trait boilerplate.

**Put every finding in one of two buckets: needs a fix, or not a real issue
with a stated reason.** Findings you have not checked are untriaged and
unfinished. Group large result sets by rule in step 3. Do not sample them.

The embedded built-ins currently contain 34 rules: 28 errors and 6 infos.
Their pattern declarations cover 35 rule/language pairs. These counts are
source facts, not scan-result counts.

### Workflow

1. **Choose the gate threshold.** Default `error` gates every error finding,
   including certified complexity, exact clones, and certified dependency
   policy. `warning` includes warnings; `info` includes advisories. Scan
   builds or refreshes its index automatically. `gateRules` accepts a nonempty
   array of active rule IDs and gates only those rules. It cannot be combined
   with `severityThreshold`; IDs must be unique. A `dependency-boundary` gate
   needs both nonempty normalized `source_prefix` and `target_prefix`
   configuration. Both blank leaves it inactive. One blank is invalid. The
   same validation rejects `gateRules` before index refresh or source writes.

2. **Run the scan.**
   ```bash
   varde-code scan --json '{"repoRoot":"<repo>"}'
   ```
   Inspect `ok`, then `data.gate.status`.
   `pass` exits zero; `fail` and `incomplete` exit nonzero.
   `ok: true` alone does not establish gate success.
   Resolve incomplete-scan diagnostics before certifying the result.
   Intentionally malformed fixtures can use repository `.ignore` exclusions.
   Document the resulting scope; suppressing findings never clears diagnostics.
   Keep findings for triage while repairing analysis failures.
   Do not pass `--apply` during initial triage.

3. **Group findings** by `rule_id`. Handle one rule at a time. Findings from
   one rule usually share a false-positive pattern, so the first triage decision
   often resolves the rest of that group.

4. **Triage each finding or group.** Read the actual code at
   `location.file`:`location.span`, or the indicated line, with the Read tool.
   Let the code decide, not `message` or `evidence`. Decide using:
   - **`certainty`** (pattern rules only, `High`/`Medium`/`Low` if present). Treat
     it as a hint, not a verdict. Read low-certainty findings closely. A
     high-certainty finding can still be a false positive when its pattern is
     too broad for the call site.
   - **The rule's intent.** Run `varde-code rules_list --json '{"repoRoot":"<repo>"}'`
     to inspect active patterns, SQL, thresholds, languages, and guidance.
     Listings include overrides and provenance. Judge the actual definition.
   - **Context the rule cannot see.** Examples include a hardcoded credential
     that is a test fixture, an unused export that is a public re-export, or a
     circular import documented as intentional. Human review supplies this
     context.
   - If you remain unsure, ask the user. Do not guess. Both false positives and
     missed bugs are costly.

5. **Record every classification as you go.** Keep a short list with rule id,
   file:line, verdict, and one-line reason. Include "not a real issue" verdicts.

6. **Fix the real findings.**
   - If the rule sets `rewrite` and the match is straightforward, prefer
     `varde-code scan --apply --json '{"repoRoot":"<repo>"}'` for that rule's
     findings. It applies the same transform consistently and requires a clean
     git tree. Add `--force` only when the user explicitly approves overriding
     that check, and say so.
   - Otherwise fix the code by hand with Edit. Use
     `agent_instructions`/`remediation` as guidance, not as text to paste.
     Verify that the fix addresses the flagged code.
   - Group fixes for the same rule. Re-read surrounding code before editing so
     each fix matches the file's existing style.

7. **Verify.** Re-run `varde-code scan --json '{"repoRoot":"<repo>"}'` after fixes and confirm the addressed findings are gone and nothing new was introduced. If the project has a test/build command (check `AGENTS.md`/`CLAUDE.md`), run it to confirm the fixes didn't break anything.

8. **Report every scan finding.** Include fixed findings with rule id and
   file:line, findings judged not real issues with the reason from step 5, and
   anything left for the user to decide. Every finding from step 2 must appear.

### Gotchas

- All 21 extraction languages have certified complexity profiles.
  Syntax rules cover only their declared languages.
  `solid-lsp` and `solid-isp` remain informational. `fat-interface`,
  `too-many-interfaces`, and `deep-inheritance` are error rules. Exact clone
  and certified dependency rules are enforceable errors. Approximate clone
  bands and the persisted dependency graph remain navigation signals.
  Inspect their evidence before inferring defects or changing architecture.
- For justified exceptions, use parser-recognized suppression comments.
  `varde-ignore-next-line rule-id -- reason` suppresses the next line.
  `varde-ignore-file rule-id -- reason` suppresses that file.
  Omitted identifiers suppress all rules in that scope.
  Suppressions remove findings before gating, never analysis diagnostics.
- `scan --apply` only touches findings whose rule has a `rewrite` template.
  Applied findings receive `rewrite_status`; skipped rewrites remain unresolved.
  Incomplete scans skip all rewrites. Rerun after repairing diagnostics.
- `scan --apply` refuses files with uncommitted changes unless `--force` is
  passed. Tell the user about this safety gate. Do not use `--force` by default.
- A finding's `evidence` and `message` come from the rule template. They do not
  prove correctness. Read the real code before deciding real or false positive,
  especially for `sql` rules summarizing multiple locations.
- If one rule repeatedly produces the same not-real-issue pattern, tighten the
  rule. See **Author a scan rule**. Tell the user instead of repeating the same
  judgment for every finding.
- Classify a finding as not real only when the flagged code is not the problem
  the rule describes. A difficult fix is still a fix.

## Author a scan rule

Develop the rule with the user. Do not generate it silently. Ask the user to
confirm thresholds, severity, and pattern shape.

### Workflow

1. **Understand the check.** Ask what the user wants flagged. Get concrete
   examples of code that SHOULD and should NOT match. Vague requests such as
   "catch bad error handling" need before-and-after examples first.

2. **Choose the rule kind.** Read `references/scan-rule-format.md` "Choosing
   pattern vs sql" for the decision criteria. Summary:
   - **`pattern`** — the check is a syntactic shape in one file/AST node (a specific call, a specific declaration form, a specific literal assignment). Runs per-file at scan time via the ast-grep-style matcher.
   - **`sql`** — the check is about aggregates, thresholds, or relationships across the persisted index (complexity, churn, fan-in/out, import graphs, cross-file joins). Runs as a read-only query against the built DB.
   - If the request needs both a structural shape and a cross-file relationship,
     prefer `sql` joining `entities`/`resolved_edges`. SQL has the full graph;
     the pattern engine sees one file at a time.

3. **For `pattern` rules**, draft the `pattern` string and `languages` list.
   Read `references/scan-rule-format.md` "Pattern syntax" for
   `$VAR`/`$$$VAR` captures, `constraints` regexes, and the optional `rewrite`
   template. Use
   `crates/varde-code/src/rules/builtin/hardcoded_credential_literal.toml` as
   the multi-pattern, multi-constraint example.

4. **For `sql` rules**, identify the tables and columns needed. Read
   `references/scan-rule-format.md` "SQL surface" for the schema, integer kind
   codes, and query conventions. The SELECT needs `file` and `line` columns;
   `:threshold_name` binds to `thresholds` or `strings`. Use
   `crates/varde-code/src/rules/builtin/complexity.toml` for aggregation and
   `circular_import.toml` for self-joins.

5. **Fill in every required and relevant optional field.** Read
   `references/scan-rule-format.md` "Rule fields" for types and semantics.
   Required fields are `id`, `kind`, `severity`, and `message`. Recommended
   fields are `name`, `description`, and `remediation`. Confirm `severity`
   (`error`/`warning`/`info`) and `thresholds`/`strings` defaults with the user.
   These values are the usual repo or user override settings.

6. **Write `[[rule.test]]` self-tests.** Add at least one positive and one
   negative case to every rule. Read `references/scan-rule-format.md` "Test
   entries" for each kind. Pattern rules use `valid`/`invalid` snippets and
   `expect_rewrite` when `rewrite` is set. SQL rules use an inline
   `[rule.test.fixture]` file tree and `expect_rows`.
   Verify positive and negative cases separately for every declared language.
   The standard runner unions matches across languages; one passing
   multi-language test does not certify every grammar.

7. **Pick the target file and scope.**
   - For a new standalone rule, use one file: either
     `<repo_root>/.varde-code/rules/<id>.toml` for this repository, or
     `~/.config/varde-code/rules/<id>.toml` for every repository. Ask when the
     scope is unclear. Default to repository scope for this codebase's rules.
   - To customize a seeded built-in, first run
     `varde-code rules_seed --json '{"repoRoot":"<repo>"}'`. This writes
     editable copies into `.varde-code/rules/`. Edit the seeded file in place,
     keeping its `id`. A matching repo or user file silently overrides the
     embedded built-in. No separate override mechanism exists.

8. **Validate.**
   ```bash
   varde-code test --json '{"rulesDir":"<dir-containing-the-toml>"}'
   ```
   This exits non-zero for any failing `[[rule.test]]` case. Fix failures and rerun
   until clean. Then confirm that the rule loads with the expected provenance:
   ```bash
   varde-code rules_list --json '{"repoRoot":"<repo_root>"}'
   ```
   Check the new or edited rule's `"source"` field (`custom`, `override`, or
   `builtin`) against the expected scope.

9. **Dry-run against real code.** For `sql` rules, this is optional but
   recommended. Run `varde-code scan --json '{"repoRoot":"<repo>"}'`.
   The scan refreshes its index automatically. Check for false positives
   in this repository and confirm the rule catches the cases from step 1.

### Gotchas

- `pattern` rules are language-agnostic by default. They match every file whose
  parse succeeds. Set `languages` for language-specific rules. Otherwise a
  JavaScript-shaped pattern silently does nothing on Python files.
- Regex `constraints` use Rust `regex`. Lookaheads and lookbehinds are not
  supported. Anchor with `^...$` for whole-capture matches. See the
  credential-literal built-in comments for the false-positive risk.
- SQL rule queries must alias `file` as the source path and `line` as a
  one-based line number in the SELECT. `Finding` rendering reads these aliases.
  Use `1 AS line` when the check has no natural line.
- `thresholds` and `strings` keys bind as named SQL parameters such as `:key`.
  An unused declared key is dead. A `:name` without a matching declaration
  fails at scan time, not load time.
- `fix` and `rewrite` differ. `fix` is informational remediation text. A
  `rewrite` is a live meta-variable template applied by `scan --apply` for
  pattern rules. Set it only for safe automatic fixes. Every `$VAR` in it must
  appear in `pattern`; otherwise the loader rejects the rule.
- One rule pack can contain multiple `[[rule]]` entries. Group closely related
  checks, such as assignment and declaration forms, in one file. Follow the
  built-in pack convention.
