# PHP cognitive complexity interpretations

The spec rules below are primary; the analogies resolve PHP-specific syntax where it is silent.

| Construct | Interpretation | Basis |
|---|---|---|
| `elseif` and `else if` | Each branch contributes one hybrid point. An `if` in the branch body stays one level beneath the root `if`; the branch header does not add a body nesting level. | `spec:176-179, 491-518`; nearest rule is the spec's `else if` branch. |
| Alternative `if: ... endif;` syntax | Score as the same `if`, `else if`, and `else` structures as brace syntax. | `spec:176-179, 491-518`; syntax form does not change the flow structure. |
| `match` expression | One decision-container point for the match and no point per arm, following the `switch` rule. | `spec:196-205`; the spec is silent on PHP `match`, whose single-value arm selection is nearest to `switch`. |
| `??` and short ternary `?:` | Both score zero. `??` is a null-coalescing operator; short ternary is the Elvis-style shorthand form. Keep the legacy ternary event for cyclomatic complexity. | `spec:155-168`; the spec explicitly ignores null-coalescing and is silent on PHP's short ternary, so use the shorthand analogy. |
| `goto`, `break N`, `continue N` | Each goto and each numbered jump adds one point; an ordinary break or continue adds none. | `spec:238-243, 498-499`. |
| Recursion | Same-file recursive free functions and methods through `$this->f()`, `self::f()`, and `static::f()` add one point per callable in the cycle. Calls on another receiver do not bind as self-recursion. | `spec:230-237`; PHP's receiver/scope forms identify the current method. |
| Closures with `use`, arrow functions, nested functions, local classes | These introduce callable boundaries without a direct point; flow inside them increases nesting when it rolls up to an enclosing callable. Each callable also receives its own metric. | `spec:267-291`. |
| `try` and `finally` | Neither adds a point; each `catch` adds one, regardless of the number of exception types. | `spec:190-203`. |
| Compensating usage | Not applicable: PHP attributes are metadata and PHP has no JavaScript/TypeScript decorator or Python decorator compensating-usage rule. The negative callback matrix row tests that same rule and is not an independent PHP construct. | The spec's exception is in `spec:415-490`; PHP attributes do not match that callable shape. |
| Recursion overload delegate | Not applicable: PHP has no method-overload declarations by parameter signature. Optional and variadic parameters belong to one declaration, not separate overloads. | `spec:230-237` describes recursion but does not define overload syntax; the PHP grammar has no overloaded declaration form. |
| Preprocessor and extern-C rows | Not applicable: PHP has no conditional preprocessor or C linkage region. | The spec's preprocessor examples are `spec:176-179`; PHP has no matching syntax. |
| Comprehension/query row | Not applicable: checked the PHP grammar; it has no comprehension or query-expression syntax. Array functions and closures are ordinary calls. | The spec is silent on PHP collection syntax; there is no matching construct in the PHP grammar. |
