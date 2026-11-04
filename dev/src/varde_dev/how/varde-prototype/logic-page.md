---
topic: varde-prototype/logic-page
version: 1
summary: Lay out logic.md as a static scenario page plus a pure module
---

- The logic is a pure module in the project's language, saved as `<storage>/logic.<ext>`. It does no I/O.
  Use a reducer for discrete actions over one state value, or a state machine when legal actions depend on the current state. With no ongoing state, use pure functions.
- The logic page holds, top to bottom:
  1. Title and question: one paragraph naming the exact state model and question under test.
  2. State-transition table: state, action, next state.
  3. Guided scenarios: for each, a plain-language situation and a table of state, action and result.
- Use domain language in states, actions and scenarios, so a non-developer can read the page unaided.
- Each round, probe one missing action, scenario, or state field.
- Export with `varde learn docs build`; live clicking is not offered.
