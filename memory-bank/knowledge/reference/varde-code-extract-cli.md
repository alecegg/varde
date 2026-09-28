---
type: reference
status: active
title: "varde-code extract CLI"
related: ["2026-08-12-varde-code-rust-port/parsing-extraction"]
---

# varde-code `extract` CLI reference

Capability reference for the `varde-code extract` command — the multi-language
parsing/extraction entry point of varde-code (the Rust code-intelligence core).

## Invocation

```text
varde-code extract <path> [--verbose]
```

`<path>` is a file or a directory (walked recursively, skipping hidden
entries, `target/`, and `node_modules/`). One JSON document is printed to
stdout; all human-readable log/diagnostic output goes to stderr.

Verbose logging: `-v`/`--verbose` (or `RUST_LOG` with values like
`trace`, `varde_code=debug`).

## JSON contract

A single JSON document on stdout:

```json
{
  "entities": [],
  "symbols": [],
  "diagnostics": []
}
```

All three arrays are always present. stdout never carries anything but this
document — logging is routed to stderr.

### Entity

A top-level structural unit extracted from source. Fields:

| field | type | notes |
|---|---|---|
| `kind` | string | one of the 14 kinds below (snake_case) |
| `name` | string | primary name of the construct |
| `file` | string | path of the source file |
| `span` | object | `start_byte`, `end_byte`, `start_line`, `start_col`, `end_line`, `end_col` (1-based lines, 0-based columns/bytes) |
| `enclosing_function` | string (optional) | nearest enclosing named function/method for control-flow/error entities |
| `method` | string (optional) | Route entities: HTTP method |
| `path` | string (optional) | Route entities: route path |
| `status` | string (optional) | Response entities: HTTP status when derivable |
| `body_shape` | string (optional) | Response entities: body shape (`json`, `send`, ...) when derivable |

Optional fields are omitted from JSON when absent.

### Symbol

A named binding or reference that is not an entity's primary name
(non-redundant with entities). Fields: `kind` (`binding` | `reference`),
`name`, `file`, `span`. `binding` symbols are names introduced by imports;
`reference` symbols are identifiers used in expressions (declared names,
callee identifiers, member properties, and type-context identifiers are
excluded).

### Diagnostic

Per-file skip reports: `file`, `message`, `severity`
(`error` for syntax/binary issues, `info` for unsupported file types).

## The 14 entity/symbol kinds

`function`, `class`, `interface`, `variable`, `parameter`, `export`, `call`,
`literal`, `member_access`, `catch`, `throw`, `control_flow`, `route`,
`response`.

Per-language mapping notes (fixture-driven, superset-safe):

| language | notes / carve-outs |
|---|---|
| TypeScript | reference implementation; routes/responses are Express-style (`app.get("/path")` → route; `res.status(200).json(...)` → response) |
| TSX | shares all TypeScript node kinds; JSX-only constructs are ignored |
| JavaScript | like TS minus interfaces (no `interface` kind) |
| Go | `panic()` → throw, `recover()` → catch (idiomatic equivalents); exports = capitalized top-level names; `mux.HandleFunc` → route; `w.WriteHeader`/`w.Write` → response |
| Java | Spring `@GetMapping("/path")`-style annotations → route; servlet `response.setStatus(n)` → response; `public` top-level types → export |
| C# | minimal-API `app.MapGet("/path", ...)` → route; `Results.Ok/Json(...)` → response; `public` top-level types → export |
| Kotlin | all 14 kinds |
| Swift | all 14 kinds (interfaces = `protocol` declarations) |
| Python | carve-outs: interface, export (no syntactic equivalents); Flask `@app.route("/path")` → route; Flask response helpers → response |
| Rust | carve-outs: catch, route, response (no idiomatic built-ins); `trait_item` → interface; `struct`/`enum` → class; `panic!()` → throw; `pub` items → export |

Coverage-parity check: `cargo test -p varde-code --test coverage_parity
[-- --include <lang1,lang2,...>]` asserts each language's fixtures produce its
required kind set (all 14 unless carved out above). `VARDE_CODE_INCLUDE` env
var is an alternative to `--include`.

## Error handling

- Unparseable files are skipped and reported as per-file diagnostics; the run
  continues and exits 0.
- Skipped-file cases: unsupported file extension (`info` diagnostic), binary /
  non-UTF-8 content (`error`), syntax errors (`error`).
- A missing or unreadable root path is fatal: message on stderr, non-zero exit.

## Example

```text
$ varde-code extract crates/varde-code/tests/fixtures/ts/structural.ts
{"entities":[{"kind":"function","name":"greet","file":"...","span":{...}}, ...],"symbols":[],"diagnostics":[]}
```
