# Built-in scan rules

The built-in pack contains 139 rules: 102 `error` rules, 31 `warning` rules, and six `info` rules.
`dependency-boundary` is inactive until configured
with both prefixes; a certified violation then fails the default gate.
Rules combine syntax patterns with indexed structural measurements.

```sh
varde scan rules list --json '{"repoRoot":"."}'
varde scan --json '{"repoRoot":".","severityThreshold":"error"}'
```

Scan refreshes its index before evaluating rules. The default threshold is
`error`. `warning` includes warnings. `info` includes every severity.

`gateRules` selects active rule IDs directly. It cannot be combined with
`severityThreshold`. Selected IDs must be unique. An unconfigured boundary is
inactive in ordinary scans when both prefixes are blank. Exactly one blank
prefix or malformed configuration makes the scan incomplete; explicit
selection is rejected before index writes.

## Gate result

Successful execution returns `ok: true`, a top-level `outcome`, and
`data.analysis` plus `data.gate`:

```json
{
  "schema_version": 1,
  "ok": true,
  "outcome": "passed",
  "data": {
    "analysis": { "status": "complete" },
    "gate": {
      "status": "pass",
      "severity_threshold": "error",
      "blocking_findings": 0,
      "diagnostic_count": 0,
      "blocking_diagnostic_count": 0
    }
  }
}
```

`ok` reports execution only. `passed` means no unresolved findings meet the
selected gate. `code-quality-error` means at least one gated finding exists.
`analysis-incomplete` means blocking diagnostics prevent certification.
`data.analysis.status` is `complete` or `incomplete`.
`data.gate.status` is `pass`, `fail`, or `unknown`. Only `pass` exits zero.
An incomplete scan with a blocking finding keeps `gate.status: "fail"` and
lists both reasons in `data.outcome_reasons`. `data.outcome` mirrors the
top-level outcome.

`diagnostic_count` counts every normalized diagnostic.
`blocking_diagnostic_count` counts diagnostics that block certification.
Each diagnostic adds stable `kind`, `source`, `message`, `location`,
`severity`, and `blocking` fields. Legacy producer fields remain available.

`policy` records the mode, active rule count, gating rule count, source counts,
and a stable `fnv1a64` fingerprint. The fingerprint covers active definitions,
overrides, and gate selection.

Findings are bounded by default. The default limit is 100. The
`findings_summary` object reports total, shown, truncation, rule, and severity
counts. Set `fullFindings: true` to return every finding. Use
`findingsLimit` and `findingsOffset` for bounded pages. Truncated results set
`meta.truncated` and provide `data.guide.truncated.findings` recovery fields.

Expected unsupported, generated, and minified skips are omitted from scan
diagnostics. Other loading, parsing, extraction, traversal, and rule errors
make the gate incomplete. Suppressions remove findings before counting, but do
not dismiss diagnostics.

## Structural and dependency rules

Structural budgets below are thresholds. Warning-level findings do not block
the default `error` threshold. Dependency counts and clone eligibility follow
their own evidence rules.

| Rule | Severity | Certified condition |
|---|---|---|
| `function-complexity-gate` | `warning` | High-confidence cognitive > 15 or cyclomatic > 20 |
| `function-length-warning` | `warning` | High-confidence span > 60 lines when both complexity metrics are within bounds |
| `file-complexity-hotspot` | `warning` | Certified production file complexity > 50 and average per function > 7 |
| `fat-interface` | `warning` | One uniquely identified type has more than 15 direct indexed methods; structural fixtures cover 13 languages |
| `too-many-interfaces` | `warning` | One class resolves more than 3 same-file interfaces with methods |
| `deep-inheritance` | `warning` | Resolved same-file inheritance depth exceeds 3; depth is a lower bound |
| `duplicate-code-clone` | `warning` | At least 3 exact-clone members, each over 8 lines and at least 20 syntax tokens |
| `low-fan-in-high-fan-out-file` | `warning` | Certified fan-out is at least 15 and fan-in is at most 2 |
| `circular-import` | `error` | Two certified dependency units import each other directly |
| `unresolved-local-import` | `error` | A certified relative source import has no supported target |
| `dependency-boundary` | `error` | A certified import crosses configured literal directory prefixes |

The tested `fat-interface` structural cases cover TypeScript, Java, C#, C++,
Python, Ruby, Kotlin, Swift, Dart, Scala, PHP, Rust, and Go.

