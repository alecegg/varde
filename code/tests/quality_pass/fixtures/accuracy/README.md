# Accuracy audit fixtures (A17-A19)

Hand-labelled inputs for the P0 accuracy audits of `validation-plan.md`:

| Audit | Threshold | Labelled set | Reference derivation |
| --- | --- | --- | --- |
| A17 tokens | within 2% per release language | `tokens/`, 30 files, 5,050 reference tokens | independent lexical scanner (`../accuracy/accuracy_reference_tokens.py`), two fully hand-counted files, and a stdlib-`tokenize` cross-check for all four Python files |
| A18 parameters | exact on at least 99% of labelled functions | `labels/params.json`, 216 functions in 25 files | hand count of the declared parameter list per function |
| A19 generated/vendored | recall at least 95%, precision at least 98% | `repo/`, 135 files (82 positive, 53 negative) | hand label with per-file evidence in `labels/generated.json` |

Every reference is derived independently of the facts engine: no label was
produced by running `varde_code.quality_pass.facts`. The audits themselves are
in `../accuracy/`.

## Token definition (A17)

The published contract (`quality-contract.md` section 1) defines the counting
unit: code tokens with comments excluded, and string literals counted as
`min(32, ceil(len(content) / 8))`. The reference scanner implements that
definition lexically, with no parser:

1. Whitespace and comments are not tokens.
2. An identifier or keyword, a numeric literal, one operator or punctuation
   mark, and one preprocessor directive keyword (`#include`, `#define`, ...)
   are one token each; the scanner uses maximal munch, so `==`, `->`, `:=` and
   `..` are single tokens.
