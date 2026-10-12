# Cognitive complexity metric

This page defines the cognitive-complexity metric used by varde-code. A
**certified function-complexity language** is one whose conformance suite passes
in CI. Existing uses of “certified” elsewhere keep their own meaning.

## Scope

The gate measures cognitive complexity per callable. Cyclomatic complexity,
`max_nesting`, thresholds, and rule severities keep their existing semantics.
The conformance suite is the source of truth for expected values; each value is
hand-derived from the Sonar specification and cites its rule lines.

## Spec basis

The source of record is the Sonar Cognitive Complexity white paper (G. Ann Campbell, SonarSource, version 1.7, 29 August 2023).

| Rule | Specification lines |
|---|---|
| `if`, `else if`, `else`, ternary, switch, loops, catch, labeled or numbered jumps, logical-operator sequences, and recursion each add one | `spec:491-501` |
| `if`, `else if`, `else`, ternary, switch, loops, catch, and nested methods or method-like structures raise nesting | `spec:502-509` |
| Only `if`, ternary, switch, loops, and catch receive a nesting increment | `spec:510-518` |
| `else if`, `elif`, and `else` add one without a nesting increment and raise nesting for their bodies | `spec:176-179`, `spec:747-754` |
| Preprocessor `#if` and `#ifdef` are structural conditionals | `spec:175`, `spec:281-291` |
| A switch counts once; catch counts once; try and finally add zero | `spec:190-203` |
| Method declarations and null-coalescing operators add zero | `spec:155-168` |
| Each sequence of like binary logical operators adds one | `spec:207-229`, `spec:254-256` |
| Each method in a direct or indirect recursion cycle adds one | `spec:230-237`, `spec:501` |
| Labeled and numbered multi-level jumps add one; other jumps and early exits add zero | `spec:238-243`, `spec:498-499` |
| Nested methods and lambdas raise nesting; top-level methods are ignored | `spec:267-291` |

## Decisions

- The conformance gate covers the 21 languages that were certified when the
  plan began. No language or construct is excluded from the gate.
- Interpret ambiguous constructs by the spec text first, then by analogy to
  the nearest specified construct. Record the chosen interpretation beside
  the language suite.
- Cognitive scores roll up events from nested callables into containing
  callables, adding one nesting level per nested callable. Nested callables
  retain their own metric rows.
- Conditions are inside their containing structure. For example,
  `if (condition ? left : right)` scores 3.
- Plain parentheses do not break a same-operator logical run. Unary `!` or
  `not` between nested runs starts a new sequence.
- Extractors represent that unary boundary with a `control_flow` entity named
  `negation_break`, spanning the negation expression. The scorer starts a new
  same-operator sequence when this marker encloses the nested run.
- A JavaScript/TypeScript/TSX declarative wrapper or a Python decorator-shaped
  function that meets the accepted compensating-usage criteria emits a
  `control_flow` entity named `compensating_usage`, spanning the callable.
  Nested callables below that marker add no callable nesting level.
- `else_branch`, `goto_jump`, `labeled_jump`, `recursive_call`, `preproc_if`,
  `preproc_branch`, `cognitive_decision`, `legacy_nesting`,
  `pattern_logical_and`, and `pattern_logical_or` do not affect legacy
  `files.complexity` or cyclomatic values. `legacy_nesting` still contributes
  to `max_nesting`; `cognitive_decision` and the pattern-logical events score
  only in cognitive complexity. `negation_break` and `compensating_usage` are
  scorer metadata markers, not flow decisions, and are also excluded from
  legacy counts. `guard_clause` remains in the legacy values (cyclomatic,
  `files.complexity`, `max_nesting`) but is excluded from cognitive complexity;
  other legacy-only decisions (comprehension shorthand) behave the same way.
- `cognitive_decision` is a cognitive-only decision for a construct that emitted
  no `control_flow` entity before this plan (Bash arithmetic ternary): it scores
  +1 plus nesting and raises cognitive nesting, and it counts in no cyclomatic,
  `max_nesting` or `files.complexity` value.
- Cross-file recursion is not counted. Same-file direct and indirect cycles
  add one point per method in the cycle.
- C, C++, C#, Swift, and Haskell files enabling CPP count preprocessor
  conditional regions. Include guards are excluded.

## Interpretations

Language-specific decisions are recorded in these pages:

- [Shared](complexity-interpretations/shared.md)
- [Bash](complexity-interpretations/bash.md), [C](complexity-interpretations/c.md),
  [C++](complexity-interpretations/cpp.md), [C#](complexity-interpretations/csharp.md),
  [Dart](complexity-interpretations/dart.md), [Elixir](complexity-interpretations/elixir.md),
  [Go](complexity-interpretations/go.md), [Haskell](complexity-interpretations/haskell.md)
- [Java](complexity-interpretations/java.md), [JavaScript](complexity-interpretations/javascript.md),
  [Kotlin](complexity-interpretations/kotlin.md), [Lua](complexity-interpretations/lua.md),
  [PHP](complexity-interpretations/php.md), [Python](complexity-interpretations/python.md),
  [Ruby](complexity-interpretations/ruby.md), [Rust](complexity-interpretations/rust.md)
- [Scala](complexity-interpretations/scala.md), [Solidity](complexity-interpretations/solidity.md),
  [Swift](complexity-interpretations/swift.md), [TSX](complexity-interpretations/tsx.md),
  [TypeScript](complexity-interpretations/typescript.md)
