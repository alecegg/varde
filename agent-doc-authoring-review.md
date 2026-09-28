# varde-agent-doc-authoring adversarial review

Date: 2026-09-27. Origin: manual user request.
Scope: all 12 files under skills/varde-agent-doc-authoring, including the entry
point, five references, validator, eval configuration, two verification scripts,
and two fixtures. Reviewed the repository version containing the new Review
section. The installed copy still has the earlier workflow; installation was
not part of this review.

## Result and evidence

Seven findings, ranked by repair priority, all seven **Fixed**.
The primary review setup matches the requested audit questions and output rules.
No original findings remain open. Review-contract coverage has been authored; model behavior
remains untested.

Every inventory item was assessed for value versus tokens/time, concise accurate
wording, and readable structure. Evidence combines source inspection, an
independent full-scope audit, and targeted smoke checks. No model-driven eval
runs or tokenizer measurements were performed. Eval coverage gaps therefore do
not establish that the model would fail those behaviors.

Word baseline: entry point 505; references 1,520; validator 845; eval config and
verification scripts 1,304; fixtures 337. Total 4,511 words before review fixes.
After the initial fixes: 4,515 words (+4). The additions disambiguate a pointer
and prevent a crash; shortening was not their purpose. The user-approved layout
clarification reduces its reference from 186 to 182 words; current total is 4,511. Installed runtime material excludes
evals and fixtures (skills/install.sh prunes evals).

Follow-up coverage work adds two eval scripts and one shared fixture, bringing
the scope to 15 files and the word total at that stage to 5,242. Eval-only material
does not increase installed runtime loading.

The duplicate-key fix adds a SafeLoader subclass, documents the unique-key
boundary, and adds a persistent regression suite. Current scope: 16 files,
5,596 words. The added parsing logic is required to preserve valid merges and
aliases while rejecting explicit duplicates.

## Ranked findings

1. **Fixed: validator crashes when unknown YAML keys have different types.**
   Location: scripts/validate-frontmatter.py, unknown-field warning loop.
   Evidence: frontmatter containing unknown keys `1` and `extra` raised
   TypeError at `sorted(unknown)` and produced no promised JSON result.
   Benefit/cost: deterministic validation earns its execution cost; an uncaught
   exception defeats the warning path. A one-line correction is clearer and
   cheaper than adding general exception handling.

   - A. Sort by string representation, preserving unknown-field warnings. **Recommended and applied.**
   - B. Reject non-string top-level keys with structured validation errors.
   - C. Add an exception boundary that reports a generic validation failure.

   Changed to `sorted(unknown, key=str)`. Retest returned valid JSON with two
   warnings and exit 0. Invalid names still returned errors and exit 1; this
   skill's frontmatter passed. Independent implementation review passed.

2. **Fixed: workflow layout guidance conflicts with separate invocation flows.**
   Location: references/workflow-skills.md, Workflow and Reference fan-out;
   SKILL.md, task table and authoring steps.
   Evidence: the reference previously required “one numbered workflow” and one reference
   per step. The entry point intentionally separates authoring from reviewing,
   and authoring loads authoring.md and specification.md together.
   Benefit/cost: layout guidance improves navigation, but an absolute rule here
   can trigger unnecessary restructuring and undermine the requested design.
   The repeated file reads are small; runtime confusion has not been tested.

   - A. Define one workflow per invocation type and distinguish procedure ownership from supplementary requirements. **Recommended and applied (user choice 1).**
   - B. Merge authoring and specification into one authoring-phase reference.
   - C. Explicitly exempt this skill's layout from the reference's rule.

   Applied after the user selected option A. Each invocation type may have its
   own numbered workflow; steps have one primary procedure, inline or in a
   reference, with supplementary requirements loaded when needed. Short
   procedures and gates stay inline; branching detail belongs in its reference.
   Reference checks passed; the edited skill underwent a follow-up review.

