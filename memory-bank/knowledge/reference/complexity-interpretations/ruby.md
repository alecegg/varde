# Ruby cognitive complexity interpretations

This page records Ruby mappings where the spec is language-neutral or silent. It follows the Sonar Cognitive Complexity spec of record, the Sonar Cognitive Complexity white paper (G. Ann Campbell, SonarSource, version 1.7, 29 August 2023).

## Branches and loops

- `if` and `unless` contribute one structural point. A directly chained `elsif` and its final `else` each contribute one hybrid point. Their bodies stay one level under the root conditional, so nested decisions there receive the root conditional's nesting increment only (`spec:176-179, 491-518`). The extractor limits `elsif` events to their conditions and `else` events to the keyword; the root conditional covers the alternatives.
- Statement modifiers such as `value if condition` and `value unless condition` contribute the same point as their block forms. The conditional expression `condition ? left : right` contributes one point, with nesting as for other structural decisions (`spec:491-518`).
- Ruby `case` contributes one decision-container point; `when` arms contribute none (`spec:196-205`).
- Native `for`, `while`, and `until` forms contribute one point and raise nesting (`spec:491-518`). The common `loop do` form is a method call with a block in Ruby's grammar, not a loop syntax node; it contributes no separate loop point. Its block is a nested callable, so events in it gain the callable nesting increment (`spec:267-291`).

## Exceptions and logical operators

- Each `rescue` clause contributes one catch point, regardless of how many exception classes appear in its exception list. `begin` and `ensure` add no cognitive points, by analogy to `try` and `finally` (`spec:190-203`). The pre-change cyclomatic baseline also counts a branch for rescue-bearing `begin`; the extractor retains that as `rescue_begin` with the `LegacyOnly` role. This keeps legacy cyclomatic values while the cognitive score remains one catch.
- A Ruby rescue modifier is a structural decision. Plain `return`, `break`, `next`, `redo`, and `retry` are zero-cost jumps; none carries the label or numeric level required for a labeled-jump increment (`spec:238-243, 491-501`).
- `&&`/`and` and `||`/`or` each form one cognitive point per same-operator run. Unary `!` and `not` add no point, but separate nested runs as in the spec's negation example (`spec:207-229, 254-256`).
- `||=` and safe navigation `&.` add zero, by analogy to null-coalescing shorthand (`spec:160-168`). A plain `||` remains a logical operator and is not treated as null coalescing.

## Callables, classes, and recursion

- Blocks, `Proc` blocks, and lambda bodies are callable boundaries. They add no point themselves; their events receive one nesting level in the enclosing method, and each boundary keeps its own metric (`spec:267-291`). This also applies to a callback block inside a top-level call: Ruby has no compensating-usage exception, so an `if` inside the block contributes two to its enclosing method.
- Nested `def` declarations and methods inside a class declared in a method roll up to the containing method with one callable nesting level. `class << self` is a `singleton_class` scope with the same callable nesting behavior. `Class.new` is a method call whose block is a callable; the call itself adds no structural point (`spec:267-291`).
- Recursion is one point per method in a same-file cycle, not per call site (`spec:230-237`). Bare calls bind within the same Ruby class owner; `self.method(...)` is self-recursion, while `other.method(...)` is not. Calls inside blocks still belong to the enclosing named method. A missing peer in this one-file fixture cannot resolve and contributes no recursion point.
- Ruby does not overload methods by signature: redefining a method name replaces its prior binding, rather than selecting an overload by arity. The overload/delegate matrix case is therefore not applicable.

## Grammar-based n/a cases

- `compensating-usage`: the spec's exception is limited to JavaScript-style declarative functions and Python decorators (`spec:415-490`). Ruby has neither form.
- `goto-or-labeled-jump`: Ruby has no goto statement or jump target labels; labels used in hash syntax are not jump targets (`spec:238-243`).
- `multi-level-break`: `break` and `next` accept no label or numeric nesting depth; `break`'s optional value is an expression, not a level (`spec:238-243`).
- `preproc-conditional` and `preproc-extern-c`: Ruby has no C-family preprocessor conditional or extern-C linkage syntax (`spec:175, 286-291`).
- `comprehension-or-query`: Ruby has no comprehension or query-clause grammar. Enumerable methods and their blocks are ordinary calls and callable bodies (`spec:155-168`).
- `spec-example-large`: the large worked example is defined only for Java, JavaScript, and C#; the Ruby fixture covers the applicable small `case` example by analogy (`spec:328-339`).
