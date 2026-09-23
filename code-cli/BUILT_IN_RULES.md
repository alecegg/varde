# Built-in scan rules

The built-in pack contains 34 rules: 28 `error` rules and six `info` rules.
There are 27 active default gates, plus one configurable boundary gate.
Rules combine syntax patterns with indexed structural measurements.

```sh
varde-code rules_list --json '{"repoRoot":"."}'
varde-code scan --json '{"repoRoot":".","severityThreshold":"error"}'
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

Structural budgets below are strict upper bounds. Dependency counts and clone
eligibility follow their own evidence rules.

| Rule | Severity | Certified condition |
|---|---|---|
| `function-complexity-gate` | `error` | High-confidence cognitive > 15, cyclomatic > 20, or lines > 60 |
| `file-complexity-hotspot` | `error` | Certified production file complexity > 50 and average per function > 7 |
| `fat-interface` | `error` | One uniquely identified type has more than 15 direct indexed methods; structural fixtures cover 13 languages |
| `too-many-interfaces` | `error` | One class resolves more than 3 same-file interfaces with methods |
| `deep-inheritance` | `error` | Resolved same-file inheritance depth exceeds 3; depth is a lower bound |
| `duplicate-code-clone` | `error` | At least 3 exact-clone members, each over 8 lines and at least 20 syntax tokens |
| `low-fan-in-high-fan-out-file` | `error` | Certified fan-out is at least 15 and fan-in is at most 2 |
| `circular-import` | `error` | Two certified dependency units import each other directly |
| `unresolved-local-import` | `error` | A certified relative source import has no supported target |
| `dependency-boundary` | `error` | A certified import crosses configured literal directory prefixes |

The tested `fat-interface` structural cases cover TypeScript, Java, C#, C++,
Python, Ruby, Kotlin, Swift, Dart, Scala, PHP, Rust, and Go.

Certified relative dependency units cover JavaScript, TypeScript, TSX, Dart,
and Solidity source paths. Go uses module-aware package-directory units.
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

```sh
varde-code rules_seed --json '{"repoRoot":"."}'
# Edit .varde-code/rules/dependency_boundary.toml:
# Replace its strings table with:
# strings = { source_prefix = "src/core", target_prefix = "src/data" }
varde-code scan --json '{"repoRoot":".","gateRules":["dependency-boundary"]}'
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

The syntax pack has 35 declared rule-language pairs. Each pair has positive and
negative coverage in the regression fixtures.

| Rule family | Rule IDs | Languages |
|---|---|---|
| Dynamic evaluation | `eval-usage` | JavaScript, TypeScript, TSX, Python |
| Empty handlers | `empty-catch-block`, `empty-catch-block-unbound` | JavaScript, TypeScript, TSX |
| Empty handlers | `empty-except-block`, `empty-except-block-bare` | Python |
| Empty handlers | `empty-catch-block-java`, `empty-catch-block-csharp`, `empty-catch-block-kotlin`, `empty-catch-block-dart`, `empty-catch-block-dart-typed`, `empty-catch-block-php`, `empty-catch-block-cpp`, `empty-catch-block-ruby`, `empty-catch-block-swift` | Java, C#, Kotlin, Dart, PHP, C++, Ruby, Swift |
| Debug syntax | `debug-statement-strict` | JavaScript, TypeScript, TSX |
| Debug syntax | `debug-macro-strict` | Rust |
| Console advisory | `console-log-strict` | JavaScript, TypeScript, TSX |
| Credential literals | `hardcoded-credential-literal` | Python, JavaScript, TypeScript, TSX |
| Credential declarations | `hardcoded-credential-declaration` | JavaScript, TypeScript, TSX |

All syntax rules are `error` except `console-log-strict`, which is `info`.
Bare `eval` matching includes shadowed identifiers. `debug-macro-strict` matches
bare `dbg!` calls only. Handler rules cover their listed known forms, not every
possible handler syntax.
Empty-handler rules ignore comment-only bodies. Python excludes
`ImportError` and `ModuleNotFoundError` handler shapes. Credential rules match
recognized bare names and strings of at least 16 allowed characters containing
a digit. They do not detect every secret format.

## Customize and suppress

Use `rules_list` to inspect the active merged definitions. Repository rules
override user rules, which override built-ins. An override replaces the whole
rule by ID.

```sh
varde-code rules_seed --json '{"repoRoot":"."}'
varde-code rules_list --json '{"repoRoot":"."}'
varde-code test --json '{"rulesDir":".varde-code/rules"}'
```

Use parser-recognized comments for local exceptions:

```javascript
// varde-ignore-next-line console-log-strict -- intentional CLI output
console.log(result);
```

`--apply` executes only explicit pattern rewrite templates. Applied findings
stop blocking. Dirty-file safeguards still apply unless `--force` is set.