3. **Fixed: eval coverage omitted the new review contract.**
   Location: evals/evals.json, especially eval 1.
   Evidence before additions: cases covered report-only audit, ungrounded authoring,
   and grounded release authoring. They did not assert three fix options plus a
   recommendation, default safe fixes with Fixed markers, or agent-initiated
   output without a newly required manual report.
   Benefit/cost: focused cases would protect the newly added branches. Running
   a broad model eval for every small change would be expensive; targeted cases
   should cover the actual contract.

   - A. Add option/recommendation assertions to eval 1 and separate safe-fix and agent-origin cases. **Recommended and applied (user choice 1).**
   - B. Add one comprehensive scenario covering all new branches.
   - C. Retain current cases and explicitly track the missing behavior coverage.

   Eval 1 now asserts three distinct options and a recommendation. Eval 4 tests
   manual review, default safe duplicate removal, Fixed reporting, saved report
   delivery, and captured independent review results. Eval 5 tests agent-origin
   report-only output with no report file and no target edits. The shared fixture
   contains one exact duplicate and a separate exact-version requirement.
   Mechanical checks require byte-exact removal and compare report artifacts
   against a pre-run Markdown hash snapshot. Eight positive/negative smoke cases
   passed; missing setup data also failed clearly. Model behavior is untested.
   Real safe-fix eval runs require independent-review-capable harness sessions;
   semantic outputs and gate traces must still be graded. Independent full
   doc-authoring review of the edited skill passed.

4. **Fixed: duplicate frontmatter keys silently overwrite earlier values.**
   Location: scripts/validate-frontmatter.py, yaml.safe_load.
   Evidence before the fix: a sample with two description keys returned ok=true and exit 0.
   Only the final value was validated. Different harness handling was not tested.
   Benefit/cost: rejecting ambiguity would strengthen the validator, but changes
   accepted input and needs parser-level tests. Its current field checks remain
   useful and concise.

   - A. Use a SafeLoader subclass that rejects duplicate mapping keys. **Recommended and applied (user choice 1).**
   - B. Add a separate duplicate-key lint for frontmatter.
   - C. Document and deliberately retain the current last-value behavior.

   Applied after user approval. A SafeLoader subclass checks explicit keys
   before merge flattening and raises a structured duplicate-key error with
   source marks. Per-loader tracking prevents inherited keys from being mistaken
   for duplicates when anchors are reused. Valid merges and explicit overrides
   retain SafeLoader results. Five duplicate subcases failed before the change;
   the five-method regression suite now passes, including nested/merge-source
   duplicates, unsafe tags, unhashable keys, mixed-key warnings, and real skill
   frontmatter. Independent implementation and doc-authoring review passed.

5. **Fixed: report verifier mistakes nested option numbering for inventory.**
   Location: evals/verify-self-audit.sh, check_report.
   Evidence before the fix: an empty report failed and a two-item inventory passed. A report
   with only one finding followed by indented options 1, 2, and 3 also passed,
   reporting three inventory entries. The script strips indentation before
   matching. It additionally checked only root-level Markdown, not a supplied
   subdirectory report path.
   Benefit/cost: the lightweight smoke check is useful, but currently overstates
   what its result proves. New option numbering makes the ambiguity more likely.

   - A. Recognize top-level finding sequences and supply an explicit report path when needed. **Recommended and applied (user approved both changes).**
   - B. Require a dedicated inventory section and parse only that section.
   - C. Keep the smoke check but label it as sequence detection, with semantic inventory validation elsewhere.

   The shell entry point now uses standard-library Python to count unindented
   finding lists, numbered headings, and inventory table rows. Nested options,
   indented code, block quotes, and fenced examples are ignored. An optional
   workspace-relative path selects one report, including a subfolder report;
   legacy callers still discover root-level Markdown. Eval 1 now requests
   reports/skill-review.md and uses a wrapper to select that exact path. The
   regression suite failed on five subcases before implementation and now passes
   eight methods covering supported formats, explicit selection, freshness,
   missing files, symlinks, path containment, and wrapper/assertion compatibility.
   It retains the minimum of two consecutive entries and still needs semantic
   grading to establish that numbered top-level prose is genuinely inventory.
   Independent implementation/doc-authoring review passed and was recorded for
   the complete change; the completion checkpoint returned ready with no blockers.

