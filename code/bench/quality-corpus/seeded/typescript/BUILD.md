# TypeScript seeded order sample

## Construction

- The corpus directory is self-contained: it includes the sensible source, test harness, profile, and mutation spec. Variant construction and verification can be reproduced from this directory without `/private/tmp` or any external sample files. The variant sources below were hand-authored.
- `tiny.ts` hand-splits order checks, catalog checks, stock/price validation, line construction, pricing stages, and report assembly into small helpers. Several orchestrators remain larger than the tiny profile cap; the source is deliberately over-split into many single-purpose functions.
- `padded.ts` adds forwarding layers around processing and report generation. It misses helper token limits because its retained validation and pricing helpers are larger than the profile allows.
- `monolith.ts` places order validation, catalog and stock checks, pricing, discounts, tax, and shipping in one long `processOrder` body. The exported report function formats all rows inline; no other helper functions remain.
- `sizematched.ts` combines validation, catalog checks, line pricing, discounts, tax, and shipping into one long `processOrder` body; report formatting is also inlined into one loop-based function. Its file token count is within 5% of `sensible.ts`, and its two long function bodies provide the intended unstructured control.

## Verification

Commands run from the repository root:

```sh
SAMPLE_MODULE_PATH="$PWD/bench/quality-corpus/seeded/typescript/<variant>.ts" node code/bench/quality-corpus/seeded/typescript/behaviour_test.ts
uv run python code/bench/quality-corpus/tools/item_targets.py code/bench/quality-corpus/seeded/typescript
uv run python code/bench/quality-corpus/tools/mutate_check.py --item code/bench/quality-corpus/seeded/typescript --variant sensible.ts --mutants code/bench/quality-corpus/seeded/typescript/mutants.toml
```

The shared behaviour test passed for `sensible`, `tiny`, `padded`, `monolith`, `namematched`, and `sizematched` (4/4 cases each). Mutation check: 25 killed, 0 survived, 0 broken, 0 unapplied, 0 equivalent.

## `item_targets.py` measurements

| File | Whole-file tokens | Functions | Findings / missed bands |
| --- | ---: | ---: | --- |
| sensible.ts | 1186 | 14 | Not fully in sensible band: `money` is 29 tokens, `invalid` is 18, `processOrder` fan-out is 7; further findings include undersized report helpers and the large `priceItems` (369 tokens, 29 rows). |
| tiny.ts | 2043 | 48 | Count (28-72) passes. Core checks and pricing/report steps are split into small helpers; `reportRows` remains above the 90-token helper cap. |
| padded.ts | 1289 | 19 | Count (14-22) passes. Misses helper token band (30-130), chain depth/fan-out, and has remaining core helpers outside its target sizes. |
| monolith.ts | 1143 | 2 | One long `processOrder` body contains validation and pricing; report formatting is inline in the second exported function. |
| namematched.ts | 1933 | 47 | Count (28-72) passes. The wrappers have domain-sounding names but forward the unchanged order through the chain; other retained core helpers exceed the 90-token cap. |
| sizematched.ts | 1198 | 2 | Whole-file tokens are 1.0% above sensible (1198 vs. 1186); combined function tokens are 1088 vs. sensible 1076 (1.1% above). Both are within about 5%; the layered checker’s strict function-token band (±10%) also passes. The single-function control band is not applicable to the requested few-function variant; the source uses two long bodies. |

The sample's smoothed source itself is outside several layered sensible bands, including 7-20 functions with per-function 30-160 tokens and entry fan-out <=6. That limits how closely the gaming variants can satisfy size/count targets while retaining the source implementation.
