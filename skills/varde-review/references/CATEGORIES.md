# Review categories

One section per review category; read the relevant category's section.

## CORRECTNESS

### When relevant

Applies to any change with logic branches, arithmetic, comparisons, or state mutation. Nearly every implementation change touches this category; skip only for pure formatting/comment-only diffs.

### What to look for

- Off-by-one errors in loop bounds or slicing.
- Boundary conditions not handled (empty collection, null/undefined, zero, negative values).
- Incorrect operator (`&&` vs `||`, `<` vs `<=`) relative to the stated intent.
- Async/await misuse causing an unhandled promise or a race between concurrent writes.
- A change that satisfies the happy path but silently breaks an existing edge case covered elsewhere in the codebase.
- A value the change writes (a field, flag, status, column, artifact) that no runtime reader actually consumes — the consumption path is the common hole. Not "the write returned 200", but "the runtime reads this new value".

### Severity calibration

A bug that produces silently wrong output (no crash, no test failure, just incorrect data) is critical — it's the hardest to catch downstream. A bug that throws or crashes loudly is high, since it's at least visible. An edge case that's unreachable given the actual call sites is low. A suspected bug in a file with no covering tests (`tests_for_file` in the `## Analyze the changed code` section of `references/WORKFLOW.md`, step 3, when available) raises calibration a tier — nothing would have caught it either way.

### How to check

Read the full function under review rather than just the diff hunk — correctness bugs often hinge on context outside the changed lines (an earlier guard clause, a later use of the same variable). Grep for other call sites of the same logic to check whether they already handle the edge case this change might be missing, which tells you whether the gap is new or pre-existing. For anything the change writes, trace every runtime reader of that value before trusting it as consumed. A green test proves nothing if it hand-builds the exact state the production code is supposed to produce — check which production code creates the state under test before counting the test as coverage.

### What counts as a finding

A boundary, operator, or async-handling bug confirmed by reading the full function and its callers, not just inferred from the diff hunk alone; or a value the change writes with no confirmed runtime reader.

### Auto-fix patterns

Adding a missing null/empty guard that mirrors an existing pattern elsewhere in the file is safe to auto-fix. A logic error in business-rule arithmetic or an operator that changes program behavior requires human confirmation of the intended semantics.

## CODE

### When relevant

Applies to any change that adds or modifies function or method bodies. Most reviews touch this category — skip it only for pure documentation, config, or data-only changes with no logic.

### What to look for

- Functions or methods that exceed a reasonable size for their responsibility.
- Cyclomatic complexity high enough that the control flow is hard to hold in mind.
- Duplicated logic that should be a shared helper.
- Dead code: unreachable branches, unused parameters, unused local variables.
- Deep nesting (more than 3–4 levels) that could flatten via early return or extraction.
- Magic numbers or strings that should be named constants.

### Severity calibration

Duplication and dead code are typically low-to-medium — they cost maintenance but don't cause incorrect behavior. High complexity or size in a function on a hot path, or in code with poor test coverage, escalates to medium-high because it raises the odds of a future regression slipping through. Reserve high/critical for complexity that already correlates with a bug in the same review.

### How to check

Skim the changed files for long functions, deep nesting, and repeated blocks before reading any body in full — this avoids a blind sweep of every changed file. For each candidate, read the full function body to confirm the complexity is real (not an artifact of a long switch or generated code) before flagging.

### What counts as a finding

A function or block that matches one of the "What to look for" items above, confirmed by reading the actual body rather than inferred from the diff hunk alone.

### Auto-fix patterns

Extracting a named constant for a magic number, removing confirmed dead code, and extracting small duplicated blocks into a shared helper are safe for automatic resolution. Splitting a large function into smaller ones requires human judgment about the right seams and is not auto-fixed.

## ARCHITECTURE

### When relevant

Applies whenever a change adds a new dependency between modules, moves code across a layer boundary, or introduces a new module/package. Less relevant for changes confined to a single function body with no new imports.

### What to look for

