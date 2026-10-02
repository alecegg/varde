# Review categories

## Rules for every category

- **Auto-fix rule:** `auto-fix` only when the fix is precisely describable and
  mirrors a pattern already in the file or its siblings; otherwise `triage`.
- **Always `triage` (a human decides):**
  - business-rule arithmetic or behavior-changing operators
  - splitting functions or restructuring control flow
  - any ARCHITECTURE change except a mechanical import reorder that breaks a
    false-positive cycle
  - authorization logic
  - complexity redesign or caching
  - what counts as sensitive log data
  - retry and partial-failure policy
  - transactions
  - concurrency checks
  - migration idempotency
  - breaking a consumed API
- **Renames:** confirm a rename's blast radius before labelling it `auto-fix`.

## CORRECTNESS

- **When:** any logic, arithmetic, comparison, or state mutation; skip only
  formatting- or comment-only diffs.
- **Check:** every value the change writes (field, flag, status, column,
  artifact) has a runtime reader. A green test that hand-builds the state
  production code should create is not coverage; nor is an assertion that
  recomputes the expected value with the code's own logic.
- **Severity:** no covering tests raises a confirmed bug one level; silently
  wrong output outranks a crash.

## CODE

- **When:** function bodies added or modified.
- **Check:** oversized functions, hard-to-follow control flow, duplicated logic
  that wants a shared helper, dead code, flattenable nesting, and unnamed magic
  values; read candidates in full to rule out a long switch or generated code.
- **Severity:** hot path or poor coverage raises complexity to medium; high only
  when it already correlates with a bug in this review.

## ARCHITECTURE

- **When:** a new cross-module dependency, code moved across a layer, or a new
  module.
- **Check:** confirm a suspected cycle by reading both ends' imports; for a new
  module or abstraction, grep for an existing one it duplicates.

## SECURITY

- **When:** user input, shell/SQL/path construction, auth, secrets, or
  permission, CORS, or network-binding config.
- **Check:** trace whether untrusted input actually reaches the sink; read the
  sink for existing sanitization or parameterization. A removed or bypassed
  guard on a previously protected path is a finding even when the hunk only
  deletes code.
- **Severity:** no realistic untrusted-input path is low, noted without
  escalating; missing authorization is critical or high by exposure.

## PERFORMANCE

- **When:** loops over unbounded data, hot paths, or I/O inside iteration.
- **Check:** whether any call site passes production-scale data.
- **Severity:** without production-scale data on the path, never above medium.

## OBSERVABILITY

- **When:** a new failure mode, external call, or background operation.
- **Check:** before calling a gap uncovered, check whether the caller's metrics
  or tracing already surface it.

## READABILITY

- **When:** names, comments, or structure a reader must parse; not generated or
  vendored code.
- **Severity:** rarely above medium; a name or comment implying wrong behavior
  is medium-high.

## RESILIENCE

- **When:** external calls, I/O, or operations that can partially fail.
- **Check:** if callers assume this function cannot fail, a new failure path is
  a breaking behavior change.
- **Severity:** a retry loop without backoff is high (it amplifies outages); a
  missing timeout on a rarely invoked internal call is medium.

## DATA-INTEGRITY

- **When:** writes to persistent storage or shared state with several readers.
- **Check:** compare every writer of the resource; drift shows as one writer
  skipping a check or format the others keep.
- **Severity:** drift already caught by validation elsewhere is medium; a
  non-idempotent migration documented as run-once is low.

## API-DESIGN

- **When:** a public signature, exported type, CLI flag, or endpoint contract.
- **Check:** confirm every call site was updated in the same change; an
  unupdated caller means the "internal-only" break was not.
- **Severity:** a break whose only caller is internal and updated in the same
  commit is low; naming or order inconsistency is low unless a footgun, such as
  reversed argument order across a conceptual pair.
