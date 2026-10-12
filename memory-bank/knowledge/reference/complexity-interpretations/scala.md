# Scala cognitive complexity interpretation

The Scala suite follows the published increments for conditionals, loops,
`match`, catches, logical sequences, and recursion (`spec:190-229`,
`230-243`, `491-518`). This page records the Scala syntax mappings and the
places where the spec needs a language-specific interpretation.

## Syntax mappings

- `if` expressions emit a structural event. A direct `else if` is a hybrid
  event; a plain `else` is also a hybrid event. Each event spans only its
  branch, so nested branch bodies receive one nesting level (`spec:176-179`,
  `491-518`; plan decision OQ5).
- `match` is the Scala switch analogue: the `match` adds one structural point,
  while its case clauses add no cognitive points (`spec:196-205`, `491-501`).
- A `catch` expression with multiple `case` alternatives emits one catch
  event. `try` and `finally` add no points (`spec:190-203`, `491-501`).
- `&&` and `||` each form logical sequences, including in conditions,
  comprehensions, and call arguments. Negation separates adjacent runs by the
  accepted logical-sequence interpretation (`spec:207-229`, `254-256`).
- Lambdas, nested `def`s, and methods in local classes or objects raise the
  callable nesting level. Their own metrics remain scoped to their own bodies
  (`spec:267-291`, `491-518`). Partial-function case blocks use the same
  method-like boundary by analogy to lambdas.
- Recursion is resolved among methods scoped to the same class, object, or
  trait. Each method in a same-file cycle receives one point, independent of
  call count (`spec:230-237`; plan decision OQ9).

## Comprehensions

A `for` expression with `yield` is treated as a comprehension shorthand:
generators and guards add no cognitive points, while Boolean operator
sequences inside them still count (`spec:155-168`, `207-229`; plan decision
on comprehension shorthand). A `for` expression without `yield` remains a
loop and receives the normal structural and nesting increments
(`spec:174-179`, `491-518`). The grammar uses one `for_expression` node for
both forms, so the extractor distinguishes them by the `yield` token.

## Not applicable constructs

Scala has no ternary operator, dedicated null-coalescing operator, goto or
label-target jumps, numeric/labeled multi-level breaks, or source
preprocessor conditionals (`spec:160-168`, `238-243`, `491-501`). Its
`Option.getOrElse` API is an ordinary call. The Appendix A compensation
examples describe JavaScript declarative wrappers and Python decorators,
neither of which is a Scala idiom (`spec:415-490`).
