# Swift cognitive complexity interpretation

The Sonar specification's structural, nesting, logical-sequence, jump, and
recursion rules apply to Swift (`spec:207-243`, `491-518`). This page records
Swift syntax mappings and decisions where the spec is silent.

## Swift mappings

- `if_statement`, `for_statement`, `while_statement`,
  `repeat_while_statement`, `ternary_expression`, and `guard_statement` are
  structural decisions. A `guard ... else` adds one point for the guard; its
  required `else` is not a second branch increment (`spec:491-518`; nearest
  analogy: `if`/`else`, `spec:176-179`). An `if let ... else` uses ordinary
  `if` and `else` scoring.
- Plain `else` emits `else_branch`; `else if` emits `elseif_statement` only.
  Swift's `if_statement` span includes its alternative, so the `if` event ends
  at its consequence. An else event spans from the `else` keyword through its
  branch body, allowing nested decisions there to receive the branch nesting
  level (`spec:502-518`; plan's accepted branch interpretation).
- `switch_statement` adds one cognitive point; `switch_entry` maps to
  `case_statement` for the existing cyclomatic case count (`spec:196-205`,
  `491-501`). Each `catch_block` adds one point; `do` and `try` add none
  (`spec:190-203`). Swift `defer` is cleanup syntax analogous to `finally` and
  adds no point. The Swift grammar has no named defer node; the fixture pins
  zero contribution.
- Swift's `? :` conditional expression scores as a ternary. `??` is
  null-coalescing and scores zero (`spec:160-168`, `491-518`). Conditions are
  inside their structure: an `if` containing a ternary in its condition scores
  3 (the `if` +1, ternary +1, and nesting +1; plan's condition interpretation).
- `conjunction_expression` and `disjunction_expression` mark logical runs. In
  this grammar, `!(b && c)` parses through a `bang` call expression; that
  expression emits `negation_break` so the inner run starts a new sequence
  (`spec:207-229`, `254-256`; plan's negation interpretation).
- Labeled `break` and `continue` emit `labeled_jump`; plain transfers and
  returns remain zero (`spec:238-243`, `491-501`). Swift has no `goto`.
- Closures, nested named functions, and local-type methods raise nesting but
  add no structural point themselves (`spec:267-291`). A closure's events also
  score in the closure's own row. `recursive_call` markers are resolved by
  method owner and argument count: unqualified calls, `self.f`, and same-type
  `Type.f` calls can bind; a different receiver cannot. Calls in closures belong
  to their enclosing named method (`spec:230-237`). Same-file cycles score once
  per method; an unresolved peer in another file scores zero.

## Conditional compilation

Swift `#if`, `#elseif`, `#else`, and `#endif` are scanned as structural
conditional regions. The fixture covers `#if` around a closure with a nested
`if` (score 4, `spec:175`, `281-291`) and verifies the `#elseif`/`#else` forms.
Swift supports `#if !FEATURE`, but has no `#define` directive; therefore the
shared C-style include-guard pattern cannot be formed, and a negated `#if`
remains an ordinary conditional. Swift has no `extern "C"` block; C ABI
attributes such as `@_cdecl` do not form preprocessor linkage regions.

## Not applicable

- `compensating-usage` and `compensating-usage-callback`: the plan's marker
  semantics are defined for JavaScript/TypeScript declarative functions and
  Python decorators/callback shape; Swift has no corresponding exception.
- `preproc-extern-c`: Swift has no C linkage block syntax.
- `comprehension-or-query`: Swift has no comprehension or query-clause syntax;
  `map` and `filter` are ordinary calls with closures.
- `spec-example-large`: the plan's large worked example is provided for Java,
  JavaScript, and C# only.
