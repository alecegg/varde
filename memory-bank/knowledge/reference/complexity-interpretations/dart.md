# Dart cognitive complexity interpretations

Dart `if`/`else if`/`else` branches use the spec's structural and hybrid
increments. The `else` markers stop at the branch boundary, so nested `if`
bodies stay at the root branch's nesting level (`spec:176-179, 491-518`). A
switch statement and switch expression each add one point; their cases add no
cognitive points (`spec:196-205, 491-501`). Ternary expressions add one point.
`??`, `??=`, `?.`, and cascades are shorthand and add none (`spec:155-168`).

Each `catch` handler and each `on T { ... }` handler adds one point; an
`on T catch (e)` pair is one handler. `try` and `finally` add none. A
cognitive-only handler marker spans the body so nested decisions receive the
handler's nesting increment, while legacy catch entities retain their
original spans and counts (`spec:190-203, 491-518`). Switch expressions and
type-only `on T { ... }` handlers use `cognitive_decision` because neither had
a legacy control-flow entity. Switch-expression arms add no points and do not
affect legacy metrics.

Binary `&&` and `||` runs add one point per like-operator sequence. A `!`
boundary separates a nested same-operator run (`spec:207-229, 254-256`).
Collection `if` and `for` elements are comprehension shorthand and add no
cognitive points, following the spec's ignore-shorthand principle and the
plan's comprehension interpretation (`spec:155-162`). The extractor emits no
decisions for them, preserving legacy cyclomatic and `max_nesting` values.

Lambdas and local functions add no point themselves and raise nesting for
decisions inside them (`spec:267-291`). Dart's class and mixin methods use
class-scoped recursion matching. Direct and qualified self-calls, multiple
self-calls, and same-file cycles add one point per method in the cycle;
calls through another receiver and a peer absent from the file do not bind
(`spec:230-237, 491-501`). Labeled `break` and `continue` add one cognitive
point while their original entities remain for legacy file counts. Plain
breaks, continues, and early returns add no cognitive points
(`spec:238-243, 491-501`).

The installed pre-change `varde` reports cyclomatic 4 for `switch_once`, 5
for `catch_once`, and 1 for `collection_comprehension`; `catch_once` and
`collection_comprehension` have `max_nesting` 0. The conformance fixture's
`files.complexity` remains 100.

`n/a` cases are local class declarations, Appendix A compensating-usage
conventions, same-name method overload delegation, and source preprocessor
directives/linkage blocks. Dart has no local class syntax, does not have the
JavaScript/Python Appendix A exception, does not overload methods by name, and
has no source preprocessor.
