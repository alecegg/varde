# Lua cognitive complexity interpretations

The conformance fixture is `clis/code/crates/varde-code/tests/fixtures/complexity/lua/`.
Cognitive values follow the Sonar cognitive-complexity spec; Lua-specific choices
below use the plan's accepted interpretations where the spec is silent.

## Construct interpretations

| Construct | Interpretation | Basis |
|---|---|---|
| `if` / `elseif` / `else` | Each branch adds one point. `elseif` and plain `else` are hybrid branches; descendants stay at the root `if` body's nesting level. Lua's `if_statement`, `elseif_statement`, and `else_statement` spans include branch bodies, so the emitted hybrid event ends at its body start. The structural `if` span is unchanged. | `spec:491-518`; hybrid behavior `spec:176-179, 747-754`; plan OQ5 |
| Numeric/generic `for`, `while`, `repeat ... until` | Each loop is a structural decision and raises nesting. Numeric and generic loops share `for_statement`; `repeat_statement` is the Lua post-test loop analogue. A bare `do ... end` is only a block and adds nothing. | `spec:491-518` |
| Logical operators | Each contiguous binary `and` or `or` run adds one. A change from `and` to `or` starts another run. Unary `not` between same-operator runs starts a new run. The Lua `a and b or c` idiom is therefore a logical mix, not a ternary. | `spec:207-229, 254-256`; null-coalescing/zero constructs `spec:160-168` |
| `goto LABEL` | `goto_statement` maps to Jump and adds one cognitive point. Its destination `label_statement` is not a cognitive event. Both existing control-flow rows remain in the legacy file-complexity count. | `spec:238-243, 491-501`; plan legacy-count rule |
| Closures in conditions | A closure inside an `if` condition is inside that structure. In the fixture, the outer `if` adds 1; its condition closure raises callable nesting by 1; an `if` inside that closure therefore adds 3. | `spec:502-518, 267-291`; plan condition-nesting interpretation |
| Recursion | Count one point per function in a same-file recursive cycle, regardless of call count. Top-level/local functions use free-function lookup. `M.f` and `M:m` declarations bind matching `M.f` and `self:m()` calls; calls through another receiver do not bind. Calls from an anonymous closure are attributed to the enclosing named function. | `spec:230-237`; plan recursion rules |
| Function literals | A function literal raises nesting for its parent's rolled-up events and keeps its own metric. A named local function is a separate nested function. | `spec:267-291` |

## Matrix entries marked n/a

| Matrix id | Reason |
|---|---|
| `switch-once` | Lua has no switch or case-container syntax; table-based dispatch is ordinary data selection. |
| `ternary` | Lua has no ternary operator. Its `and`/`or` idiom is covered by `logical-run-mixed`. |
| `catch-once`, `try-finally-zero` | Lua has no catch/finally regions; `pcall` and `xpcall` are ordinary calls that return status values. |
| `null-coalescing-zero` | Lua has no null-coalescing operator; `or` is logical and covered by `logical-run-mixed`. |
| `class-in-method` | The grammar has no class declaration. Tables and metatables are conventions, not structural local classes. |
| `compensating-usage`, `compensating-usage-callback` | The plan's compensation rules cover JavaScript-like declaration-only functions and Python decorators; Lua has neither the rule's forms nor callback compensation marker. |
| `multi-level-break` | Lua `break` has no label or numeric level. `goto` is covered separately. |
| `recursion-overload-delegate` | Lua has no function overloading by signature. Reassigning a name is replacement, not overload delegation. |
| `preproc-conditional`, `preproc-extern-c` | Lua has no preprocessor directives or extern-C linkage syntax. |
| `comprehension-or-query` | Lua has no comprehension/query clause syntax; iterator calls and loops are ordinary calls and loops. |
| `spec-example-large` | The spec's large example is defined for Java, JavaScript, and C# only. |

The spec's `getWords` switch example cannot be represented directly in Lua; the
fixture covers `spec-example-small` with the `sumOfPrimes` loop/goto example.
