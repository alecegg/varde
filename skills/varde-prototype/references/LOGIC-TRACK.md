# Logic Track

The deliverable is one file: `<storage>/logic.html`, a self-contained HTML document with no build step, no framework, and no server — anyone opens it by double-click and drives the state model by clicking buttons. See `LOGIC-FORMAT.md` for the full document structure.

## Steps

1. **State the question.** Write one paragraph, at the top of the visible page (not just a code comment), naming the exact state model and question being tested — "does cancelling a partially-shipped order correctly split the refund" not "test the order model." A logic prototype that answers the wrong question is pure waste.
2. **Isolate the logic in a pure module** (reducer, state machine, or pure functions, no DOM access — see `LOGIC-FORMAT.md` and Gotchas). Pick whichever shape fits the question (reducer for discrete actions over one state value; explicit state machine when "which actions are legal right now" is itself part of the question; plain pure functions when there's no ongoing state) rather than whichever is easiest to wire up.
3. **Write the page in domain language**, not code, per the required sections in `LOGIC-FORMAT.md`. Choose walkthrough scenarios that stress the awkward cases — the happy path, a tricky edge case, an action that should be illegal — not just the obvious flow.
4. **Show, ask, revise.** Show the file path (plus an Artifact/mcp__visualize preview if detected, same convention as the Visual track), ask one targeted question about what to add or adjust (a missing action, a new scenario, a state field that should be visible), wait for the answer, revise in place. There is no version number to increment — `logic.html` is the one file across every round.

## Anti-patterns

- No tests — a prototype that needs tests has stopped being a prototype.
- No real database or API — in-memory state only, unless persistence itself is the question.
- No generalizing beyond the question asked — no "what if we also supported X later."
- Don't let the pure module reach into the DOM or button handlers — that breaks the "lifts directly into the real codebase" property that makes this worth doing.
- Don't reach for a framework, bundler, or dev server — one file, double-clickable, is what makes it shareable.
