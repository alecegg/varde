# Bash cognitive complexity interpretations

This page records Bash mappings where the Sonar Cognitive Complexity spec is language-neutral or silent. Spec references point to the Sonar Cognitive Complexity white paper (G. Ann Campbell, SonarSource, version 1.7, 29 August 2023).

## Decisions and jumps

- `if`, `elif`, and `else` each add one point. Bash's `elif_clause` and `else_clause` grammar nodes include their bodies, so their emitted spans stop at the condition or keyword; a nested decision in either branch receives only the root `if` nesting increment (`spec:176-179, 491-518`).
- `case` adds one structural point; its pattern arms remain cyclomatic branches and add no cognitive points (`spec:196-205, 491-501`). This preserves the installed pre-change cyclomatic and file-complexity counts.
- `for`, C-style `for`, `select`, `while`, and `until` are loop decisions. Bash `select` shares the grammar's `for_statement` node; `until` shares `while_statement` (`spec:491-518`).
- Arithmetic `?:` emits `cognitive_decision`: it adds one point plus current cognitive nesting, including when nested inside an `if` condition. This name is excluded from cyclomatic, `max_nesting`, and legacy file-complexity values (`spec:491-518`).
- Plain `return`, `break`, and `continue` add zero. Numeric `break N` and `continue N` emit `labeled_jump` and add one point each (`spec:238-243, 498-499`). Bash has no `goto` statement or label target.

## Logical sequences and callables

- Each same-operator `&&` or `||` run adds one point, whether it appears in `[[ ]]` or a command list. `!` adds no point and separates nested logical runs (`spec:207-229, 254-256`).
- Named nested functions raise nesting for decisions in their bodies; their bodies also receive separate function metrics (`spec:267-291`). Bash has no anonymous callable or lambda syntax.
- A function that calls itself by command name adds one recursion point. Multiple calls still add one point, and every function in a same-file recursion cycle receives its own point. Calls to a peer absent from the one-file fixture do not form a recursion cycle (`spec:230-237, 491-501`).
- `trap` installs a signal or error handler but does not delimit a protected region, so it is not a `catch` or `finally` construct (`spec:190-203`).

## Grammar-based n/a cases

Bash has no syntax for lambdas, closures, class or receiver methods, method overloads, `try`/`catch`/`finally`, JavaScript declarative wrapper functions, Python decorators, source preprocessor directives, extern-C linkage, or comprehensions/queries. Parameter-expansion defaults such as `${value:-fallback}` are not null-coalescing operators (`spec:160-168, 415-480`). Its numeric jumps are covered by `labeled_jump`, so the `goto-or-labeled-jump` matrix row is applicable.
