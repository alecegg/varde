# Reviewer evidence record

Load before writing a record in either review phase. Inspect the subject at the
current phase; use returned `data.version`, `contract_fingerprint`, and
`baseline_id`. Initialization returns the id at `data.subject.subject_id`.
Write your own strict JSON and submit with `review record`; a report or
coordinator-written approval is insufficient. Keep records in the configured
working store outside source scope.

Pre-edit record (`schema_version: 1`; unknown fields are rejected):

```json
{
  "schema_version": 1,
  "subject_id": "<subject-id>",
  "phase": "pre-edit",
  "reviewer": { "identity": "<reviewer>", "provenance": "<harness/role>" },
  "verdict": "<approved-or-blocked>",
  "unresolved_choices": [],
  "contract_fingerprint": "<data.contract_fingerprint>",
  "baseline_id": "<data.baseline_id>",
  "verification_approach": "<approach>",
  "verification_rationale": "<why this verifies the plan>",
  "verification_expected_results": "<observable result>",
  "structural_risk": "<risk>",
  "structural_risk_rationale": "<why>",
  "implementation_review_required": "<true-or-false>",
  "rationale": "<review rationale>"
}
```

Replace placeholders with inspected values and your actual assessment; the
boolean placeholder becomes a JSON boolean. Do not default approval or the
final-review decision. Approval requires no unresolved choices. Non-low risk
requires `implementation_review_required: true`.

For phase `implementation`, use the same common fields, omit
`structural_risk`, `structural_risk_rationale`, and
`implementation_review_required`, then add:

```json
{
  "change_fingerprint": "<data.change_fingerprint>",
  "coverage": "entire-subject-change"
}
```

Review every current subject change, including external artifact entries;
record the inspected change fingerprint. A fingerprint binds evidence to
observed files; it does not establish correctness. After approval the
coordinator runs the complete checkpoint.
