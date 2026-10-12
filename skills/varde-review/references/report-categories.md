# Review categories

## Spec axis

Does the diff do what the task, plan, or linked specs asked? Cite the source
line; report missing, partial, wrong, and unasked-for work. With no spec, join
`CORRECTNESS` here.

## Standards axis

Skip untouched categories.

- **CORRECTNESS** — every written value has a runtime reader; coverage is a check that fails without the fix, not one that hand-builds state or recomputes the expected value with its own logic.
- **CODE** — oversized functions, duplicated logic, dead code, deep nesting, magic values.
- **ARCHITECTURE** — a new cross-module dependency or cycle, or an abstraction duplicating an existing one.
- **SECURITY** — trace untrusted input to its sink, then read the sink for sanitization: shell, SQL, or path construction, auth, secrets, CORS, network binding. A removed guard on a protected path is a finding even when the hunk only deletes code.
- **PERFORMANCE** — an unbounded or hot path, or I/O in a loop. Without production-scale data on the path, never above medium.
- **OBSERVABILITY** — a new failure mode or background call; check the caller's metrics first.
- **READABILITY** — names, comments, structure; a misleading name is medium-high.
- **SIMPLICITY** — additions that do not earn their cost; a one-caller abstraction is low.
- **RESILIENCE** — partial failure; a retry without backoff is high, a rare internal call without a timeout is medium.
- **DATA-INTEGRITY** — compare every writer of a shared resource; drift validation already catches is medium.
- **API-DESIGN** — a public signature, type, flag, or endpoint; an unupdated caller means the break was not internal.

## Rules

- Verify every high or critical finding against the code before reporting it.
- Apply a fix that makes actual behaviour match the spec. Group a fix that changes intended behaviour (what the plan, spec, or public API promises) for the user.
