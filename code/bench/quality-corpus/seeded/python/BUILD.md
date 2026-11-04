# Python seeded item build

This directory is self-contained: it includes the behavior test, all six version files, the mutation spec, and the layered profile. The gaming variants were hand-authored. Rerunning their behavior and mutation checks does not depend on an external sample directory.

## Variants

- `sensible.py` preserves the sample implementation as the comparison point.
- `tiny.py` splits order checks, customer/items/code extraction, each item field check, price rounding, line construction, discount parts, report lines, and result assembly into small helpers. `process_order` coordinates those helpers.
- `namematched.py` has the same call-tree shape as `tiny.py`, with business-like names that misdescribe their implementations. For example, formatting or validation helpers use names suggesting shipping, promotion, or invoice work.
- `padded.py` adds entry, dispatch, and gate wrappers for order validation, item normalization, discount, shipping, and report creation.
- `monolith.py` keeps validation, calculations, item formatting, and report formatting in one `process_order` body.
- `sizematched.py` is a hand-authored, single-body control that inlines order processing and uses intermediate values and condition variables. At 819 tokens versus 860 for sensible, it is 4.8% smaller.

## Measurements and bands

Command: `uv run python code/bench/quality-corpus/tools/item_targets.py code/bench/quality-corpus/seeded/python`

| File | Tokens | Functions | Layered band results |
| --- | ---: | ---: | --- |
| sensible.py | 860 | 9 | Misses per-function token bands (16, 22, 20, 247, and 175 vs 30-160). The declared API is `process_order`; the checker expects `solution`. |
| tiny.py | 1,204 | 31 | Function count, helper sizes, depth 6, and fanout 10 meet their bands. `process_order` is 103 tokens and 11 rows, over 90 tokens and 10 rows. |
| padded.py | 1,055 | 24 | Depth 6 and fanout 6 meet their bands. Function count is 24 vs 14-22; the short forwarding helpers and inherited large helpers miss the 30-130 token band. |
| monolith.py | 769 | 1 | One-body form is met. The function has 767 tokens vs the layered minimum of 1.3x sensible (1,118); several lines exceed 100 columns. |
| sizematched.py | 819 | 1 | Whole-file and function tokens are within sensible ±5%; single-body control shape is met. Two lines exceed 100 columns. |
| namematched.py | 1,204 | 31 | Matches tiny's function count, call-tree shape, depth 6, and fanout 10. `process_order` is 103 tokens and 11 rows, over 90 tokens and 10 rows. |

The item checker also reports the shared `process_order` / expected `solution` entry-name mismatch for every version. The public name remains `process_order` to satisfy the behavior test.

## Checks

Run from the repository root:

```sh
for variant in sensible tiny padded monolith namematched sizematched; do
  SAMPLE_MODULE_PATH="code/bench/quality-corpus/seeded/python/${variant}.py" python3 code/bench/quality-corpus/seeded/python/behaviour_test.py
done
uv run python code/bench/quality-corpus/tools/item_targets.py code/bench/quality-corpus/seeded/python
uv run python code/bench/quality-corpus/tools/mutate_check.py --item code/bench/quality-corpus/seeded/python --variant sensible.py --mutants code/bench/quality-corpus/seeded/python/mutants.toml
md5 -r code/bench/quality-corpus/seeded/python/{sensible,tiny,padded,monolith,namematched,sizematched}.py
```

All six behavior runs passed (6 tests each). Mutation check: 22 mutants, 22 killed, 0 survived, 0 broken, 0 unapplied, and 0 equivalent. The six version files have distinct MD5 hashes. The fixed behavior test does not separately establish every rule in the task specification.
