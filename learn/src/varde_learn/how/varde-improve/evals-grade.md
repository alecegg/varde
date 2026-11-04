---
topic: varde-improve/evals-grade
version: 1
summary: Eval step 5 of 6, after compare - grade with trace evidence and iterate on assertions
---

## Grade and iterate

- Put mechanical checks (file creation, valid JSON, counts, dimensions, diffs)
  in `verification_script`. The judge grades the rest from the final text, the
  post-run file listing, and the ordered tool-use list.
- Accept a grade only with concrete trace evidence. Prose never proves file
  creation or independent-review execution. An assertion the trace cannot
  establish is missing evidence, not PASS.
- Replace assertions that always pass, always fail, or cannot be verified from
  available output.
