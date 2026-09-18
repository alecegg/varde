# Logic Track

Create one file: `<storage>/logic.html`. It is self-contained HTML with no
build step, framework, or server. Anyone can open it and use the state model.
Read `LOGIC-FORMAT.md` for the structure.

## Steps

1. **State the question.** At the top of the visible page, name the exact state
   model and question being tested. Do not hide it in a code comment.
2. **Isolate the logic in a pure module** (reducer, state machine, or pure functions, no DOM access — see `LOGIC-FORMAT.md` and Gotchas). Pick whichever shape fits the question (reducer for discrete actions over one state value; explicit state machine when "which actions are legal right now" is itself part of the question; plain pure functions when there's no ongoing state) rather than whichever is easiest to wire up.
3. **Write the page in domain language**, not code, per the required sections in `LOGIC-FORMAT.md`. Choose walkthrough scenarios that stress the awkward cases — the happy path, a tricky edge case, an action that should be illegal — not just the obvious flow.
4. **Show, ask, revise.** Show the file path (plus an Artifact/mcp__visualize preview if detected, same convention as the Visual track), ask one targeted question about what to add or adjust (a missing action, a new scenario, a state field that should be visible), wait for the answer, revise in place. There is no version number to increment — `logic.html` is the one file across every round.

## Anti-patterns

- No tests — a prototype that needs tests has stopped being a prototype.
- No real database or API — in-memory state only, unless persistence itself is the question.
- No generalizing beyond the question asked — no "what if we also supported X later."
- No framework, bundler, or dev server — one file, double-clickable, is what makes it shareable.
