# Haskell cognitive complexity interpretations

This page records the Haskell mappings and choices where the specification needs a language analogy. Cognitive values in the conformance fixture are derived from the spec; cyclomatic values and legacy parity were checked against the pre-change extractor.

## Branches and nesting

- `if/then/else` is the Haskell conditional. Each `if` adds one structural point; a plain `else` adds one hybrid point. An `else` whose expression is directly another `if` maps to `else if`. These choices follow `spec:169-179, 491-518`. The extractor clips each conditional event at its then expression so an else-if chain does not become nested; it retains a nesting-only marker for the old full spans so `max_nesting` remains unchanged.
- A Haskell `case` expression is a switch analogue: the whole expression scores once and its alternatives score zero cognitively (`spec:196-205, 491-518`). The grammar exposes two nested `case` control-flow nodes for one expression. The outer node remains `case`; the inner node uses the Haskell-only `case_inner` role `LegacyNesting`, retaining legacy file complexity and `max_nesting` without a second cognitive or cyclomatic contribution.
- Guard alternatives (`|`) are interpreted like an `if` followed by `else if` branches (`spec:169-179, 491-518`). Each guard adds one cognitive point. Existing guard events remain under Haskell-specific ignored/legacy roles so their pre-change cyclomatic, nesting, and file counts stay stable.
- `let/in` is a binding form rather than a branch, so it adds no cognitive point. A `where`- or `let`-bound local function is a separate callable (`spec:155-162, 267-291`). Lambdas likewise add no point themselves, but increase nesting for events in their bodies (`spec:267-291`). Nested callable events roll up into their containing callable as set out in the plan.
- A Haskell `if` expression used in an outer condition is nested inside the outer `if`, just like the condition nesting interpretation in the plan. The inner `if` therefore scores at nesting depth one, and each plain `else` still adds its own hybrid point (`spec:176-179, 491-518`).

## Logical operators, recursion, and library constructs

- Adjacent `&&` operators form one logical sequence; changing between `&&` and `||` starts another (`spec:207-229`). A `not` application containing a logical expression separates the inner operator run from the surrounding run, matching the negated logical sequence example (`spec:250-256`). List-comprehension syntax is shorthand and scores zero; boolean operators in its predicates still score as logical sequences (`spec:155-168, 207-229`).
- Each callable in a direct or indirect same-module recursion cycle gets one point, independent of the number of recursive calls (`spec:230-237, 491-501`). Haskell equations with the same name are separate callable clauses, and each clause is checked using its own name and arity. A qualified call through the current module name is self-like; a different module qualifier is not assumed to be the same callable. An unresolved peer absent from this file creates no cycle.
- The `catch`/`handle`/`try` exception combinators are the closest Haskell equivalent to catch clauses and add one point per modeled catch boundary (`spec:190-195`). `finally` is cleanup, not a handler decision, so it adds none. Haskell has no loop, goto, labeled jump, ternary operator, early-return statement, or null-coalescing syntax; their matrix rows are `n/a`. `return` is an ordinary monadic function and does not exit the callable.

## CPP

Files with `{-# LANGUAGE CPP #-}` use the shared preprocessor scanner. `#if` contributes one structural point, `#else`/`#elif` are alternatives, and included body decisions nest under the condition (`spec:169-179, 281-291, 491-518`). The scanner ignores a matching `#ifndef X`, `#if !X`, or `#if !defined(X)` followed immediately by `#define X` and closed by the file's final `#endif`. A split `#if` minimal repro parsed without diagnostics in the installed pre-change Varde, but extraction returned only the first branch; the fixture uses an inline conditional so its measured construct is fully represented.
