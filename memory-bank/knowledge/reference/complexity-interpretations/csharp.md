# C# cognitive complexity interpretation

The Sonar specification defines `if`, `else if`, `else`, `switch`, loops,
`catch`, `goto`, recursion, and logical-operator sequences
(`spec:190-229`, `230-243`, `491-518`). C# maps those constructs to the same
increments as their language-neutral forms. This page records the C# cases
where the syntax tree needs an explicit mapping or the spec is silent.

## C# mappings

- `switch_statement` and `switch_expression` are `DecisionContainer` events:
  each adds one cognitive point and nesting, while their `case_statement`
  events supply cyclomatic branches. This follows the spec's single cognitive
  switch increment and per-case cyclomatic branches (`spec:196-205`,
  `491-501`).
- `and_pattern` and `or_pattern` each emit one event at the outermost node of
  a same-operator run. They use the cognitive-only `Else` role so they add no
  point to legacy cyclomatic metrics. `not` adds no event. This is the plan's
  adopted analogy to binary logical sequences (`spec:207-229`).
- A C# `when` filter is a legacy `guard_clause`: its Boolean operators still
  count, while the guard itself adds no cognitive point. Each `catch` still
  counts once (`spec:190-203`, `207-229`).
- A plain `else` emits `else_branch`; `else if` emits `elseif_statement` and
  does not also emit an `else_branch`. C# `if_statement` syntax spans include
  the full alternative chain, so the event span ends at that branch's
  consequence. This prevents earlier branches from adding nesting to later
  branches. `else if` and `else` are hybrid increments with no nesting cost
  of their own (`spec:176-179`, `491-518`).
- A negated binary logical expression emits `negation_break` on C#'s
  `prefix_unary_expression`; it separates like-operator runs as described by
  the accepted plan interpretation (`spec:207-229`; plan decision, since the
  spec does not spell out negation boundaries).
- `goto`, `goto case`, and `goto default` emit `goto_jump`. A label target is
  not an event (`spec:230-243`, `491-501`). Query clauses are shorthand and
  score zero by plan decision.

## Preprocessor guards

The spec's `#if` example adds a structural increment (`spec:175-179`), and its
callable-boundary example discusses nesting (`spec:286-291`); neither passage
defines include guards. The nearest analogy is the plan's C/C++ header-guard
rule: a file wrapper is a guard, not a conditional, when its opening
`#if !X` in C# is immediately followed by `#define X` and closed by the
file's final `#endif`. It contributes zero. The shared scanner also recognizes
`#ifndef X`, `#if !X`, and `#if !defined(X)` with the same matching define and
final-endif conditions. A missing or mismatched immediate define leaves an
ordinary conditional. C/C++ `#ifdef __cplusplus` linkage regions remain
conditionals; they are not include guards.

## Extractor idioms for other languages

- Register callable AST node kinds in `FUNCTION_SCOPES`; use a stable
  `function_scope_name` for operator, conversion, destructor, and accessor
  declarations. Keep callable spans body-covering for nesting and recursion.
- Emit language-specific control flow as `EntityKind::ControlFlow` with the
  shared role name where available. Add per-language `FLOW_NAME_ROLES` only
  when a construct's cognitive and cyclomatic behavior differs; the registry
  is collected centrally in `extract/langs/mod.rs`.
- Implement `match_callees(source)` in the language extractor and rely on the
  existing `SupportLang::CSharp => cs::match_callees(source)` dispatcher in
  `extract/langs/mod.rs`. Return shared `Callable` and `CalleeReference`
  records with declaration spans, name spans, owner type, and arities.
  Class-scoped self calls use `Qualifier::SelfLike` for `this`,
  `Qualifier::NamedType` for the containing type, and `Qualifier::Other` for
  other receivers. The recursion resolver then handles overload selection,
  cycles, and the final `recursive_call` markers.

For C# the callable node names are `method_declaration`,
`constructor_declaration`, `local_function_statement`, `accessor_declaration`,
`operator_declaration`, `conversion_operator_declaration`, and
`destructor_declaration`. The shared dispatcher is already registered, so a
language task implements its extractor hook without editing the dispatcher.
