# Test quality

Apply these rules to every added or modified test; tests may check architecture required by the specification and generated-artifact freshness. Report each hit as a `CORRECTNESS-NNN` finding with `Severity: high`, title `Low-quality test: <rule>`, and a summary naming the test and quoting its offending assertion. Any open finding requires `verdict: changes-requested` and cannot be deferred, overriding the fix workflow's deferral instruction.

- **Low-quality test: internals.** Bad: assert a mock was called twice or inspect a private attribute.
- **Low-quality test: tautology.** Bad: calculate the expected value with the code under test or the same logic.
- **Low-quality test: source text.** Bad: assert `"def run"` occurs in source or grep a skill file.
- **Low-quality test: byte copy.** Bad: compare a file with its mirror using `cmp` or `filecmp`.
- **Low-quality test: borrowed golden.** Bad: trust a golden from another implementation because outputs match.
- **Low-quality test: design assertion.** Bad: assert an incidental helper, class, or file layout without checking its effect.
