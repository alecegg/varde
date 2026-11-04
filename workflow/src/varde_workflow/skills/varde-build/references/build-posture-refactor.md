# Refactor Posture

- Refactor and commit only on green. Run `tests_for_file` for the target and record
  pre-existing failures before the first change.
- Preserve observable behavior: same inputs give the same outputs, side effects,
  and public APIs; messages, logs, and wire formats stay unchanged.
- When replacing an internal API, leave no in-scope caller of the old one,
  remove it in the same change, and report out-of-scope callers.
- Rename only when the rename is the change.
