# Review categories

Read the section for each relevant category. Each names when it applies, what to
look for, how to calibrate severity, and the check specific to it.

## Rules for every category

**How to check:** Read the full function or file under review, not the diff hunk
— most findings hinge on context outside the changed lines. Grep the call sites
of anything the change touches before judging blast radius. Each category below
adds the check particular to it.

**What counts as a finding:** A defect confirmed by reading the actual code, not
inferred from the diff hunk. `references/report-format.md`'s finding discipline
sets the evidence bar.

**What a fix pass may auto-resolve:** A change that mirrors a pattern already
present in the file or its siblings — adding the guard, log, constant, or
validation the neighbours already use. Anything requiring a judgment about
intended semantics, module boundaries, or a system's concurrency model
escalates. Categories note their own exceptions.

## CORRECTNESS

**When relevant:** Any change with logic branches, arithmetic, comparisons, or state mutation. Nearly every implementation change; skip only for formatting- or comment-only diffs.

**Look for:** off-by-one bounds, unhandled boundary values, a wrong operator
relative to the stated intent, async misuse causing an unhandled promise or a
race, and a happy path that breaks an edge case covered elsewhere. The one that
hides: a value the change writes — field, flag, status, column, artifact — that
no runtime reader consumes. Not "the write returned 200", but "the runtime reads
this new value".

**Severity calibration:** A bug that silently produces wrong output is critical — it is hard to catch later. A visible crash is high. An unreachable edge case is low. If a file has no covering tests, raise a suspected bug by one severity level.

**How to check:** Trace every runtime reader of a value the change writes before trusting it as consumed. A green test proves nothing if it hand-builds the exact state the production code is supposed to produce — check which production code creates the state under test before counting the test as coverage. Nor if its assertion recomputes the expected value the way the code does: that passes by construction and can never disagree with the code.

**Auto-fix:** Business-rule arithmetic and operators that change program behavior need human confirmation of the intended semantics.

## CODE

**When relevant:** Any change that adds or modifies function or method bodies. Skip for pure documentation, config, or data-only changes with no logic.

**Look for:** oversized functions, control flow too complex to hold in mind,
duplicated logic that wants a shared helper, dead code, nesting an early return
would flatten, and magic values that want a name.

**Severity calibration:** Duplication and dead code are typically low-to-medium — they cost maintenance but don't cause incorrect behavior. High complexity or size in a function on a hot path, or in code with poor test coverage, escalates to medium-high because it raises the odds of a future regression slipping through. Reserve high/critical for complexity that already correlates with a bug in the same review.

**How to check:** Skim the changed files for long functions, deep nesting, and repeated blocks first, then read only the candidates in full — confirm the complexity is real and not an artifact of a long switch or generated code.

**Auto-fix:** Splitting a large function needs human judgment about the right seams.

## ARCHITECTURE

**When relevant:** A change that adds a dependency between modules, moves code across a layer boundary, or introduces a new module/package. Less relevant for changes confined to one function body with no new imports.

**Look for:** an import crossing a layer boundary in the wrong direction, a cycle
introduced or worsened, fan-in or fan-out out of proportion to the module's
stated responsibility, logic sitting in a layer that doesn't own it, and a new
abstraction duplicating one that already exists.

**Severity calibration:** A new circular dependency or a layer-boundary violation is high — these are expensive to unwind the longer they persist. A single misplaced concern in an otherwise-sound module is medium. Fan-in/fan-out growth proportional to the module's existing role is low or not worth flagging at all.

**How to check:** For a suspected cycle, grep both ends for imports of each other and read both files to confirm it is real.

**Auto-fix:** Nothing here, save a mechanical import reordering that resolves a false-positive cycle without moving code. Module boundaries are a human call.

## SECURITY

**When relevant:** A change that handles user input, constructs a shell/SQL/file-system command, touches authentication or authorization, or reads/writes secrets. Low relevance for internal-only pure-computation changes with no external input.

**Look for:** untrusted input reaching a shell, SQL, or path sink unsanitized; a
previously guarded path losing its authn/authz check; secrets hardcoded or
logged in plaintext; unsafe deserialization; and permissions, CORS, or network
bindings loosened by the change.

**Severity calibration:** Any confirmed injection vector (command, SQL, path traversal) reachable from untrusted input is critical. A missing authz check on a sensitive endpoint is critical to high depending on exposure. Logged secrets or overly permissive defaults are high. Theoretical issues with no realistic untrusted-input path are low — note them, don't escalate.

**How to check:** Trace whether untrusted input can actually reach the suspect sink; a vulnerability with no reachable caller is lower severity. Read the sink itself to check whether sanitization or parameterization is already applied.

**Auto-fix:** Authorization logic always requires human judgment.

## PERFORMANCE

**When relevant:** A change in a loop over unbounded data, a hot path (called per-request or per-item at scale), or a database/network call inside iteration. Lower relevance for one-shot startup code or admin tooling with bounded input.

