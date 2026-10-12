# Refactor Posture

Refactor only on green: run `tests_for_file` for the target and record
pre-existing failures before the first change.

Preserve observable behavior: same inputs give the same outputs, side effects,
and public APIs; messages, logs, and wire formats stay unchanged.

Make one behavior-preserving change at a time, rerun the target's tests after
each, and commit only on green; revert only the failing attempt.

Count callers with `varde map dependents` before inlining; rename only when the
rename is the change.
