# Kotlin cognitive complexity interpretations

Kotlin `if_expression` uses the specification's `if` increment. A plain `else`
emits one hybrid point; an `else if` emits one hybrid point and does not also
emit an `else` point. Their bodies follow the spec's branch nesting model
(`spec:176-179, 491-518`). Event spans end at each `if` consequence so branch
bodies do not nest sibling branches.

`when_expression` maps to the spec's `switch`: the expression adds one
cognitive point and its `when_entry` nodes are decision arms, not extra
cognitive points (`spec:196-205, 491-501`). Kotlin's safe-call `?.` and Elvis
`?:` operators are null-handling shorthand and add zero, following the spec's
null-coalescing rule (`spec:155-168`). Kotlin has no ternary operator; its
conditional `if` expressions use the normal `if` rule.

Each `catch` adds one point, regardless of the exception type; `try` and
`finally` add none (`spec:190-203`). Binary `&&` and `||` sequences add one
point per run. A negation marker separates same-operator runs across `!`,
following the specification's sequence rule and its negated example
(`spec:207-229, 254-256`).

Labeled `break@label` and `continue@label` emit a jump point. Plain `break` and
`continue` remain ignored. `return@label` is an early exit and adds zero,
following the early-return rule (`spec:238-243, 491-501`). Lambdas and local
functions add no point themselves and raise nesting for structural decisions
inside them. Methods in local classes and anonymous object literals follow the
same nested-callable rule (`spec:267-291`). The extractor gives anonymous
object scopes a location-based synthetic owner so their member functions retain
class scope.

Recursion adds one point per member of a same-file cycle, including direct
self-calls and calls through `this` in class or object methods (`spec:230-237,
491-501`). Arity selects among Kotlin overloads. Calls through another receiver
do not bind to the current method. Extension functions are function declarations
with a receiver; the receiver participates in same-file owner matching.

`n/a` cases are the ternary-operator syntax, JavaScript/Python compensating
usage conventions, C preprocessor conditionals/linkage blocks, and query or
comprehension clauses. Kotlin has local classes, object declarations and object
literals, labeled loop jumps, `when` entries, lambdas with labels, and overloads;
those constructs are represented by cases rather than excluded.
