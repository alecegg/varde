# Triage scan findings

A `varde-code scan` finding is a **candidate**, not a verdict: the rule engine
cannot see context. **Report every finding: fixed (rule id, file:line),
not-real with a reason, or explicitly handed to the user;** never triage a
sample.

A rule that keeps producing the same false positive is a rule problem: hand
its definition, false-positive examples, and intended matches to the installed
`varde-manage` skill. Without that skill, report the proposed rule change and
do not claim the rule was corrected.

## Workflow

Unless a caller's gate covers this work, initialize the
`references/review-gates.md` subject and pass its `start` checkpoint before
the first fix or suppression edit (step 5); after step 6, finish its final
review and `complete` checkpoint before reporting.

1. **Run the scan** without `--apply`, with every finding:
   ```bash
   varde-code scan --json '{"repoRoot":"<repo>","severityThreshold":"error","fullFindings":true}'
   ```
   On `index_missing` or `index_stale`, a coordinator applies the varde-code
   skill's Index readiness and Fallback, then retries; a worker, or a
   coordinator whose `watch --ensure` fails, reports the scan as unavailable.
   Check `ok`, `data.analysis.status`, and `data.gate.status` independently.
   Resolve incomplete-analysis diagnostics before certifying a result:
   suppressions never clear them, so exclude intentionally malformed fixtures
   with repository `.ignore` entries and document the scope.
2. **Group findings by `rule_id`** (`data.findings_summary.by_rule` has the
   counts); the first decision usually settles its group.
3. **Triage from the real code** at `location.file`:`location.span`;
   `message` and `evidence` are rule-template text. Weigh the rule's definition
   (`varde-code rules_list --json '{"repoRoot":"<repo>"}'`) and context it
   cannot see (test fixtures, public re-exports, documented intentional
   cycles); `certainty`, clone bands, and the graph are only hints. Not real
   means the flagged code is not the problem the rule describes; a hard fix is
   still a fix.
4. **Record each verdict as you go:** rule id, file:line, verdict, one-line
   reason.
5. **Fix** real findings by hand in the file's style, guided by
   `data.rules.<rule_id>.remediation`, and suppress not-real ones with a
   reason (Suppressions). Use the `--apply` flag only to apply every
   remaining real rewrite finding after recording a verdict for each: it rewrites every
   unsuppressed match of every rewrite rule in the run, regardless of
   `severityThreshold`. It skips modified, staged, or untracked files
   (suppression edits count) as `skipped-dirty`; tell the user which, and use
   the `--force` flag only with approval.
6. **Verify.** Re-run the scan (addressed findings gone, nothing new) and the
   project's test or build command.
7. **Persist** each real or undecided finding left for the user, per
   `## Persist leftover findings`.

## Persist leftover findings

Use the standing review at `<working>/reviews/deferred/`; never persist fixed
or not-real findings. Create or update its `review.md` per
`references/report-format.md` with a SCAN category marked complete, and append
to SCAN.md with the next unused `SCAN-NNN` ID.

- **Repeat scans:** match an existing finding by the scan finding's `id`
  (kept in its Summary), else by rule id, full location span, and resolved
  message; update its evidence instead of appending a duplicate.
- **Fields:** severity error→high only for findings confirmed real (code-confirmed),
  undecided errors cap at medium, warning→medium, info→info;
  `Label: triage`; `Disposition: blank`; `Location` from `location.file` plus
  `location.span.start_line` when present.
- **Summary:** the scan finding `id`, rule id, message
  (`data.findings[].message`, else the static `data.rules[rule_id].message`),
  the reason it remains for the user, and enough location detail to tell apart
  several findings of one rule in one file.
- **Solutions:** `data.rules.<rule_id>.remediation` when it describes a
  concrete fix; otherwise the fix found during triage.

## Suppressions

For a justified exception, use a parser-recognized comment:
`varde-ignore-next-line rule-id -- reason` or
`varde-ignore-file rule-id -- reason`. Omitting the id suppresses every rule in
that scope.
