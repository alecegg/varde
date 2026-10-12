# Solidity cognitive complexity interpretation

Solidity's `if`, `else if`, `else`, loops, ternaries, catches, and Boolean
operator sequences use the spec's ordinary increments. A plain `else` emits a
complexity-only `else_branch` at the `else` token. An `else if` emits
`elseif_statement` at its `if` token, without a second `else_branch`. Keeping
these hybrid markers outside their bodies makes nested decisions in either
branch one level under the root `if`, per the plan's accepted OQ5 reading
(`spec:176-179`, `502-518`). A ternary in an `if` condition is inside that
structure and receives its nesting increment (`spec:502-518`; plan
interpretation).

Each `catch_clause` scores once. `try` itself adds nothing; Solidity has no
`finally` clause (`spec:190-195`). Early returns add nothing (`spec:238-243`).
Modifiers are callable scopes, like functions: control flow in a modifier gets
its own metric, while applying a modifier does not add a point. Constructors,
fallbacks, and receive functions are also separate callables with synthetic
names because the grammar does not give them a `name` field.

Solidity's `assembly_statement` continues to emit its historical `inline_yul`
control-flow entity so `files.complexity` stays stable. Its role is `Ignored`,
preserving its pre-change cyclomatic and `max_nesting` values while avoiding an
unknown-role confidence downgrade. Yul `if`, `for`, and `switch` statements
emit `cognitive_decision` events, which do not affect legacy metrics. Each is
scored by analogy to the matching spec structure; a Yul switch with multiple
cases is one decision (`spec:173-175`, `196-205`, `493-518`). Yul function
definitions are nested callable scopes. A decision inside one contributes to
the containing Solidity callable with one nested-callable increment and also
gets its own metric (`spec:267-291`, `502-518`).

Bare self-calls and `this.f()` can form recursion cycles; the latter is a
self-like qualified call. A call through another receiver does not bind to the
current contract method. Arity prevents a call to a distinct overload from
being treated as recursion. Same-file cycles add one point per member; an
unresolved peer in another file adds none (`spec:230-237`, `491-501`; plan
resolver interpretation).

Solidity has no null-coalescing operator, lambda literal, labeled or numbered
break/continue, `goto`, preprocessor conditionals, collection comprehension,
query clauses, or `finally` block. Its `?:` is a ternary, not an Elvis or
null-coalescing form (`spec:155-168`). Compensating usages are the JavaScript
and Python forms in Appendix A (`spec:415-490`). The large worked example in
the plan is reserved for Java, JavaScript, and C#.
