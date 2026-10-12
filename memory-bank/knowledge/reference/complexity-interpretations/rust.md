# Rust cognitive complexity interpretations

This page records Rust-specific mappings and choices for the shared Sonar
Cognitive Complexity rules. The conformance fixture is
`clis/code/crates/varde-code/tests/fixtures/complexity/rust/`.

| Construct | Scoring choice | Spec basis |
|---|---|---|
| `if let` and its `else` | Treat `if let` as `if` (+1) and a plain alternative as `else` (+1). | `spec:491-518`; tree-sitter represents `if let` as `if_expression` with a let condition. |
| Rust `if` expression as a value (ternary analogue) | Use the value-producing `if_let_else` case to cover this matrix concept; Rust has no ternary operator. | `spec:491-518`; `if` and `else` are the nearest named alternatives. |
| `if` expression in an `if` condition | The inner condition expression receives the outer `if`'s nesting level: outer `if` +1, inner `if` +2, inner `else` +1, total 4. The fixture wraps the inner expression in parentheses to make its condition use explicit. | `spec:491-518`; the plan's “Conditions are inside their structure” interpretation applies. |
| `let ... else` | Count the `else` branch as a hybrid increment (+1); it raises nesting for structures in its block but receives no nesting increment itself. The spec does not name this Rust syntax, so this follows `else` by analogy. | `spec:176-179, 491-509` |
| `else if` | Count the branch once as `ElseIf` (+1), without a nesting increment. Clip each `if_expression` event to its consequence so an earlier branch does not nest later branches. | `spec:176-179, 502-518`; the branch-depth fixture pins the plan's OQ5 reading. |
| `match` and its arms | The `match_expression` is one decision container (+1); `match_arm` nodes remain cyclomatic arms and add no cognitive points. | `spec:196-205, 491-500` |
| `loop`, `while`, `for` | Map Rust loop expressions to structural decisions; nested loops receive the usual depth increment. | `spec:491-518` |
| Closures and nested functions | Add no point for the callable itself, but raise nesting for its contents. Nested callable events roll up into enclosing functions per the shared containment rule. | `spec:267-291` |
| Local `struct`/`impl` inside a function | Treat a method in a local `impl` as a nested named callable; its flow rolls up with one additional nesting level. The fixture confirms the grammar accepts this item placement. | `spec:267-280` |
| Rust `?` | Score zero by analogy to null-coalescing shorthand. | `spec:163-168` |
| `||=` | Rust has no logical-OR assignment operator spelled `||=`; `|=` is bitwise assignment, and `||` is logical OR or closure syntax. No operator event is emitted for assignment shorthand. | The null-coalescing shorthand principle at `spec:163-168` is the closest spec basis; Rust syntax has no direct counterpart. |
| Logical operator sequences | Count each run of `&&` or `||` once. A negated nested run starts a new sequence through a `negation_break` marker. | `spec:207-229, 254-256` |
| Labeled `break` and `continue` | Emit a cognitive-only `labeled_jump` (+1). An unlabelled jump remains zero. A loop's own label does not change the loop's structural role. | `spec:238-243, 491-501` |
| Recursion in free functions and `impl` methods | Count once for each callable in a direct or same-file cycle. Bare references bind to free functions in their lexical scope; `self.f` and `Self::f` bind to the enclosing impl method, while another receiver does not. Calls inside closures belong to the enclosing named function. | `spec:230-237, 491-501`; owner and arity behavior follows the plan's shared resolver contract. |

Rust has no ternary operator, catch/finally form, or C preprocessor directives.
The ternary matrix concept is covered by the value-producing `if_let_else`
case; catch/finally and preprocessor entries are `n/a`. Matching a `Result` is
ordinary `match` syntax.