Certified dependency facts cover all 21 extraction languages. JavaScript,
TypeScript, TSX, Dart, Solidity, Rust, Python, C, C++, Ruby, PHP, Lua, Bash,
Elixir and Haskell use file units; Go and Java/Kotlin/Scala use directory
units; C# uses the nearest `.csproj`; Swift a `Sources/<Target>` directory or
an Xcode `PBXNativeTarget` read from `project.pbxproj`.

Per-language limits:

- JavaScript, TypeScript, TSX, Dart, Solidity: relative source paths only.
- Go, Java, Kotlin, Scala: directory units, and a fact needs exactly one
  repository file declaring the imported type or package in a different unit.
- Rust: only cross-Cargo-package imports with file units; a `use` inside one
  crate yields no fact. `mod name;` declarations are not dependencies; they
  drive `missing` facts only.
- Python: relative imports resolving to exactly one indexed
  `a.py`/`a/__init__.py`, and absolute imports whose top-level package is a
  repository source root with `__init__.py`. `TYPE_CHECKING` blocks and
  `try`/`except ImportError` guards yield no fact.
- C, C++: quoted includes outside conditional regions. `missing` is certified
  only for `./` and `../` specifiers.
- Ruby, PHP: plain `require_relative` (Ruby) and literal
  `require`/`require_once`/`include`/`include_once` (PHP) strings. Guarded,
  interpolated and variable includes yield no fact.
- Lua: a dotted `require` resolving to exactly one `a/b.lua` or
  `a/b/init.lua` under the repository root or its `lua/` directory. Bash:
  explicitly relative literal `source`/`.` paths only.
- C# and Swift: facts are certified only, because a namespace or module cannot
  be certified absent from source; neither emits `missing` facts.
- Elixir, Haskell: module names from `defmodule`/`defprotocol` and
  `module M where` headers, with file units. A missing fact needs repository
  ownership from a local manifest or a declared parent module.

Missing-import findings require an explicit, recognized source filename that is
absent across supported extension aliases. Extensionless missing imports are
not certified. Package aliases, ambiguous targets, and ignored or unindexed
targets are excluded. Tests,
tooling, type-only imports, and assets are excluded. Cycle detection reports
direct reciprocal pairs only. It does not search transitive cycles.

Exact-clone verification compares AST leaves, kinds, and structure. Comments
and layout are ignored. Literals, operators, and case remain significant.
Bodies are compared when available; otherwise the whole function is used.
Actual-source clone fixtures cover all 21 extraction languages.

Boundary prefixes match complete directory segments. Prefix text is literal,
not a regular expression. Both prefixes must be nonempty for an active policy.
Because the rule enforces an explicitly configured architecture boundary, its
violations block the default gate.

```sh
varde scan rules seed --json '{"repoRoot":"."}'
# Edit .varde-code/rules/dependency_boundary.toml:
# Replace its strings table with:
# strings = { source_prefix = "src/core", target_prefix = "src/data" }
varde scan --json '{"repoRoot":".","gateRules":["dependency-boundary"]}'
```

Seeded copies are whole-rule overrides. They stay active until removed, so
future built-in updates do not replace local edits.

Partial function metrics are reported by `function-complexity-advisory` at
`info`. `churn-complexity-hotspot` is also `info`; churn is review context, not
proof of a defect. `vertical-slice-sprawl`, `solid-lsp`, and `solid-isp` are
`info` advisories. Their evidence cannot establish compiler-level contracts.

All 21 extraction languages have tested function-complexity profiles:
JavaScript, TypeScript, TSX, Rust, Go, Python, Java, C, C++, C#, Swift,
Kotlin, Ruby, PHP, Scala, Dart, Lua, Elixir, Solidity, Haskell, and Bash.

## Syntax rules

The syntax pack has 139 declared rule-language pairs. Each pair has positive
and negative coverage in the regression fixtures. Rule severity follows the
measured false-positive rate: an `error` rule showed zero false positives
across at least three reference repositories per language plus this repository
where the language occurs; a rule whose measured hits are intentional discards
ships at `warning`. Every rule has positive and negative fixtures per declared
language.

### Dynamic evaluation, debug, and console

