# Python and TypeScript call ground truth

The matching rule is fixed before export: a call targets the concrete callable
declaration the static tool resolves. Constructor calls target the class
constructor declaration. For overloads, use the selected overload's unique
implementation body when one exists. A call typed only against an interface or
abstract declaration with possible runtime implementations stays dynamic and
unknown; it is not remapped to the base contract. Conflicting or unavailable
targets stay unknown.

Jedi and the TypeScript checker provide target declarations. For Python, Jedi
is queried at every call, including dynamic and higher-order syntax; one
unambiguous in-repository definition is retained, an external definition is
marked `external`, and no or ambiguous definitions are `unknown`. AST syntax
classification supplies only the call-class label (`same_file`, `imported`,
`constructor`, `member`, `dynamic`, or `higher_order`); it never supplies a
target. Thus a call can retain a dynamic or higher-order class while still
having a tool-derived target. The TypeScript worker uses the checker
declaration for targets and syntax/checker results for class labels.

Unknown dynamic and higher-order calls are counted separately and receive two
independent, unfilled reviewer slots. No reviewer target is inferred from the
measured edge.

`export.py` runs Jedi and the TypeScript compiler API against source roots in
`repos/python-ts.toml`. `generate.py` makes the role-disjoint, six-class
stratified sample with the checked-in seed. Only development records are
written in this repository. Frozen test records go to the plan's restricted
agent-memory directory; the repository stores only their SHA-256 manifest.

Every record carries the name called at the site in `call_name`, and a sample
keeps `(repo, file, line, call_name)` unique. `generate.py` fills an even quota
per call class where the pinned repositories supply one, drawing sites
round-robin across the split's repositories so a repository stays under its
share when three or more are available. Classes that cannot reach the quota
are reported in the summary's `sample_composition` and in the feasibility note
rather than padded, and the rest of the split is filled from the real surplus
so each split still holds 300 sites. Vendored and test directories are
excluded during export; the residual test-path share is reported too.
