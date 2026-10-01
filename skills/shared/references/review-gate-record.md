# Reviewer evidence record

Reuse the same reviewer agent for a subject's pre-edit and implementation
phases, continuing its own context rather than starting a fresh one.

1. Take the id from initialization at `data.subject.subject_id`.
2. Resolve code-answerable questions yourself.
3. Inspect the subject at the current phase; copy `data.version` and
   `data.record_template`:

   ```sh
   varde-workflow review inspect --subject <subject-id> --phase <pre-edit|implementation> --json
   ```

4. `data.record_template` is `EvidenceRecord`'s exact shape, with
   `schema_version`, for this phase. Fill every remaining placeholder from your
   own assessment (`implementation_review_required` and `tier_confirmed` are
   JSON booleans); never default approval or the final-review decision. Write
   the filled record in the configured working store, outside source scope and
   never as the CLI-owned `pre-edit.json`, `implementation.json`, or
   `subject.json` — a report or coordinator-written approval is insufficient.
   An implementation record requires `coverage: "entire-subject-change"`, a
   non-empty `change_fingerprint`, and `tier_confirmed`.
5. Submit it (a pre-edit verdict before any implementation edit):

   ```sh
   varde-workflow review record --subject <subject-id> --expected-version <data.version> --file <reviewer-record.json> --json
   ```

Verdict rules:

- Behavior changes default to a failing test before implementation unless you
  approve a concrete alternative with its rationale and expected result.
  Documentation and packaging use structural or smoke checks.
- Set `implementation_review_required` true whenever `structural_risk` is
  above low/none; the CLI rejects non-low risk marked false.

Review every current subject change, including external artifacts, and record
the inspected change fingerprint. `tier_confirmed` judges `data.subject.tier`
(from `scripts/risk-tier.py`) against what you observed: `false` contradicts
the computed tier and blocks `complete` on its own, regardless of verdict.

## Low tier lightweight checks

For low tier code routed here from `review-gates.md` §5, check:

- the diff stays within the approved scope
- verification results match the expected results
- no behavior change beyond the approved outcome
