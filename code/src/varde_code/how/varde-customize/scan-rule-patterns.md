---
topic: varde-customize/scan-rule-patterns
version: 1
summary: Scan rule pattern syntax, part 3 of 4, fields in scan-rule-format, tests in scan-rule-tests
---

## Pattern syntax

Patterns use the same ast-grep-style matcher as `find_pattern`.

- `$VAR` captures one AST node; `$$$VAR` captures a variadic list (arguments,
  statements).
- A leading `$$$MOD` makes a declaration pattern ignore modifiers (`let` matches
  `static let` and `private static let`) and lets field patterns match in class
  or contract bodies. It is valid only at the start of the pattern.
- Everything else matches AST structure, not text. Declaration keywords such
  as `const` and `let` are stripped as trivia, so `const $KEY = $VAL` also
  matches `let` declarators. `$KEY = $VAL` and `const $KEY = $VAL` still
  need separate `[[rule]]` entries (see `hardcoded-credential-*`).
- Constraints use Rust `regex` (no lookahead or lookbehind) via an unanchored
  `is_match`. Anchor with `^...$` unless substring matching is intended.
