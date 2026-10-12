# C cognitive complexity interpretation

The Sonar specification defines `if`, `else if`, `else`, `switch`, loops,
`catch`, `goto`, recursion, and logical-operator sequences
(`spec:190-229`, `230-243`, `491-518`). C maps those constructs onto the
language-neutral roles; this page records the C cases where the syntax tree
needs an explicit mapping or the spec is silent.

## C mappings

- A plain `else` emits `else_branch` (role `Else`): one hybrid increment with
  no nesting cost of its own, and the body one nesting level deeper. An `else`
  whose body is directly an `if` stays the `elseif_statement` event and emits
  no `else_branch` (`spec:176-179`, `491-518`).
- C's `if_statement` syntax span covers its whole `else` tail. The event is
  trimmed to end at the branch's `consequence`, so an earlier branch never
  adds nesting to a later branch (`spec:502-518`). Because the trim removes
  the outer `if` as the max-nesting parent of its else tail, a non-`else if`
  `if` with an alternative also emits a `legacy_nesting` row over that tail;
  the row counts only in `max_nesting` and preserves the pre-change
  `max_nesting` value. `else_branch` supplies the cognitive nesting parent.
- A negated binary logical expression emits `negation_break` on the
  `unary_expression`; it separates like-operator runs as described by the
  accepted plan interpretation (`spec:207-229`, `254-256`; the spec does not
  spell out negation boundaries).
- `goto` keeps the existing `goto_statement` entity name and now maps to the
  shared `Jump` role: one flat increment, no nesting cost, no cyclomatic
  point, and it still counts once in `files.complexity`
  (`spec:238-243`, `491-501`). The label target emits nothing, so unlabeled
  `break`/`continue`/`return` stay zero (`spec:238-243`).
- `switch_statement` is a `DecisionContainer` and each `case_statement` is a
  legacy `DecisionArm`: the switch and all its cases add one cognitive point,
  while the arms supply the cyclomatic branches (`spec:196-205`, `491-500`).
- A direct or indirect same-file self-call emits one `recursive_call` row at
  the function's name token (`spec:230-237`, `491-501`). C functions are
  module-level, so an unqualified call binds to a same-file function with a
  matching arity; a call through a struct function-pointer member is a
  different receiver and binds nothing. A peer defined in another file is
  absent from the file and scores 0.

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
  `function_declarator`; the name is the unwrapped identifier.
- Arity comes from the `function_declarator`'s `parameter_list`: a
  defaulted `optional_parameter_declaration` is optional, a variadic tail
  makes the total unbounded, and a declarator-less `(void)` parameter list
  declares zero parameters.
- `match_callees` reports syntactic references only; the shared
  `extract/recursion.rs` resolver owns arity, owner, cycle, and cross-file
  binding, and emits the `recursive_call` markers.
