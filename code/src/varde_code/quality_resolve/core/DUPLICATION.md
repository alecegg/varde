# Resolver duplication

The quality resolver copies the private `_callee_key` normalizer from
`index/resolve/calls.py` rather than importing it. It uses `ImportIndex.match`
for direct import targets. Imports are direct only: aliases can bind a receiver,
but aliases and re-exports are not followed transitively.

`resolve_calls` is not run. This resolver has a scan-only cascade, filters
overloads by known arity, and retains ambiguity and pass provenance that
`calls.py` discards. Receiver lookup uses L1 `receiver_text`, a dotted
identifier chain, falling back to legacy `receiver` only when that field is
absent. Its first segment matches an import hook's `binding`. Lookup is
scoped to those bound files, or to the current enclosing type for a single
segment `self`, `this`, or `cls` receiver. `super` and member chains such as
`self.field` remain opaque. A receiver that is exactly an import binding matches
module-level functions; if that binding itself names a type in the bound files,
it matches that type's owned methods (for example Java `import q.B` and C# static
using). A two-segment bound receiver may name a type (`mod.Foo.f`); longer
chains remain opaque. Same-file type names scope qualified methods. Unknown
variable receivers remain opaque.
Namespace lookup is scoped to the caller's explicit package or namespace facts
and direct imports. Type lookup consumes facts-2 `types` records (`id`, `name`,
`kind`, `line`, `qualifier`) across same-file, import, and supported package
passes. Creation sites and Python type calls map to owner-matched initializers
by arity; absent initializers fall back to the type id. C++ qualified types match
their recorded scope, while receiver lookup uses function owners and qualifiers
to retain namespace distinctions. Type and bound-file function details
participate in per-file digests.

For Java, C#, Kotlin, Scala, and Swift unqualified namespace function lookup
accepts owned methods only when the owner is the caller's type or an enclosing
type; ownerless top-level functions remain eligible. Inheritance is not
represented in these facts, so calls that require inherited-member lookup stay
opaque. Adding inheritance facts is a port-back candidate.
When a caller has no function record, the resolver cannot infer its enclosing
type, so owned methods in other files are not eligible. Owner matching uses
simple type names, so same-named types in distinct namespaces can be conflated.

## Language extension hook

Before resolving a file, core imports
`varde_code.quality_resolve.langs.<language>` when that module exists. It may
define `import_bindings(spec, importer_path, file_set, context) -> list[dict]`.
Each dict has `path` (a repository-relative path in `file_set`), `names` (a
list of unqualified callee names brought into scope, or `"*"` for every
function declared in that file), optional `aliases` (a dict mapping visible
unqualified names to target function names), `binding` (the receiver name
for the file, or `None`), and optional `owner` (a non-empty type name declared
in `path`). Names in `names` use the same visible and target
name. `spec` is an L1 import-spec mapping, `importer_path` is a
repository-relative path, `file_set` is the sorted tuple of repository-relative
source paths, and `context` is the facts-by-file mapping passed to `prepare`.
Malformed results raise `TypeError` naming the language and spec. The hook is
called more than once per spec, during resolution and digest construction, so
it must be pure. When a non-empty binding list is returned, it exclusively
defines target paths, imported names, and receiver bindings for that spec.
Several matching candidates remain ambiguous.

Examples of language semantics:

- Python `from b import y`: `{"path": "b.py", "names": ["y"], "binding": None}`.
- Python `from lib import work as w`: `{"path": "lib.py", "names": [], "aliases": {"w": "work"}, "binding": None}`.
- TypeScript `import { a as b } from './m'`: `{"path": "m.ts", "names": [], "aliases": {"b": "a"}, "binding": None}`.
- Python `import b as m`: `{"path": "b.py", "names": [], "binding": "m"}`.
- C++ `#include "h.h"`: `{"path": "h.h", "names": "*", "binding": None}`.
- Java `import q.B`: `{"path": "q/B.java", "names": ["B"], "binding": "B", "owner": "B"}` for the constructor and type receiver.
- C# `using Alias = Q.B;`: `{"path": "B.cs", "names": [], "binding": "Alias", "owner": "B"}`.
- Go `import "x/pkg"`: `{"path": "x/pkg/pkg.go", "names": [], "binding": "pkg"}`.
- Rust `use crate::a::f`: `{"path": "a.rs", "names": ["f"], "binding": None}`.

If `import_bindings` is absent or returns `[]`, core keeps the existing
behavior: `import_targets(spec, importer_path, file_set, context)` may return
candidate paths, then `ImportIndex.match` supplies the fallback. Unqualified
calls use the strict imported name/alias/`*` rule, and module-only imports bind
qualified receivers. Resolution digests include the binding names,
receiver names, candidate paths, and candidate facts, scoped to the importing
file; changing those inputs invalidates that file's digest.

Resolution digests include the hook's candidate paths and their facts, but not
the hook implementation identity. Changing hook logic without changing its
candidate paths or their facts may therefore leave digests unchanged; digests
track per-input resolution dependencies rather than resolver code versions.

The adapter uses a prebuilt declaration id map for its cross-file fallback.

## Cost

On this machine, `prepare` took 0.815 s for a synthetic 2,000-file input
(one callable per file, no imports or call sites). This includes the per-scan
global index and input-digest construction; it is a single wall-time sample.
After sharing file ids, resolved imports, package membership, per-language
repo context, and type records, `prepare` took 7.437 s for 5,000 synthetic
Java files (one distinct package per file, no functions, imports, or call
sites). This also includes the per-scan global index and is a single wall-time
sample; the namespace digest still scales with the size of each language's
repo-wide callable and type context.
