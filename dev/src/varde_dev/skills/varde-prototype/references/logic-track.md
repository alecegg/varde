# Logic Track

- `<storage>/logic.md` is edited in place and exported with `varde learn docs build`; it has no iteration files.
- It is a static page: a title and question paragraph, then page components.
- It uses no script and no server. Clicking through live is not offered; when the question needs it, the real-app rule applies.
- The page holds the state-transition table (state, action, next state).
- It also holds the guided scenarios as step-by-step tables of state, action and result:
  - the happy path
  - a tricky edge case
  - an action that should be illegal
- Write scenarios in domain language a non-developer can use unaided.
- The logic is also a pure module with no I/O, in the project's language, saved as `<storage>/logic.<ext>`. It is the part to lift into the real codebase.
- Stays a prototype: no tests, and in-memory state with no real database or API unless persistence is the question.