**Look for:** a call issued per-iteration instead of batched, complexity above
what the problem requires, unbounded memory growth where streaming would do,
blocking I/O on a path that should be async, and recomputation that could hoist
out of the loop.

**Severity calibration:** An N+1 query pattern or unbounded memory growth on a path with production-scale data is high. The same pattern on a path known to run against small, bounded input (e.g. a CLI tool over a handful of files) is low — flag it as a note, not a blocker. Algorithmic complexity issues scale with expected input size.

**How to check:** Check whether any call site actually passes production-scale data — that determines whether a flagged inefficiency matters at all.

**Auto-fix:** Redesigning complexity or introducing a cache requires human judgment about staleness and invalidation.

## OBSERVABILITY

**When relevant:** A change introducing a new failure mode, a new external call, or a background/async operation a future operator would need to diagnose. Lower relevance for pure internal refactors with unchanged external behavior.

**Look for:** a caught error swallowed with no log, metric, or re-throw; a new
failure path indistinguishable from others in logs; sensitive data in log
output; a background operation with no way to observe completion or failure; and
a log level that doesn't match severity.

**Severity calibration:** A silently swallowed error on a path that can cause real data loss or corruption is high. A new failure mode indistinguishable from others in logs is medium — it slows incident response but doesn't cause the incident. Log-level mismatches are low unless they hide a critical error.

**How to check:** Before calling a gap uncovered, check whether the calling code has its own metrics or tracing that would surface the silent failure indirectly.

**Auto-fix:** Deciding what counts as sensitive data in a given context is a human call.

## READABILITY

**When relevant:** A change touching identifier names, comments, or code structure a future reader must parse. Lower relevance for auto-generated or vendored code.

**Look for:** names that don't carry intent, comments restating the code instead
of a non-obvious why, conventions inconsistent with the surrounding file, control
flow structured so it obscures intent, and missing or misleading documentation on
a public surface.

**Severity calibration:** Rarely above medium, since these don't affect correctness. A misleading comment or name — one that actively suggests wrong behavior — is medium-high, because it misdirects future readers. Purely stylistic inconsistency is low.

**How to check:** Survey the whole file's naming conventions to spot an outlier relative to its neighbours, rather than judging a name in isolation.

**Auto-fix:** A rename needs its blast radius confirmed first. Restructuring control flow for clarity is a human call.

## RESILIENCE

**When relevant:** A change that calls an external service, reads/writes I/O, or handles an operation that can partially fail. Lower relevance for pure in-memory computation.

**Look for:** a network, file, or subprocess call with no error handling; a retry
loop with no backoff, cap, or jitter; a resource not released on the error path;
a partial-failure case with no defined behavior; and a missing timeout on
something that can hang.

**Severity calibration:** An unhandled failure path that can crash the process or corrupt state on partial failure is high. A retry loop without backoff that risks amplifying an outage is high. A missing timeout on a rarely-invoked internal call is medium. Cosmetic error-message quality is low.

**How to check:** Check whether callers already assume this function cannot fail — that makes a newly-introduced failure path a breaking behavior change.

**Auto-fix:** Retry/backoff policy and partial-failure semantics need human judgment about actual failure modes.

## DATA-INTEGRITY

**When relevant:** A change that writes to persistent storage (files, databases, notes) or mutates shared state read by multiple callers. Lower relevance for read-only or in-memory-only changes.

**Look for:** a write with no validation of what it persists, a multi-step write
with no rollback or transaction boundary, concurrent writers with no
optimistic-concurrency check, a write whose format drifts from what readers
expect, and a migration with no idempotency guarantee if re-run.

**Severity calibration:** A write path that can corrupt or silently lose committed data is critical. A missing concurrency check on a resource known to have concurrent writers is high. Schema drift caught by existing validation elsewhere is medium. A non-idempotent migration documented as run-once is low.

**How to check:** Read every writer of the same resource and check whether they agree on format and validation — drift shows up as one writer skipping a check the others perform.

**Auto-fix:** Transaction boundaries, concurrency checks, and migration idempotency need human judgment about the surrounding system.

## API-DESIGN

**When relevant:** A change to a public function signature, exported type, CLI flag, or MCP/HTTP endpoint contract. Lower relevance for internal-only helpers with no external callers.

**Look for:** a breaking signature change on a symbol with external callers,
naming or parameter order inconsistent with siblings in the same surface, an
optional parameter inserted mid-list instead of appended, missing validation at a
trust boundary, and an internal type leaking where a stable contract belongs.

**Severity calibration:** A breaking change to a widely-consumed public API with no migration path is high to critical. The same change on an API with a single internal caller updated in the same commit is low. Naming/ordering inconsistency is low unless it causes a footgun — two functions with reversed argument order for the same conceptual pair.

**How to check:** Confirm every call site was updated in the same change; an unupdated caller means the "internal-only" breaking change wasn't.

**Auto-fix:** A genuine breaking change to a consumed API needs a human decision on versioning or migration.
