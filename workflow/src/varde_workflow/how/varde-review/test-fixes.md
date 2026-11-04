---
topic: varde-review/test-fixes
version: 1
summary: Good alternatives for each low-quality test rule
---

## Fixing low-quality tests

- **internals.** Run the command and assert its output and exit code.
- **tautology.** Write the expected value from the specification.
- **source text.** Run the script or CLI and assert its output.
- **byte copy.** Run the installed copy and assert behavior. Generator-output freshness checks are not byte-copy findings.
- **borrowed golden.** Use a small hand-written input and expected result justified by the specification.
- **design assertion.** Assert the behavior or output the helper, class, or file layout provides. A design choice required by the specification is a valid contract to test.
- Fix by asserting behavior or output, or delete a test that protects no behavior.
