# Logic Track

Edit `<storage>/logic.html` in place; no iteration files.

## The page

`logic.html` is one valid, self-contained HTML document with inline `<style>`
and no external dependencies, framework, bundler, or server.

- **The logic is a pure module** in one `<script>` block: a reducer for
  discrete actions over one state value, a state machine when legal actions
  depend on the current state, or pure functions when no ongoing state exists.
  The page calls the module; the module never touches the DOM.
- **The rest is a thin shell** with these sections, top to bottom:
  1. **Title and question** — one visible paragraph naming the exact state
     model and question under test.
  2. **Current-state panel** — the full relevant state as labelled fields, not
     a `JSON.stringify` dump, re-rendered after every action.
  3. **Free-play buttons** — one always-available button per action,
     dispatching straight into the module.
  4. **Guided scenarios** — tabs, each with a plain-language description of the
     situation and what to watch for, and the scenario's steps as real
     clickable buttons. Opening a tab resets to a known initial state.

Write buttons, state fields, and scenarios in domain language so a
non-developer can use the file unaided. Cover the happy path, a tricky edge
case, and an action that should be illegal. Style plainly: clean typography,
generous spacing, one accent color, no animation.

## Rounds

Each round, ask about one missing action, scenario, or state field.

## Stay a prototype

- Add no tests; a prototype that needs tests has stopped being one.
- Keep state in memory, with no real database or API, unless persistence is
  the question.
