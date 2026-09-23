# Logic Track

Create one file: `<storage>/logic.html`. It is self-contained HTML with no
build step, framework, or server. Anyone can open it and use the state model.
Read `logic-format.md` for the structure.

## Steps

1. **State the question.** At the top of the visible page, name the exact state
   model and question being tested. Do not hide it in a code comment.
2. **Isolate the logic in a pure module.** Use a reducer, state machine, or
   pure functions. Do not access the DOM. See `logic-format.md` and Gotchas.
   Choose the shape that fits the question:
   - Use a reducer for discrete actions over one state value.
   - Use an explicit state machine when legal actions depend on current state.
   - Use pure functions when no ongoing state exists.
3. **Write the page in domain language**, not code, using the required sections
   in `logic-format.md`. Include the happy path, a tricky edge case, and an
   action that should be illegal. Test more than the obvious flow.
4. **Show, ask, revise.** Show the file path. Add an Artifact or
   `mcp__visualize` preview when detected, as in the Visual track. Ask one
   targeted question about a missing action, scenario, or visible state field.
   Wait for the answer, then revise in place. Do not increment a version number;
   `logic.html` remains the one file across every round.

## Anti-patterns

- Do not add tests. A prototype that needs tests has stopped being a prototype.
- Do not use a real database or API. Keep state in memory unless persistence
  itself is the question.
- Do not generalize beyond the question asked. Do not ask, "what if we also
  supported X later."
- Do not use a framework, bundler, or dev server. Keep one file that opens by
  double-click and can be shared.
