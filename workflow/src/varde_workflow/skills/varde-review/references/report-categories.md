# Review categories

## Standalone review

Plain review uses `CORRECTNESS`, `CODE`, and `ARCHITECTURE`. Thorough review
uses every relevant category below; named concerns use their matching category.

## Plan architecture review

At plan finish or on demand, review `CORRECTNESS`, `CODE`, and macro
architecture in the categories `ARCHITECTURE`, `API-DESIGN`, `SIMPLICITY`,
`DATA-INTEGRITY`, `RESILIENCE`, and `SECURITY`, when touched. The gate owns lint, tests, types, and scans;
conformance owns the Spec axis.

## Categories

Skip untouched categories.

- **CORRECTNESS** — every written value has a runtime reader. Coverage is a check that fails without the fix, not one that hand-builds state or recomputes the expected value with its own logic.
- **CODE** — oversized functions, duplicated logic, dead code, deep nesting, magic values. In plans, scan-covered issues belong to the gate.
- **ARCHITECTURE** — a new cross-module dependency or cycle, or an abstraction duplicating an existing one.
- **API-DESIGN** — a public signature, type, flag, or endpoint; an unupdated caller means the break was not internal.
- **SECURITY** — trace untrusted input to its sink, then read the sink for sanitization: shell, SQL, or path construction, auth, secrets, CORS, network binding. A removed guard on a protected path is a finding even when the hunk only deletes code.
- **PERFORMANCE** — an unbounded or hot path, or I/O in a loop. Without production-scale data on the path, never above `medium`.
- **OBSERVABILITY** — a new failure mode or background call; check the caller's metrics first.
- **READABILITY** — names, comments, structure; a misleading name is `medium` severity.
- **SIMPLICITY** — additions that do not earn their cost; a one-caller abstraction is `low`.
- **RESILIENCE** — partial failure; a retry without backoff is `high`, a rare internal call without a timeout is `medium`.
- **DATA-INTEGRITY** — compare every writer of a shared resource; drift validation already catches is `medium`.

## Rules

- Verify every high-severity finding against the code before reporting it.
- Apply a fix that makes actual behaviour match the spec. Group a fix that changes intended behaviour (what the plan, spec, or public API promises) for the user.