- New imports that cross an established layer boundary in the wrong direction (e.g. core importing from a CLI or UI layer).
- Circular dependencies introduced or worsened by the change.
- A module accumulating disproportionately high fan-in or fan-out relative to its stated responsibility.
- Logic placed in a layer that doesn't own it (e.g. business rules embedded in a transport handler).
- A new abstraction that duplicates responsibility already covered by an existing module.

### Severity calibration

A new circular dependency or a layer-boundary violation is high — these are expensive to unwind the longer they persist. A single misplaced concern in an otherwise-sound module is medium. Fan-in/fan-out growth that's proportional to the module's existing role is low or not worth flagging at all.

### How to check

Grep for imports of any module whose public surface is changing to see its fan-in and judge blast radius before flagging a breaking change. Read the changed file's import list to trace whether a new import crosses a boundary it shouldn't. For suspected cycles, grep both ends of the suspected cycle for imports of each other and confirm the cycle is real by reading both files.

### What counts as a finding

A layering violation, cycle, or misplaced concern confirmed by reading the actual imports and code, not just inferred from file names.

### Auto-fix patterns

Architecture findings almost always require human judgment about the right module boundary or abstraction and are not auto-fixed. The one exception is a mechanical import reordering that resolves a false-positive cycle without any code movement.

## SECURITY

### When relevant

Applies to any change that handles user input, constructs a shell/SQL/file-system command, touches authentication or authorization, or reads/writes secrets or credentials. Low relevance for internal-only pure-computation changes with no external input.

### What to look for

- User-controlled input reaching a shell command, SQL query, or file path without sanitization.
- Missing or weakened authentication/authorization checks on a previously guarded path.
- Secrets, tokens, or credentials hardcoded or logged in plaintext.
- Unsafe deserialization of untrusted data.
- Overly permissive CORS, file permissions, or network bindings introduced by the change.

### Severity calibration

Any confirmed injection vector (command, SQL, path traversal) reachable from untrusted input is critical. A missing authz check on a sensitive endpoint is critical to high depending on exposure. Logged secrets or overly permissive defaults are high. Theoretical issues with no realistic untrusted-input path are low and should be noted, not escalated.

### How to check

Grep for every call site of any input-handling function to trace whether untrusted input can actually reach the suspect sink — a theoretical vulnerability with no reachable caller is lower severity. Read the full body of the sink itself to check whether sanitization or parameterization is already applied before flagging.

### What counts as a finding

An injection vector, missing authz check, exposed secret, or unsafe deserialization confirmed by reading the actual sink and call chain, not just inferred from the diff hunk alone.

### Auto-fix patterns

Switching a string-concatenated query to a parameterized one, or removing a hardcoded secret in favor of an existing config/env pattern, is safe to auto-fix when the surrounding code already has a clear parameterized/config precedent to follow. Authorization logic changes always require human judgment.

## PERFORMANCE

### When relevant

Applies to any change in a loop over unbounded data, a hot path (called per-request or per-item at scale), or a database/network call inside iteration. Lower relevance for one-shot startup code or admin tooling with small, bounded input.

### What to look for

- A database or network call issued inside a loop instead of batched (N+1 pattern).
- An algorithm with worse asymptotic complexity than the problem requires (e.g. nested linear scans where a map lookup would do).
- Unbounded memory growth — accumulating an entire dataset in memory when streaming would work.
- Synchronous blocking I/O on a path that should be async/non-blocking.
- Redundant recomputation of a value that could be cached or hoisted out of a loop.

### Severity calibration

An N+1 query pattern or unbounded memory growth on a path with production-scale data is high. The same pattern on a path known to run against small, bounded input (e.g. a CLI tool over a handful of files) is low — flag it as a note, not a blocker. Algorithmic complexity issues scale with expected input size.

### How to check

Grep for call sites of a changed function to check how many there are and whether any of them pass production-scale data — this determines whether a flagged inefficiency actually matters. Read the full function body to confirm a suspected loop-nested I/O call rather than inferring from the diff hunk alone.

