# JavaScript cognitive complexity interpretations

The JavaScript extractor maps conditionals, loops, ternaries, switches,
catches, logical sequences, labeled jumps, and recursion to the shared scoring
roles. Plain `else` branches add one hybrid point without a nesting increment;
`else if` chains remain hybrid branches. The event span ends at its branch body
so sibling branches do not nest one another (`spec:176-179, 491-518`).

Logical runs count once per sequence of like binary operators. A changed
operator or an intervening `!` begins another sequence. Nullish coalescing,
optional chaining, `??=`, and `||=` are shorthand and score zero; early returns
score zero, while labeled `break` and `continue` add one
(`spec:155-168, 207-243`).

Nested functions and arrow callbacks contribute nesting to the containing
function but keep their own metric row (`spec:267-291`). The two JavaScript
Appendix A examples pin compensation: a declaration-only outer function scores
1 from its assigned function's `if`; adding a top-level `if` makes the outer
ordinary and the nested `if` scores at depth one, for total 3. A top-level call
such as `xs.forEach(x => { if (x) g(); })` is also unmarked and scores 2
(`spec:415-446`).

Generator functions and async arrows use the same callable nesting rules as
other functions and arrows (`spec:267-291`). Class methods are separate
callables and their flow rolls up through containing functions by span
containment (`spec:267-291`).

The recursion matcher binds direct self-calls, `this.method(...)` calls,
closure calls to the enclosing function, and same-file cycles. A different
receiver does not bind; the matcher has no type resolution. JavaScript has no
distinct overload declarations, so the overload-delegation case is `n/a`
(`spec:230-237`). The cross-file fixture calls a documented but absent peer and
scores zero because the resolver has only the current file.

The `model.js` example is preserved with ordinary JavaScript quotes in the
fixture. Its `save` function-expression callable scores 20; the two nested
callback rows are scored independently and roll up into that total
(`spec:690-738`).
