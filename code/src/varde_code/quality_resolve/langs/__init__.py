"""Optional quality-resolver language extensions discovered by language name.

An ``import_targets(spec, importer_path, file_set, context) -> list[str]`` hook
may return candidate repository-relative target paths.

Core imports ``varde_code.quality_resolve.langs.<language>`` when resolving a
file. A language module may define ``import_bindings(spec, importer_path,
file_set, context) -> list[dict]``. Each result has ``path`` (a path in
``file_set``), ``names`` (a list of unqualified callee names, or ``"*"`` for
every function declared in that file), optional ``aliases`` (a mapping from
visible unqualified names to target function names), ``binding`` (a
receiver name or ``None``), and optional ``owner`` (a non-empty type name in
the bound file). ``names`` keeps identical visible and target names;
``aliases`` can expose a different target name. These results exclusively
define targets, imported names, and
receiver bindings for that spec when non-empty. For example, Python
``from b import y`` binds ``{"path": "b.py", "names": ["y"], "binding":
None}``; Python ``from lib import work as w`` binds ``{"path": "lib.py",
"names": [], "aliases": {"w": "work"}, "binding": None}``; ``import b as m``
binds ``{"path": "b.py", "names": [], "binding": "m"}``; TypeScript
``import { a as b } from './m'`` uses ``{"path": "m.ts", "names": [],
"aliases": {"b": "a"}, "binding": None}``; C++ ``#include "h.h"`` binds
``{"path": "h.h", "names": "*",
"binding": None}``; Java ``import q.B`` binds ``{"path": "q/B.java",
"names": ["B"], "binding": "B", "owner": "B"}`` for the constructor and
type receiver; C# ``using Alias = Q.B;`` binds
``{"path": "B.cs", "names": [], "binding": "Alias", "owner": "B"}``; Go
``import "x/pkg"`` binds ``{"path": "x/pkg/pkg.go", "names": [],
"binding": "pkg"}``; Rust ``use crate::a::f`` binds ``{"path": "a.rs",
"names": ["f"], "binding": None}``.

Call sites may include ``receiver_text``, the receiver's dotted identifier
chain (for example ``mod``, ``ns.Foo``, or ``self``); its first segment is
matched against the hook's ``binding``. A missing ``receiver_text`` uses the
legacy ``receiver`` field, while an explicit ``None`` means an unqualified
call. A receiver binding with ``owner`` resolves only to that type's methods.

``spec`` is an L1 import-spec mapping, ``importer_path`` is the
repository-relative source path, ``file_set`` is the sorted tuple of
repository-relative source paths, and ``context`` is the facts-by-file mapping
passed to :func:`prepare`. A malformed result raises ``TypeError``. The hook
is called more than once per spec and must be pure. If the hook is absent or
returns an empty list, core uses its existing ``import_targets`` hook and
``ImportIndex.match`` behavior.
"""
