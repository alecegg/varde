# Elixir cognitive complexity interpretation

The specification explicitly covers logical operator runs, recursion, jumps,
nested lambdas, and structural/hybrid branches (`spec:207-243`, `267-291`,
`491-518`). It does not name Elixir's `cond`, `with`, comprehensions, or
function-head guards. The choices below use the nearest described construct
while preserving pre-change cyclomatic and `max_nesting` behavior.

## Elixir mappings and interpretations

- `if` and `unless` are structural decisions. A plain `else` emits
  `else_branch` on the keyword only, so it adds one without raising the body
  nesting. A conditional directly inside an `if`/`unless` `else` is emitted as
  `elseif_statement`, preserving the branch-chain nesting rule
  (`spec:176-179`, `491-518`).
- `case` is the switch analogue: its container adds one cognitive point and
  its `case_item` arms remain cyclomatic (`spec:196-205`, `491-501`).
- `cond` is an ordered conditional chain. Since the spec does not name it, each
  clause adds one hybrid point by analogy to `if`/`else if`; the existing
  `case_item` events remain in place for cyclomatic compatibility, and an
  additional shared `cognitive_decision` marker scores each clause without
  changing legacy file complexity. A `legacy_nesting` marker preserves the
  old `case_item` nesting effect for nested decisions in alternatives. The
  outer event is named `elixir_cond` and ignored cognitively. A nested decision
  in a clause inherits the hybrid clause's nesting level.
- `with` itself is ignored as a sequence of matches; its `else` alternatives
  add one each by analogy to hybrid `else` branches (`spec:176-179`). The
  fixture pins a one-clause `with ... else` at one point.
- `for` comprehensions are shorthand and add no cognitive point. Boolean
  sequences in filters still score (`spec:155-168`, `207-229`). The extractor
  renames its existing event to `elixir_comprehension` with `LegacyOnly`, so
  the previous cyclomatic and `max_nesting` behavior is retained.
- Each `rescue` or `catch` clause adds one. `try` and `after` add zero
  (`spec:190-203`, `491-518`).
- `fn` creates a callable boundary and adds one nesting level to its contents;
  `&function/arity` captures have no body and do not create a separate
  callable (`spec:267-291`).
- Each `def`/`defp` clause is an independent callable. The recursion matcher
  uses the containing module, function name, and arity. An unqualified
  same-module call and `__MODULE__.function/arity` can bind; a call through
  another receiver cannot. Calls in a lambda belong to the enclosing named
  function. Each member of a same-file cycle gets one marker
  (`spec:230-237`; plan recursion rule).
- The pre-plan extractor emitted one `unknown_multi_clause_grouping` control
  entity for each function clause with a same-name sibling. Those four legacy
  rows remain as `elixir_unknown_multi_clause_grouping` with the same spans and
  an ignored role, preserving `files.complexity` without globally remapping
  the same name emitted by Haskell.
- An `elseif_statement` replaces the old nested `if` event for cyclomatic and
  cognitive scoring. A co-spanned `legacy_nesting` marker preserves the old
  `max_nesting` contribution without changing `files.complexity` or cyclomatic
  complexity. The `cond` fixture's old max-nesting parent was its `case_item`
  arm, so those alternative spans also carry `legacy_nesting` when needed.
- `when` guards currently emit a structural legacy event. The Elixir extractor
  now names it `elixir_guard_statement` and assigns `LegacyOnly`: cyclomatic
  and `max_nesting` retain the prior count, while cognitive complexity adds
  zero. The unique name matters because flow-role registrations are global and
  Java also emits `guard_statement`.
- `receive` clauses use the same `cognitive_decision` marker so their cognitive
  branch points do not add legacy file-complexity entities.
- A `defmodule` inside a function body parses as a nested module declaration
  in this grammar. Its function is a nested callable for roll-up, demonstrated
  by `class-in-method`; this documents parser behavior, not Elixir compilation
  of the fixture.

## Not applicable

- `ternary`: Elixir's `if` is a macro with `do`/`else` branches, not a ternary
  expression.
- `early-return-zero`: functions return their final expression; there is no
  return statement.
- `null-coalescing-zero`: `||` is a binary logical operator; Elixir has no
  null-coalescing operator (`spec:160-168`).
- `named-nested-function`: nested `def`/`defp` definitions are not allowed;
  `fn` closures are covered separately. The official [Module documentation]
  states this for function definitions inside `@on_definition` callbacks.
- `compensating-usage` and `compensating-usage-callback`: Appendix A's
  exception is specified for JavaScript/TypeScript and Python
  (`spec:415-490`).
- `goto-or-labeled-jump` and `multi-level-break`: Elixir has no `goto`, labels,
  or numbered/labeled `break`/`continue` (`spec:238-243`, `491-499`).
- `preproc-conditional` and `preproc-extern-c`: Elixir has no source
  preprocessor or C linkage syntax (`spec:175`, `281-291`).
- `spec-example-large`: the example depends on nested imperative loops and a
  labeled `continue`; Elixir comprehensions are shorthand, and the language
  has no corresponding jump (`spec:155-168`, `238-243`, `491-499`).

[Module documentation]: https://elixir.hexdocs.pm/1.2.4/Module.html