| Language | Debug rule or N/A | Eval rule or N/A |
|---|---|---|
| JavaScript | `debugger;`, `console.log(...)` | `eval(...)` (`eval-usage`) |
| TypeScript | `debugger;`, `console.log(...)` | `eval(...)` (`eval-usage`) |
| TSX | `debugger;`, `console.log(...)` | `eval(...)` (`eval-usage`) |
| Python | `breakpoint()`, `pdb.set_trace()` | `eval(...)` (`eval-usage`) |
| Ruby | N/A: bare `byebug` also matches receiver calls such as `x.byebug` | `eval(...)` (`eval-usage-ruby`) |
| PHP | `var_dump(...)`, `dd(...)` | `eval(...)` (`eval-usage-php`) |
| Lua | N/A: no specific general debug call | `load(...)` (`eval-usage-lua`) |
| Bash | N/A: shell tracing is a mode or option | `eval ...` (`eval-usage-bash`) |
| Elixir | `IO.inspect(...)`, `dbg(...)` | `Code.eval_string(...)` (`eval-usage-elixir`) |
| Haskell | N/A: no general debug shape selected | N/A: no standard dynamic-evaluation call selected |
| Solidity | N/A: no general debug or eval shape selected | N/A: no general debug or eval shape selected |
| C | N/A: ordinary output calls would overmatch | N/A: no standard dynamic-evaluation call selected |
| C++ | N/A: ordinary stream and logging output would overmatch | N/A: no standard dynamic-evaluation call selected |
| C# | N/A: `Console.WriteLine` is ordinary output | N/A: no standard dynamic-evaluation call selected |
| Go | N/A: print and logger calls are ordinary output | N/A: no standard dynamic-evaluation call selected |
| Java | N/A: `System.out.println` is ordinary output | N/A: no standard dynamic-evaluation call selected |
| Kotlin | N/A: `println` is ordinary output | N/A: no standard dynamic-evaluation call selected |
| Scala | N/A: print and logger calls are ordinary output | N/A: no standard dynamic-evaluation call selected |
| Swift | N/A: `print` is ordinary output | N/A: no standard dynamic-evaluation call selected |
| Dart | N/A: `print` is ordinary output | N/A: no standard dynamic-evaluation call selected |
| Rust | `dbg!(...)` (`debug-macro-strict`) | N/A: no standard dynamic-evaluation call selected |

Debug and eval entries are syntax policies; they do not resolve callee identity.
The debug rules added for Python, PHP, and Elixir ship at `warning`: `python-breakpoint-strict`, `python-pdb-set-trace-strict`, `php-var-dump-strict`, `php-dd-strict`, `elixir-io-inspect-strict`, and `elixir-dbg-strict`.
Ruby debug rules are omitted because the syntax matcher cannot distinguish a
bare `byebug` call from a receiver method such as `x.byebug`.

### Empty handlers and error swallowing

Every rule ignores comment-only handler bodies.

| Rule IDs | Severity | Languages |
|---|---|---|
| `empty-catch-block`, `empty-catch-block-unbound` | `error` | JavaScript, TypeScript, TSX |
| `empty-except-block`, `empty-except-block-bare` | `error` | Python |
| `empty-catch-block-java`, `empty-catch-block-csharp`, `empty-catch-block-kotlin`, `empty-catch-block-dart`, `empty-catch-block-dart-typed`, `empty-catch-block-php`, `empty-catch-block-cpp`, `empty-catch-block-ruby`, `empty-catch-block-swift` | `error` | Java, C#, Kotlin, Dart, PHP, C++, Ruby, Swift |
| `error-swallow-c-empty-if` | `error` | C |
| `error-swallow-c-void-cast` | `warning` | C |
| `error-swallow-scala` | `error` | Scala |
| `error-swallow-scala-unit` | `warning` | Scala |
| `error-swallow-solidity`, `error-swallow-solidity-error` | `error` | Solidity |
| `error-swallow-elixir`, `error-swallow-elixir-catch` | `error` | Elixir |
| `error-swallow-elixir-discard` | `warning` | Elixir |
| `error-swallow-haskell`, `error-swallow-haskell-infix`, `error-swallow-haskell-handle`, `error-swallow-haskell-try`, `error-swallow-haskell-try-late` | `error` | Haskell |
| `error-swallow-go` | `error` | Go |
| `error-swallow-go-call`, `error-swallow-go-two-value` | `warning` | Go |
| `error-swallow-rust-call`, `error-swallow-rust-ok` | `warning` | Rust |
| `error-swallow-bash`, `error-swallow-bash-redirect` | `warning` | Bash |

Accepted limits:

