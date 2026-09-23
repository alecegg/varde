# Debugging entry path

Use this reference when a request names a bug or regression without an explicit
mode, or explicitly asks for diagnosis only. This path stays inside
`varde-change` and uses `references/build-posture-debug.md` for the investigation
discipline.

## Select the debug mode

Set exactly one `debug_mode`:

- `diagnose` for diagnosis-only requests. Reproduce the symptom, test ranked
  hypotheses, and report the likely cause. Do not edit production source.
- `fix` for a requested bug fix or regression repair. Reproduce and minimize
  first, then test hypotheses before writing the fix.

Set `route_source` to `automatic` when the named bug or regression triggered
this path. Set it to `explicit` when the user requested diagnosis-only mode.

Explicit requests have priority. An exploration request routes to
`varde-explore`. An explicit build request routes to the normal build path,
even when the request contains bug or regression language.

## Evidence gate

Represent the investigation as `debug_evidence` with these fields:

1. `reproduction`: one deterministic command and its observed symptom.
2. `hypotheses`: three to five ranked, falsifiable hypotheses.
3. `experiments`: one result for each tested hypothesis.
4. `cause`: the supported root-cause explanation.
5. `verification`: the regression check and full verification result.

For `fix`, fields `reproduction`, `hypotheses`, and `experiments` must be
non-empty before implementation starts. The fix then adds `cause` and
`verification` before reporting completion. For `diagnose`, `cause` may remain
uncertain, but the report must state the evidence limit and leave production
source unchanged.

Do not claim a fix from a passing command alone. Preserve the original
reproduction command and run it again after the regression test passes.
