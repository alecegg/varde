# Go Cognitive Complexity interpretations

This page records Go-specific choices for the plan's hand-derived Cognitive
Complexity conformance suite. The Go grammar reference is tree-sitter-go 0.25.0.

| Construct | Scoring choice | Spec basis |
|---|---|---|
| `if`, `else if`, and `else` | Count `if` as structural (+1), an `else if` as hybrid (+1), and a plain `else` as hybrid (+1). Clip each `if` event to its consequence so chained alternatives stay at the root branch depth. | `spec:176-179, 491-518`; Go's `if_statement.alternative` is either a block or another `if_statement`. |
| Expression switch, type switch, and `select` | Count each container once (+1); its `case`/`default` arms remain cyclomatic only. Treat `select` as the Go multi-branch counterpart to `switch`. | `spec:190-205, 491-500`; type switch and `select` are Go-specific analogues. |
| `goto`, labeled `break`, and labeled `continue` | Emit a complexity-only `goto_jump` for `goto`; emit `labeled_jump` only when `break` or `continue` has a label. Label declarations and unlabelled jumps add no cognitive point. | `spec:238-243, 491-501`; labeled jumps are not part of the legacy cyclomatic count. |
| Function literals | The literal adds no point itself and raises nesting for its body. Its callable row scores its body from its own root. | `spec:267-291` |
| Function literal in an `if` condition | A closure in the outer condition has one callable nesting level; an `if` in that closure is also inside the outer `if`. In `condition_nesting`, the outer `if` adds 1 and the closure's inner `if` adds 3, total 4. | `spec:267-291, 491-518`; the condition nesting depth follows the plan's accepted “Conditions are inside their structure” interpretation. |
| Free-function and receiver-method recursion | Count once per function in a same-file cycle. Bare calls resolve to free functions; `r.f()` resolves to the current method only when `r` is its receiver variable. Calls on another receiver do not bind. | `spec:230-237`; Go receiver ownership follows the plan's shared resolver contract. |
| `defer` and `recover` | Neither is a catch construct; ordinary defer/recover use adds no catch increment. | `spec:491-518`; Go syntax has no `try` or `catch` statement. |

The Go grammar confirms no conditional expression/ternary operator, no
`try`/`catch` syntax, no null-coalescing operator, no nested function
declarations, and no local method declarations. Go build constraints are
comments rather than C-style preprocessor regions. The plan's compensation
exceptions do not apply to Go, which has no comprehension/query-clause syntax;
the large Sonar example is reserved for Java, JavaScript, and C#.