3. A C-family character literal (`'a'`, `'\n'`) is one token.
4. A string literal contributes `min(32, ceil(len(content) / 8))` tokens, where
   `content` is the text between the delimiters with prefix and suffix removed
   (`b`/`r`/`f`, C# `@`, Rust `r#...#`, C++ `R"delim(...)delim"`). An
   interpolated or raw string is one literal; its embedded text is part of the
   content.
5. A JavaScript-family regular expression literal is one token.
6. After a C/C++ `#include`/`#import`, the header name in angle brackets is one
   token, so `#include <vector>` is two tokens.
7. In TSX, `</` is one token (the TypeScript scanner's `LessThanSlashToken`) and
   a JSX text run (the maximal text up to the next `<` or `{` in an element's
   child position) is one token (the scanner's `JsxText`). The scanner tracks a
   small JSX position machine: element nesting, fragments, self-closing tags
   (`/` and `>` stay two tokens) and inline `{...}` expressions. It does not
   implement JSX entity references, which no fixture uses.

`labels/tokens.json` holds the reference count per file, produced by
`reference_token_count`; `test_accuracy_tokens.py` asserts the label file still
matches the scanner so a scanner change cannot silently move a reference.

### Hand checks

Two references were additionally counted token by token from the source text
(per line, using the rule above), which exercises the two rules most likely to
be wrong: preprocessing and string weight.

| Fixture | Hand count | Scanner | Break-down |
| --- | --- | --- | --- |
| `tokens/cpp/basics.cpp` | 88 | 88 | 87 lexical tokens; `"anonymous"` has 9 content bytes, so weight 2 instead of 1 |
| `tokens/python/numeric.py` | 183 | 183 | 176 lexical tokens; the 64-byte module docstring has weight 8 instead of 1 |

For Python, all four fixtures are cross-checked against the standard library
`tokenize` (a second, unrelated tokenizer): the lexical token counts agree
exactly (148, 152, 176, 221) once the PEP 701 f-string parts
(`FSTRING_START`/`FSTRING_MIDDLE`/`FSTRING_END`) are collapsed into the one
literal the reference rule counts.

### A17 sizes and results

Reference totals (engine totals in parentheses) per release language:

| Release language | Files | Reference | Engine | Delta |
| --- | --- | --- | --- | --- |
| python | 4 | 736 | 736 | +0.00% |
| typescript/javascript/tsx | 6 (2 ts, 1 tsx, 3 js) | 1144 | 1139 | -0.44% |
| java | 4 | 691 | 693 | +0.29% |
| go | 4 | 534 | 534 | +0.00% |
| rust | 4 | 682 | 680 | -0.29% |
| csharp | 4 | 621 | 622 | +0.16% |
| cpp | 4 | 642 | 643 | +0.16% |

All 30 token fixtures are now within 2%. C# strings, C++ character literals,
and JavaScript regular expressions follow the token definition above.

## Parameter definition (A18)

One reference value per labelled function, counted by hand from the source:

- one entry in the declared parameter list is one parameter;
- Go receivers and Rust `self` / `&self` / `&mut self` / `self: T` receivers are
  not parameters (the grammar separates them); Python `self`/`cls` and Java,
  C#, C++ `this`-like forms are ordinary parameters where the grammar puts them
  in the parameter list;
- a C++ `(void)` parameter list has zero parameters; a variadic `...` counts
  one; a C++ parameter pack `Args... args` counts one;
- a C# `params int[] rest` counts one;
- a Java compact record constructor takes the record components as its
  parameters.

Labels are keyed by `owner.name` (or `name`), so fixtures keep at most one
function per owner and name. Set sizes: python 38, typescript 29, tsx 3,
javascript 13, java 27, go 27, rust 24, csharp 25, cpp 30 - 216 functions in 25
files. Engine-exact: 216 of 216 (100.00%).

## Generated/vendored definition (A19)

`repo/` is a simulated repository; each label key is the path the engine sees
and each file sits at `repo/<key>`. A fixture is labelled `generated` or
`vendored` when that is its true origin (with the evidence recorded per file in
`labels/generated.json`), and `clean` when it is hand-written project source
even if it mentions generation in prose.

The A19 threshold applies to the **raw detection signal** the pass produces:

- the facts engine's file markers (content markers such as
  `Code generated ... DO NOT EDIT`, the `@generated`/`<auto-generated>`
  variants, and the Java and C# path and annotation conventions), or
- the path classification by directory convention (`vendor/`, `third_party/`,
  `node_modules/`, `generated/`, `autogenerated/`, `auto-generated/`), or
- the minified exclusion.

A second, stricter measurement applies the gate-mode exclusion decision
(`classify_path(gate_mode=True)` with the markers as the marker predicate and no
base-ref allowlist or extra generator signature), where a marker alone does not
exclude a file. It is reported by the audit but is not the A19 threshold.

Set composition: 82 positives and 53 negatives. Positive evidence kinds:
`marker` 34, `path` 40, `extension` 5 (`.generated.java`, `.g.cs`, `.g.i.cs`,
`.generated.cs`, `.designer.cs`), `attribute` 2 (`@Generated`,
`[GeneratedCode]`), `minified` 1 (a one-line bundle). The 13 added, independently
labelled marker positives cover Kubernetes license blocks (with and without `*`
prefixes), Go build tags, C# `using`, JavaScript `use strict`, Python module
docstrings, ANTLR, automatically generated files, Thrift, `GENERATED FILE`,
“This file is generated,” flex, and bindgen. Thirteen added clean fixtures cover
prose and late-marker cases, including `generated by hand`, `do not edit ... by
hand`, `generated by-product`, `regenerated`, `degenerated`, and `generated id`. Hard positives include
protobuf `*.pb.cc`/`*.pb.h` output in normal directories, a Javadoc `@generated`
tag, a shebang-prefixed generation notice, a 120-line generated table, a
vendored copy in an unconventional `deps/` path, and a minified bundle outside
any generated directory. Hard negatives include prose that uses the marker
vocabulary, name and annotation traps, and ordinary library sources.

Current engine results:

| Measurement | Recall | Precision |
| --- | --- | --- |
| raw detection (A19 threshold) | 82/82 = 100.00% | 82/82 = 100.00% |
| gate mode, no allowlist | 41/82 = 50.00% | 41/41 = 100.00% |

The 50.00% gate-mode recall is expected here: without an allowlist or base
signature, gate mode excludes marker-only positives only when another convention
also supports exclusion. A19's recall threshold applies to the raw signal above.

Marker detection scans comments once in source order. It accepts recognized
generation or vendoring notices in the first 100 header comment lines, or a
standalone marker comment anywhere in the file. It retains the old phrase
coverage (including `generated`, `do not edit`, `auto-generated`, and
`automatically generated`) with word boundaries and notice-context checks.
Ordinary prose such as `generated id`, `regenerated`, `degenerated`, or
`generated by hand` does not qualify. The expanded A19 set now includes these
real header forms and prose negatives; its 100% marker recall (34/34) is a
measurement on these labelled examples, not a claim about every generator.

### Limitations of the A19 set

- The negative set is deliberately hard-negative weighted (19 of 53 negatives use
  the marker vocabulary in prose), so the raw precision is a lower bound for a
  random file sample.
- One large generated file stands in for a large generated tree (the plan names
  Roslyn-scale syntax trees); there is no multi-thousand-file generated corpus.
- There is one minified positive; minified detection is the engine's own
  `excluded` flag, a separate rule from markers and paths.
- Marker positives include header preambles and block comments. Clean late-marker
  fixtures ensure notices after code do not qualify unless they are standalone.
- The A18 fixtures contain no C++ overloads or Rust trait-default bodies, which
  would collide with the `owner.name` label key.
