# Python cognitive complexity interpretations

This page records Python mappings where the spec is language-neutral or silent. It follows the Sonar Cognitive Complexity spec of record, the Sonar Cognitive Complexity white paper (G. Ann Campbell, SonarSource, version 1.7, 29 August 2023).

## Branches and loops

- `if` contributes one structural point. A directly chained `elif` contributes one hybrid point, and its body remains one nesting level under the root `if`. A plain `else` attached to an `if` contributes one hybrid point; its body is one level under the root `if` (`spec:176-179, 491-518`). The extractor limits the `if` event to its consequence so sibling branches do not create extra nesting.
- `for` and `while` contribute one structural point, with nested decisions increasing by one per level (`spec:491-518`). Python `for`/`while` `else` suites and `try` `else` suites contribute zero: the spec defines the `else` hybrid for `if`/`else if` chains but is silent on completion suites, which run after normal loop or try completion rather than choosing a branch (`spec:176-179, 190-203`).
- `match` contributes one container point, by analogy to `switch`; `case` arms add no cognitive points (`spec:196-205`). Match arms remain legacy cyclomatic branches.
- Conditional expressions contribute one structural point, increasing with nesting (`spec:510-518`).

## Exceptions and shorthand

- Each `except` clause contributes one point, by analogy to the spec's per-`catch` rule. `try`, `finally`, and `try`-`else` contribute zero (`spec:190-203`).
- Comprehension and generator `for`/`if` clauses are shorthand and contribute zero cognitive points, by analogy to the spec's ignore-shorthand principle (`spec:155-162`). Their legacy cyclomatic branches are preserved with `LegacyOnly` flow roles. Boolean operators inside a comprehension still form cognitive logical sequences (`spec:207-229`).
- `and` and `or` sequences contribute one point per run of the same operator; changing operator starts another run (`spec:207-229`). A `not` operator around a nested boolean sequence breaks parent-run grouping, consistent with the spec's negation example (`spec:254-256`).
- Python decorators receive the spec's narrow compensating-usage exception: a function body containing only a nested function definition and a return does not add callable nesting to the nested function's events (`spec:450-490`). An additional statement disqualifies the exception. The same syntax applies when the returned nested function is a callback.

## Callables and recursion

- Nested named functions and lambdas add no structural point; their contained events increase nesting by one in the enclosing callable. Their own metrics start at nesting zero (`spec:267-291`).
- A class declared inside a function is represented by Python grammar and receives its own class-method callable. Class declarations have no structural point; the method's events are attributed to that method and roll up according to callable nesting (`spec:267-291`).
- A same-file direct or mutual recursive call contributes one point per recursive callable, not per call site (`spec:230-237`). Python `self.f(...)` and `cls.f(...)` references can bind to methods in the same class. A call on another receiver is not self-recursion. The per-file matcher cannot resolve a peer absent from the fixture, so that cross-file reference contributes zero (`spec:230-237`). Python does not declare distinct overloads by arity; redeclaring a name rebinds it, so the overload/delegate matrix case is not applicable.

## Grammar-based n/a cases

- `null-coalescing-zero`: Python has no null-coalescing or optional-chaining operator production (`spec:163-168`).
- `goto-or-labeled-jump`: Python has no goto or labeled jump production (`spec:238-243`).
- `multi-level-break`: Python `break` and `continue` have no label or numeric level syntax (`spec:238-243`).
- `preproc-conditional` and `preproc-extern-c`: Python has no preprocessor conditional or C-family extern-C linkage grammar (`spec:175, 286-291`).