- Lua has no rule: discarded `pcall(...)` and captured `local ok, err = pcall(...)` both match `function_call`. The schema cannot select by parent kind, so a rule would report handled captures.
- Bash covers plain commands and stderr-redirection forms followed by `|| true` or `|| :`. Pipes, assignment left sides, stdout or combined redirections, compound commands, and `set +e` scope remain unsupported.
- Go covers `_ = err` at `error` and single-result and two-result call discards at `warning`. Type facts are needed to distinguish errors from ordinary values. Unchecked calls and `v, _ := f()` are not covered.
- Rust covers `let _ = call(...)`, bare `.ok();`, and empty `if let Err(_)` at `warning`. Type facts are needed to distinguish error results; arbitrary `Result` tests and non-empty `Err` handling also need control-flow facts.
- Elixir covers `rescue _ -> nil`, `catch _, _ -> :ok`, and `_ = call(...)` at `warning`. Arbitrary handler bodies and bare clauses without an enclosing construct are not matched.
- Haskell covers unit-returning lambda handlers for `catch`/`handle` and `_ <- try` in selected do-block positions at `warning`. Named handlers, broader `Left` branches, standalone case alternatives, and one late-statement position remain unsupported.

These structural limits need type or control-flow facts that pattern rules do not provide.

### Credential rules

Every `hardcoded-credential-*` rule carries the same KEY name regex and the
same VAL literal regexes. A match needs a recognized bare name and a string
literal of at least 16 allowed characters containing a digit. Raw,
triple-quoted, backtick, heredoc and prefixed literals count; interpolated
forms do not. All ship at `error`. Credential and error-swallowing rules set
`exclude_test_paths = true`, so test, spec and fixture paths do not report; the
original JavaScript, TypeScript, TSX and Python `literal`/`declaration` rules
are the exception.

| Language | Rule IDs (`hardcoded-credential-` prefix omitted) |
|---|---|
| JavaScript, TypeScript, TSX | `literal`, and `declaration` for the declaration forms |
| Python | `literal` |
| C | `c`, `c-const-ptr`, `c-ptr`, `c-const-array`, `c-array`, `c-sized-array`, `c-const-sized-array` |
| C++ | `cpp`, `cpp-const-ptr`, `cpp-const-array`, `cpp-ptr`, `cpp-string`, `cpp-const-string`, `cpp-sized-array`, `cpp-const-sized-array`, `cpp-constexpr-auto`, `cpp-const-auto`, `cpp-auto` |
| C# | `csharp`, `csharp-property`, `csharp-property-get`, `csharp-property-init` |
| Dart | `dart`, `dart-declaration`, `dart-typed`, `dart-member`, `dart-member-const`, `dart-member-typed`, `dart-member-const-typed`, `dart-top-level`, `dart-top-level-var`, `dart-top-level-typed`, `dart-top-level-final-typed` |
| Elixir | `elixir`, `elixir-attribute` |
| Go | `go`, `go-short-var`, `go-var`, `go-const` |
| Haskell | `haskell`, `haskell-annotated` |
| Java | `java`, `java-field` |
| Kotlin | `kotlin`, `kotlin-typed`, `kotlin-var`, `kotlin-var-typed` |
| Lua | `lua` |
| PHP | `php`, `php-const`, `php-define`, `php-define-double` |
| Ruby | `ruby` |
| Rust | `rust`, `rust-typed`, `rust-const`, `rust-static` |
| Scala | `scala`, `scala-typed`, `scala-var`, `scala-var-typed` |
| Solidity | `solidity`, `solidity-local`, `solidity-assignment`, `solidity-state` |
| Swift | `swift`, `swift-let`, `swift-var`, `swift-typed-let`, `swift-typed-var` |
| Bash | `bash` |

Bare `eval` matching includes shadowed identifiers. `debug-macro-strict` matches
bare `dbg!` calls only. Handler rules cover their listed known forms, not every
possible handler syntax. Python excludes `ImportError` and
`ModuleNotFoundError` handler shapes. Credential rules do not detect every
secret format.

## Customize and suppress

Use `rules_list` to inspect the active merged definitions. Repository rules
override user rules, which override built-ins. An override replaces the whole
rule by ID.

```sh
varde scan rules seed --json '{"repoRoot":"."}'
varde scan rules list --json '{"repoRoot":"."}'
varde scan test --json '{"rulesDir":".varde-code/rules"}'
```

Use parser-recognized comments for local exceptions:

```javascript
// varde-ignore-next-line console-log-strict -- intentional CLI output
console.log(result);
```

`--apply` executes only explicit pattern rewrite templates. Applied findings
stop blocking. Dirty-file safeguards still apply unless `--force` is set.
