# Triage scan findings

A `varde-code scan` finding is a **candidate**, not a verdict: the rule engine
cannot see context such as test fixtures, intentional cycles, public
re-exports, or trait boilerplate.

**Every finding ends fixed, not-real with a reason, or explicitly handed to
the user.** Group large result sets by rule; do not sample them. A rule that keeps
producing the same false positive is a rule problem: hand off its definition, false-positive examples, and intended matches to the
installed `varde-manage` skill for rule authoring. If that skill is unavailable,
continue triage and report the proposed rule change for setup; do not claim the
rule was corrected.

## Workflow

1. **Run the scan** without `--apply`:
   ```bash
   varde-code scan --json '{"repoRoot":"<repo>","severityThreshold":"error"}'
   ```
   (or `gateRules`; not both). Inspect `ok`, then `data.analysis.status` and
   `data.gate.status` independently; `ok: true` alone establishes neither. A
   nonzero exit means incomplete analysis or blocking findings. Resolve
   incomplete-analysis diagnostics before certifying a result, keeping the
   findings for triage meanwhile. Suppressions never clear diagnostics; exclude
   intentionally malformed fixtures with repository `.ignore` entries and
   document the scope.

   `data.findings` is bounded. While `data.findings_summary.truncated` is
   true, use `meta.toz.handle` with
   `data.guide.truncated.findings.toz_read` or search that handle when
   present. Otherwise re-run with `findingsOffset` =
   `data.guide.truncated.findings.next_offset`, or pass `fullFindings: true`.
   Triage every finding, never a truncated sample.
2. **Group findings by `rule_id`** (`data.findings_summary.by_rule` gives the
   counts) and handle one rule at a time; the first decision usually settles
   its group.
3. **Triage from the real code** at `location.file`:`location.span`, not from
   `message` or `evidence`, which come from the rule template — especially for
   `sql` rules that summarize several locations. Weigh:
   - `certainty` (pattern rules) as a hint only: a high-certainty match can
     still be a false positive when the pattern is too broad for the site.
   - The rule's actual definition, from
     `varde-code rules_list --json '{"repoRoot":"<repo>"}'`.
   - Context the rule cannot see: a credential that is a test fixture, an
     unused export that is a public re-export, a documented intentional cycle.

   A finding is not real only when the flagged code is not the problem the rule
   describes; a difficult fix is still a fix. Approximate clone bands and the
   persisted dependency graph are navigation signals: inspect their evidence
   before inferring a defect.
4. **Record each verdict as you go:** rule id, file:line, verdict, one-line
   reason.
5. **Fix.** Before using `scan --apply`, inspect and record a verdict for every
   rewrite-bearing finding from every loaded rule in the complete scan;
   `--apply` runs rewrite handling for every unsuppressed match of every
   rewrite rule in the run, regardless of `severityThreshold`. Suppress
   not-real findings with a reason (Suppressions section). Use `--apply` only
   when you intend to apply every remaining real rewrite finding; otherwise
   hand-edit selected findings in the file's style, using
   `data.rules.<rule_id>.remediation` as guidance.
   `--apply` skips modified, staged, or untracked files as `skipped-dirty`
   unless `--force`; suppression edits can make their files dirty. Tell the
   user when files are skipped, and use `--force` only with approval.
6. **Verify.** Re-run the scan: addressed findings are gone and nothing new
   appeared. Run the project's test or build command.
7. **Report every finding from step 1:** fixed ones with rule id and
   file:line, not-real ones with their reason, and anything left for the user.
   Persist each real or undecided finding left for the user in the standing
   review at `<working>/reviews/deferred/`. Create or update its `review.md`
   using `references/report-format.md`, with a SCAN category marked complete,
   and append findings to SCAN.md with the next unused `SCAN-NNN` ID. Include
   the scan finding's `id` in its Summary. Check existing SCAN findings for
   that same scan finding id before appending; update its evidence instead of
   making a duplicate on a repeat scan. If no id is present, match rule id,
   full location span, and the message resolved below. Do not persist findings
   already fixed or judged not-real.

   Map `data.findings[].severity` error→high, warning→medium, info→info;
   use `Label: triage`, `Disposition: blank`, and `Location` from
   `location.file` plus `location.span.start_line` when present. Put the rule
   id and message in `Summary`, using `data.findings[].message` when present
   (interpolated) or `data.rules[rule_id].message` otherwise (static), along
   with the reason it remains for the user. In `Solutions`, use
   `data.rules.<rule_id>.remediation` when it describes a concrete fix;
   otherwise name the fix found during triage.
   Preserve enough rule and location detail to distinguish findings when a
   single rule reports more than one issue in one file.
8. **Record lessons.** Record real obstacles through `varde-learn` and durable
   decisions through `varde-knowledge`; otherwise skip.

## Suppressions

For a justified exception, use a parser-recognized comment:
`varde-ignore-next-line rule-id -- reason` or
`varde-ignore-file rule-id -- reason`. Omitting the id suppresses every rule in
that scope. Suppressions remove findings before gating.
