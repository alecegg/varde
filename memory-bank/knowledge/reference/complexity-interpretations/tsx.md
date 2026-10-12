# TSX cognitive complexity interpretations

TSX uses the TypeScript flow-event and recursion rules documented in
`typescript.md`. JSX markup is not itself a cognitive-complexity construct.
Logical operators inside JSX expressions remain ordinary binary logical
sequences: for example, `cond && <A />` adds one sequence point, and a following
different operator begins another run (`spec:207-229`).

Conditionals, loops, ternaries, catches, switches, nesting, compensating usage,
labeled jumps, and recursion follow the TypeScript interpretations
(`spec:170-179, 230-243, 261-291, 415-446, 493-518`). The two Appendix A
compensating-usage examples score 1 for the declaration-only outer function and
3 when a top-level `if` makes the outer function non-declarative; a top-level
callback call is the negative shape and scores 2 (`spec:415-446`).