### What counts as a finding

An N+1 pattern, unbounded memory growth, or algorithmic complexity issue confirmed by reading the full function body and its call sites, not just inferred from the diff hunk alone.

### Auto-fix patterns

Hoisting a loop-invariant computation out of a loop, or batching an obviously batchable set of sequential calls using an existing batch API in the codebase, is safe to auto-fix. Redesigning an algorithm's complexity or introducing a cache requires human judgment about correctness trade-offs (staleness, invalidation).

## OBSERVABILITY

### When relevant

Applies to any change introducing a new failure mode, a new external call, or a background/async operation that a future operator would need to diagnose. Lower relevance for pure internal refactors with unchanged external behavior.

### What to look for

- A caught error that's swallowed with no log, metric, or re-throw.
- A new failure path with no way for an operator to distinguish it from other failures in logs.
- Logging that includes sensitive data (secrets, full request bodies with PII).
- A new background job or async operation with no way to observe its completion or failure.
- Log levels that don't match severity (an actual error logged at debug/info).

### Severity calibration

A silently swallowed error on a path that can cause real data loss or corruption is high. A new failure mode indistinguishable from others in logs is medium — it slows incident response but doesn't cause the incident. Log-level mismatches are low unless they hide a critical error.

### How to check

Read any catch block in full to check whether the caught error is logged, rethrown, or genuinely dropped. Grep for callers of the surrounding function to see whether the calling code has its own observability (metrics, tracing) that would surface a silent failure indirectly, before assuming a gap is uncovered.

### What counts as a finding

A swallowed error, missing log, or logged secret confirmed by reading the actual catch block and surrounding code, not just inferred from the diff hunk alone.

### Auto-fix patterns

Adding a log statement to an empty catch block, following the logging convention already used elsewhere in the file, is safe to auto-fix. Redesigning what gets logged for an entire subsystem, or deciding what constitutes sensitive data in a given context, requires human judgment.

## READABILITY

### When relevant

Applies to any change touching identifier names, comments, or code structure that a future reader will need to parse. Lower relevance for auto-generated files or vendored code.

### What to look for

- Identifier names that don't communicate intent (single letters outside tight loops, abbreviations that aren't domain-standard).
- Comments that restate what the code does instead of explaining a non-obvious why.
- Inconsistent naming or formatting conventions relative to the surrounding file.
- Control flow that's technically correct but structured in a way that obscures intent (e.g. inverted conditionals, deeply chained ternaries).
- Missing or misleading documentation on a public API surface.

### Severity calibration

Readability issues are rarely above medium since they don't affect correctness. A misleading comment or name (one that actively suggests wrong behavior) is medium-high because it actively misleads future readers. Purely stylistic inconsistency is low.

### How to check

Read the whole file to survey naming conventions and spot an outlier identifier relative to its neighbors. Grep for call sites of a public symbol with unclear naming to gauge how many would be affected by a rename, informing whether to flag it as a quick fix or a larger cleanup.

### What counts as a finding

A naming, comment, or structure issue confirmed by reading the actual file and its neighbors, not just inferred from the diff hunk alone.

### Auto-fix patterns

Renaming an identifier to match established convention, or removing a comment that merely restates the code, are safe for automatic resolution as long as `dependents` confirms a rename's blast radius is limited to the current change. Restructuring control flow for clarity requires human judgment about the intended behavior.

## RESILIENCE

### When relevant

Applies to any change that calls an external service, reads/writes I/O, or handles an operation that can partially fail. Lower relevance for pure in-memory computation with no external dependency.

### What to look for

- Missing error handling around a network call, file operation, or external process invocation.
- A retry loop with no backoff, cap, or jitter that could hammer a failing dependency.
- A resource (file handle, connection, lock) not released on the error path.
- A partial-failure scenario (batch operation where some items fail) with no defined behavior.
- Timeouts absent on an operation that can hang indefinitely.

### Severity calibration

