# C++ cognitive complexity interpretation

The Sonar specification defines `if`, `else if`, `else`, `switch`, loops,
`catch`, `goto`, recursion, and logical-operator sequences
(`spec:190-229`, `230-243`, `491-518`). C++ maps those constructs onto the
language-neutral roles; this page records the C++ cases where the syntax tree
needs an explicit mapping or the spec is silent.

## C++ mappings

- A plain `else` emits `else_branch` (role `Else`): one hybrid increment with
  no nesting cost of its own, and the body one nesting level deeper. An `else`
  whose body is directly an `if` stays the `elseif_statement` event and emits
  no `else_branch` (`spec:176-179`, `491-518`).
- C++'s `if_statement` syntax span covers its whole `else` tail. The event is
  trimmed to end at the branch's `consequence`, so an earlier branch never
  adds nesting to a later branch (`spec:502-518`). The non-`else if` `if` with
  an alternative also emits a `legacy_nesting` row over that tail; the row
  counts only in `max_nesting` and preserves the pre-change value.
  `else_branch` supplies the cognitive nesting parent.
- A negated binary logical expression (`!` or the alternative token `not`)
  emits `negation_break` on the `unary_expression`; it separates like-operator
  runs (`spec:207-229`, `254-256`; the spec does not spell out negation
  boundaries).
- `goto` keeps the existing `goto_statement` entity name and maps to the
  shared `Jump` role: one flat increment, no nesting cost, no cyclomatic
  point, and it still counts once in `files.complexity`
  (`spec:238-243`, `491-501`). The label target emits nothing.
- `switch_statement` is a `DecisionContainer` and each `case_statement` a
  legacy `DecisionArm`; a `try_statement` is ignored, and each
  `catch_clause` is one `Catch` point regardless of the caught types
  (`spec:190-205`, `491-500`).
- Lambdas are callable boundaries: they score no structural increment of
  their own, but their decisions raise the containing callable's score by one
  nesting level (`spec:267-291`). A local class's methods are nested callables
  in the same way, and each nested callable keeps its own metric row.
  A constructor, destructor, overloaded operator, or function template is a
  callable; the method structure itself adds no point (`spec:155-168`).
  Operators are named after their `operator_name` token (`operator+`), while
  destructors keep the class name from the pre-change declarator unwrap
  (conversion operators such as `operator bool` also keep their declarator
  name and are not renamed).
- Recursion is class-scoped (`spec:230-237`, `491-501`): `this->f` is a
  self-like call, `Type::f` for the enclosing type is a named-type call, and
  any other receiver binds nothing. An out-of-line definition
  (`Type::f` outside the class) resolves its owner from the qualified
  declarator, so its unqualified self-call still binds. Calls inside a lambda
  belong to the enclosing named function. Arity is checked against the
  callee's declared parameter range, so a delegating overload is not
  recursion. A peer defined in another file is absent from the file and
  scores 0.

## Preprocessor guards

`#if`, `#ifdef`, and `#ifndef` are structural conditionals: one flat point and
one nesting level for their contents (`spec:175`, `281-291`). The shared text
scanner emits `preproc_if`/`preproc_branch`; a region that contains a top-level
function also gets a copy clipped to that function's span.

- A conventional include guard (`#ifndef X` immediately followed by
  `#define X`, closed by the file's final `#endif`) contributes nothing; it is
  a file wrapper, not a conditional (`spec:175`, `281-291`; plan decision).
- The split linkage form `#ifdef __cplusplus` / `extern "C" {` / `#endif` and
  its closing twin are ordinary conditionals that contain no callable, so
  functions between them gain nothing (`spec:281-291`; plan decision).
- A source with this split form fails the first parse and is re-parsed with
  directive lines blanked; byte offsets and line numbers are preserved, and
  the directive regions are restored from the original text, exactly as
  production `scan` does.

## Extractor idioms

- `function_definition` declarators are peeled through
  `pointer_declarator`/`parenthesized_declarator` to the
  `function_declarator`. The callable name is the operator token text for
  `operator_name` declarators, otherwise the unwrapped identifier; a
  `qualified_identifier` name resolves the out-of-line owner from its scope.
- Arity comes from the `function_declarator`'s `parameter_list`: a defaulted
  `optional_parameter_declaration` is optional, a variadic tail makes the
  total unbounded, and a declarator-less `(void)` parameter list declares zero
  parameters.
- `match_callees` reports syntactic references and owner-qualified
  references; the shared `extract/recursion.rs` resolver owns arity, cycle,
  and cross-file binding, and emits the `recursive_call` markers.
