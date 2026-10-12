# Java cognitive complexity interpretation

The specification explicitly scores `if`/`else if`/`else`, one `switch`, each
`catch`, logical-operator runs, recursion and jumps (`spec:176-179`, `190-229`,
`230-243`, `491-518`). It also shows nesting across callable boundaries
(`spec:267-291`) and provides Java examples (`spec:328-339`, `525-685`). Java
uses those scores; this page records the syntax-tree mappings and silent cases.

## Java mappings

- Java's parser represents colon-form switch statements and arrow-form switch
  expressions as `switch_expression` nodes. Each emits one
  `DecisionContainer`; `case_statement` emits the legacy cyclomatic arms. This
  preserves one cognitive increment for either syntax (`spec:196-205`,
  `491-501`).
- A plain `else` emits `else_branch`; an `else if` emits `elseif_statement`.
  The `if` event span ends at its consequence so later branches do not inherit
  nesting from earlier alternatives. This applies the hybrid increments and
  the plan's rule that an `else if`/`else` body sits one level below its root
  `if` (`spec:176-179`, `491-518`).
- Each Java `catch_clause` emits one catch event, including a multi-catch
  parameter. `try`, `finally`, and try-with-resources emit no cognitive event;
  nested decisions in their bodies keep their ordinary nesting
  (`spec:190-203`).
- Java binary `&&` and `||` sequences emit the shared logical-run events. A
  unary `!` emits `negation_break` to separate same-operator runs; the spec
  defines logical sequences but does not state whether negation splits them,
  so this follows the plan's adopted rule (`spec:207-229`; plan decision).
- Labeled `break` and `continue` emit `labeled_jump`; unlabeled forms remain
  ignored. The spec names `goto` as a jump and gives it one point; Java has no
  `goto`, so labeled jumps use that nearest analogue (`spec:230-243`,
  `491-501`).
- Lambdas, local-class methods, anonymous-class methods, and record constructors
  and methods are separate callable scopes. Nested callable events roll up
  with one additional nesting level, following the lambda example; the spec
  does not enumerate Java callable forms (`spec:267-291`).
- Java class and record methods use owner-scoped recursion. Bare self-calls,
  `this.method()`, and same-type calls can bind by method name and arity;
  another receiver cannot. Calls in lambdas belong to the enclosing named
  method. Overload delegation and same-file cycles use the shared resolver
  (`spec:230-237`).
- Ternary expressions add a structural point according to the nested ternary
  table. Enhanced `for` has the same increment as the specification's `for`;
  `instanceof` patterns add no point on their own and rely on the enclosing
  decision (`spec:491-518`).

Java has no preprocessor conditionals, C/C++ `extern "C"` regions,
null-coalescing operator, named nested function declarations, or comprehension
syntax. These are recorded as `n/a` in the conformance suite. Java streams use
ordinary calls and lambdas, not comprehension clauses.