6. **Fixed: validation pointer no longer identifies a unique step.**
   Location: references/specification.md, Validation.
   Evidence: “see SKILL.md step 3” became ambiguous after several numbered
   sections were added.
   Benefit/cost: an exact section name prevents a navigation error with three
   extra words and no repeated command. No structural reorganization is needed.

   - A. Name “SKILL.md, Author or revise step 3.” **Recommended and applied.**
   - B. Link directly to the authoring heading.
   - C. Repeat the sandbox fallback in this reference.

   The pointer now names its section. Reference checks and independent review
   passed.

7. **Fixed: mandatory word measurements can add cost without useful evidence.**
   Location: references/reviewing.md, Token economy.
   Evidence before the fix: it required word counts and edit deltas without a materiality
   condition. A count does not explain a routing correction or catch a validator
   defect. Actual overhead across agent sessions was not measured.
   Benefit/cost: counts help assess substantial condensation and loading costs;
   for a tiny clarity fix, qualitative evidence is often more informative.

   - A. Require counts for substantial condensation or loading changes; otherwise explain the concrete benefit. **Recommended.**
   - B. Keep unconditional counts for consistency.
   - C. Remove measurement instructions and rely on qualitative judgment.

   Both baseline measurement and post-edit remeasurement now use the same
   substantive wording/loading condition. Small fixes require a brief concrete
   benefit instead of counts. The clarity and accuracy questions remain intact.
   Exact-condition checks, installed-reference checks, and diff checks passed.
   Runtime tests are unnecessary for this instruction-only clarification.
   Independent doc-authoring/implementation approval was recorded for the
   entire change; the completion checkpoint passed with no blockers.

## Retained inventory and cost judgments

| Item | Value, wording, and structure assessment |
|---|---|
| SKILL.md description and task dispatch | Concrete scope separates agent documents from user-facing docs. Three routes are readable. Review-first routing now points to the primary process. Retain. |
| Authoring steps 1–4 | Routing, grounded source loading, conditional frontmatter validation, and scoped final checks are useful. The final pass explicitly avoids accidentally launching a full audit. The global full-review requirement still applies before completion after editing a skill. Retain with the clarified per-invocation layout guidance. |
| Review inventory and three questions | Covers features, steps, flows, branches, instructions, all output types, references, scripts, templates, and evals. Explicit value/wording/structure questions are the requested review purpose. Retain. |
| Review evidence and supplementary loading | Locations, observed behavior, correctness/value distinction, and uncertainty prevent unsupported conclusions. Supplementary checklist loading is conditional; it no longer competes with the primary output protocol. Retain. |
| Review output branches | Priority ordering, options/recommendation, Fixed markers, report-only precedence, caller restrictions, edit gates, manual Markdown delivery, agent delivery, and delegated-user origin are explicit. Three options have a real report cost, but the user requested them; exempting retained items prevents padding. Retain with the added review-contract assertions and cases. |
| Gotchas | Self-contained references and real pointers protect installed usability. Stray closing-tag check is cheap, concrete, and scoped. Retain. |
| references/authoring.md | Grounded project rules, source-free interview branch, conditional reading, repeated-work scripts, and scope guidance provide useful defaults. Interview flow costs turns but avoids invented project policies. Retain. |
| references/review-gates.md | Pre-edit verdict, unresolved-choice handling, scope-change review, verification alternatives, implementation review, unavailable-review handling, fix verification, and stopping criteria are consequential branches. At 527 words it is costly, but conditional loading limits repeat cost. No safe deletion identified; local ownership preserves install independence. Retain. |
| references/reviewing.md | Applicability, loading, duplication, instruction quality, concise wording, and accuracy checks supply concrete scrutiny. Fan-out consolidation addresses structure rather than merely cutting words. Retain with conditional measurement guidance. |
| references/specification.md | Required/optional fields, naming, description constraints, positive trigger wording, and validator invocation are compact and actionable. Retain with fixed pointer. |
| references/workflow-skills.md | Dispatch, observable completion, conditional reference splitting, and gotchas improve ordered procedures. Retain with the clarified per-invocation workflows and supplementary loading. |
| Validator discovery and output | Direct file, skill directory, and installed-root discovery; missing-input handling; required and optional field checks; unknown-field warnings; body-budget warning; JSON/text rendering; and exit statuses earn deterministic execution cost. No broad exception-catching redesign needed. Retain with the mixed-key and duplicate-key corrections. |
| UniqueKeyLoader and evals/test-frontmatter-validator.py | Explicit-key checks precede recursive merge flattening; node tracking preserves reused anchors. Structured errors remain compatible with existing JSON output. Regression checks prove rejection and accepted-merge equivalence; justified logic and maintenance cost. Retain. |
| Eval 1 and varde-change fixture | Historical source copy explicitly limits cross-file evidence. Report-only override, routing analysis, inventory, economy, and manual report delivery remain useful. Fixture does not claim current varde-change behavior. Retain with the added review-contract assertions and cases. |
| Evals 4–5 and shared review-guidance fixture | Focused manual safe-fix and agent-origin cases isolate new branches. Immutable fixture preserves the exact-version instruction while making duplicate removal measurable. Required gates remain in force; no claim of model success. Retain. |
| setup-agent-review.sh and verify-review-branches.sh | Pre-run Markdown hashes distinguish existing artifacts from added/modified reports. Exact target-byte checks reject unchanged, missing, symlinked, or arbitrary rewritten outputs. Assertions match the runner schema and case IDs. Three new eval-only files add no installed loading cost. Retain. |
| Eval 2 | Source-free authoring case protects against fabricated project guidance and tests the bounded interview branch. No script is necessary for the semantic judgment. Retain. |
| Eval 3 and release-notes fixture | Grounded release authoring tests trigger wording, correction preservation, workflow ordering, output placement, and frontmatter. Short fixture provides sufficient concrete evidence without broad deployment assumptions. Retain. |
| verify-release-skill.sh | Missing/symlinked output rejection, validator invocation, uv/system fallback, expected release name, and JSON result provide a useful narrow check. It does not establish that the authoring agent invoked validation itself; semantic assertions must assess that. Retain. |
| verify-review-report.sh and test-report-verifier.py | Wrapper wires the subfolder path into the zero-argument eval runner. Persistent positive/negative checks cover counting, path selection, and declared assertions; eval-only cost is justified by reproduced false credit. Retain. |
| verify-self-audit.sh | File existence, symlink exclusion, optional run-start freshness, and machine-readable verdict are useful narrow checks. Retain with top-level parsing and explicit report-path support. |