An unhandled failure path that can crash the process or corrupt state on partial failure is high. A retry loop without backoff that risks amplifying an outage is high. A missing timeout on a rarely-invoked internal call is medium. Cosmetic error-message quality issues are low.

### How to check

Read the full function making the external call to check whether the surrounding try/catch (or its absence) covers the actual failure surface. Grep for callers of this function to check whether they already assume it cannot fail, which would make a newly-introduced failure path a breaking behavior change.

### What counts as a finding

A missing error handler, unbounded retry, resource leak, or missing timeout confirmed by reading the actual function body, not just inferred from the diff hunk alone.

### Auto-fix patterns

Wrapping an I/O call in error handling that mirrors an existing pattern elsewhere in the codebase is safe to auto-fix. Designing retry/backoff policy or partial-failure semantics requires human judgment about the operation's actual failure modes.

## DATA-INTEGRITY

### When relevant

Applies to any change that writes to persistent storage (files, databases, notes) or mutates shared state read by multiple callers. Lower relevance for pure read-only or in-memory-only changes.

### What to look for

- A write operation with no validation of the data being persisted, allowing malformed state to be written.
- A partial write (multi-step persistence) with no rollback or transaction boundary on failure.
- A race condition where concurrent writers can overwrite each other's changes (missing optimistic-concurrency check).
- Schema or format drift — a write that doesn't match what readers of the same data expect.
- A migration or backfill with no idempotency guarantee if re-run.

### Severity calibration

A write path that can corrupt or silently lose committed data is critical. A missing OCC/concurrency check on a resource known to have concurrent writers is high. Schema drift caught by existing validation elsewhere is medium. A non-idempotent migration that's documented as run-once is low.

### How to check

Grep for every writer of the same resource and read each one to check whether they agree on format/validation — drift often shows up as one writer skipping a check the others perform. Read the full multi-step write function to confirm whether it's wrapped in a transaction or has partial-failure exposure.

### What counts as a finding

A write path confirmed to lack validation, a transaction boundary, or concurrency safety by reading the actual write code, not just inferred from the diff hunk alone.

### Auto-fix patterns

Adding a validation check that mirrors an existing pattern used by sibling writers of the same resource is safe to auto-fix. Introducing transaction boundaries, OCC checks, or migration idempotency requires human judgment about the surrounding system's concurrency model.

## API-DESIGN

### When relevant

Applies to any change to a public function signature, exported type, CLI flag, or MCP/HTTP endpoint contract. Lower relevance for internal-only helper functions with no external callers.

### What to look for

- A breaking signature change (removed parameter, changed return type) on a symbol with external callers.
- Inconsistent naming or parameter ordering relative to sibling functions in the same API surface.
- Optional parameters added in a position that breaks positional-call sites instead of appended at the end.
- Missing input validation at a trust boundary where the API is the first line of defense.
- An API that leaks an internal implementation detail (e.g. an ORM entity) instead of a stable contract type.

### Severity calibration

A breaking change to a widely-consumed public API with no migration path is high to critical. The same change on an API with a single internal caller updated in the same commit is low. Naming/ordering inconsistency is low unless it actively causes a footgun (e.g. two functions with reversed argument order for the same conceptual pair).

### How to check

Grep the repo for every call site of the changed symbol (by name) and read each one to confirm it was updated in the same change — an unupdated caller means the "breaking change" wasn't actually internal-only. Read sibling files in the same API surface to check naming/parameter-order consistency before flagging an inconsistency. The code-intelligence skill can speed this up when it's available, but plain grep/read is sufficient.

### What counts as a finding

A change that matches one of the "What to look for" items above, confirmed by reading the actual call sites and surrounding code rather than inferred from the diff hunk alone.

### Auto-fix patterns

Reordering a newly-added optional parameter to the end of the signature, when a grep of call sites confirms none rely on the current position, is safe to auto-fix. A genuine breaking change to a widely-consumed API requires human judgment about versioning or migration strategy.
