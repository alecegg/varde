# Go gaming variants

This directory is self-contained: it includes the Go module, fixed behavior test, version manifest, mutation spec, and all six source variants. The variants are hand-authored Go sources. Reproducing their checks does not require `/private/tmp/qs-run1` or any other external sample files.

- `tiny.go`: split validation, pricing, policy decisions, and report formatting into 35 small single-purpose functions. The entry has seven direct calls, the deepest call chain is within the layered band, and the file meets the tiny count, token, row, fanout, and forwarder bands.
- `namematched.go`: uses a 24-hop forwarding ladder with descriptive operational names; the forwarding functions do no work.
- `padded.go`: routes validation, catalog lookup, discount, tax, and shipping through ten additional forwarding wrappers (two layers per operation).
- `monolith.go`: moves row validation into a private validator, inlines catalog checks and pricing policies into `ProcessOrder`, and retains the public validation wrapper.
- `sizematched.go`: inlines validation, catalog pricing, discounts, tax, shipping, and reporting into one long `ProcessOrder` body with a local row type and an exported function-valued `ValidateOrder` adapter. Its long, linear body is deliberately unstructured.

Checks run from the repository root:

```sh
uv run python code/bench/quality-corpus/tools/behaviour_runner.py --items code/bench/quality-corpus/seeded/go --check
uv run python code/bench/quality-corpus/tools/item_targets.py code/bench/quality-corpus/seeded/go
uv run python code/bench/quality-corpus/tools/mutate_check.py --item code/bench/quality-corpus/seeded/go --variant sensible.go --mutants code/bench/quality-corpus/seeded/go/mutants.toml --jobs 4 --json
```

The behavior runner passed all six declared versions. Their MD5 digests are distinct: sensible `25e2f949913d060c749ef471bfe200b0`, tiny `4445766b0de6adefff2716838f513847`, padded `6a473dcbe3af8cca46b3754445f02976`, monolith `36d088383c5064d9821b151faafadf25`, namematched `4f078a42c73627dc2fe1500959d2408d`, and sizematched `102ab378170deb3e7503f8188b6c3c75`.

`item_targets.py` measured whole-file tokens / functions: sensible 791/7, tiny 1402/35, padded 935/17, monolith 769/3, namematched 1291/32, sizematched 775/2. Sensible misses function token bounds (ValidateOrder 221, ProcessOrder 388, shippingAmount 27); this is the phase A sample/profile mismatch. Tiny meets every tiny band: 35 functions, helpers and entry 14-90 tokens, at most 9 rows per function, fanout 7, and required forwarders. Padded meets count, depth, and fanout bands; it misses helper token limits because its forwarding wrappers are 14-16 tokens, the entry token cap, the retained 221-token validator, and entry/signature parity. Monolith has three measured functions, including a 484-token entry, and misses its one-function requirement. Sizematched is within 10% of sensible for file tokens (775 vs 791) and measured function tokens (758 vs 766); the checker counts its exported `ValidateOrder` adapter as a second function (22 tokens), so it misses the one-function count and shared-entry parity. That adapter preserves the required public API. Namematched misses depth (27 vs 3-8), entry fanout, and per-function token limits.

Mutation result: 23 entries, 17 killed, 6 equivalent, 0 survived, 0 unapplied, and 0 broken. Equivalent mutants are `row-cap-21` (21 rows must contain a repeated SKU among the three allowed SKUs), the discount boundaries at 2499 and 7499 (all merchandise subtotals are 25-cent multiples), both shipping boundaries at 2499 and 7499 (those discounted subtotals are unreachable under the catalog and rounding rules), and the logically identical SKU predicate. The row-cap mutant is equivalent in the task’s observable behavior because the test asserts only `err != nil` for the 21-row case; it does not check the error message. Exhaustive enumeration of permitted quantities for all three distinct SKUs found no valid order yielding either shipping boundary amount.