Verifier follow-up scope was 18 skill files (6,334 words at that stage,
including concurrent review-gate updates). The two new files are eval-only.

## Verification and limits

- Frontmatter validation passed for the audited skill.
- Mixed-key regression smoke check passed after the fix; invalid-name rejection remained intact.
- Duplicate-description acceptance reproduced before its fix; nested-option verifier false positive was reproduced before its fix.
- Persistent frontmatter regression suite passed after five duplicate subcases failed before implementation. Valid merge outputs match SafeLoader; unsafe tags and unhashable keys remain rejected.
- Duplicate-key implementation and edited skill passed independent doc-authoring review.
- Report verifier correctly failed empty input and passed a two-item inventory.
- All five eval shell scripts passed bash syntax checks.
- New case IDs and fixture/script paths validated; mechanical assertion strings match declared assertions.
- Eight positive/negative branch-checker smoke cases passed; missing baseline snapshot failed clearly.
- Eval additions passed independent implementation and full doc-authoring review; coverage is authored, not behaviorally proven.
- skills/check-refs.sh passed storage fallback, install layout, scalar description, pointer resolution, script naming, reference reachability, and retired-name checks.
- git diff --check passed for the skill changes.
- Independent full-scope audit completed; all three applied fixes passed independent implementation review. The layout
  clarification also passed a follow-up doc-authoring review of the edited skill.
- Report-verifier suite passed eight methods after five failing subcases were reproduced before implementation.
- No model-driven evals, duplicate-key behavior comparisons across harnesses, or runtime token measurements were performed.
- Remaining recommendations alter accepted inputs, prescribed workflows, or evaluation design; they were not treated as functionality-preserving copy edits.
