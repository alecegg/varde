# TypeScript cognitive complexity interpretations

The TypeScript extractor emits the shared cognitive-complexity flow events for
conditionals, loops, ternaries, catches, switches, logical sequences, labeled
jumps, and recursion. Plain `else` branches are events; an `else if` chain is
represented as hybrid `else_if` events without adding nesting to later chain
branches. A nested decision in an `else` body still receives the enclosing
nesting increment (`spec:170-179, 261-269, 493-518`).

Logical complexity counts a run of like binary operators once, and a changed
operator or explicit negation separates runs. Shorthand operators `?.`, `??`,
`??=`, `||=`, and `&&=` do not add cognitive points. Early returns are not
counted; labeled `break` and `continue` are (`spec:156-169, 207-243`).

Nested functions and lambdas contribute nesting when their flow events roll up
to the containing function. A function whose top-level statements are only
declarations gets a `compensating_usage` marker, so its nested callable starts
at nesting zero. Calls, loops, and conditionals at top level make it ordinary
usage (`spec:261-291, 415-446`). The Appendix A declaration-only example scores
1 from its assigned function's `if`; the example with a top-level `if` scores
3 (top-level `if` +1, nested function's `if` +2). A top-level call such as
`xs.forEach(x => { if (x) g(); })` is also unmarked and scores 2
(`spec:415-446`).

The recursion matcher binds direct and qualified self-calls, closure calls to
the enclosing function, and same-file cycles. Calls through another receiver
do not bind to the current callable. TypeScript overload signatures share one
implementation body, so a separate overload-delegation case is not applicable
(`spec:230-237`).
