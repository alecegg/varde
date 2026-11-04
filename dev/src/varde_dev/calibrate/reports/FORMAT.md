# Calibration report formats

`report <dataset> [--by category,language,lens] [--over-split-category b] [--json]`
reads the store's manifest, item and unit JSONL files, and manifest-listed label
batches. Each label's `choice` is first mapped through `order_shown` to an item
id. If `order_shown` is absent, the reader uses `a_item_id`/`b_item_id`, then
matches `a_sha256`/`b_sha256` to item `content_sha256`. All rater comparisons,
panel votes, margins, dissent and validation compare those item ids in the
unit's canonical `item_ids` order. A/B are display positions, not stable sides.

The report emits agreement and kappa, per-lens/category/variant accuracy tables
with Wilson 95% intervals and deterministic task-cluster bootstrap intervals,
panel vote vectors/classes/dissent/margins, labelled rates by the requested
metadata fields, dissent rates per over-split variant and lens, and an
over-split table with one row per lens vote. The over-split table includes only
items whose metadata category equals `--over-split-category`; the default is
`b`. No corpus-specific variant name is assumed. Bootstrap defaults are seed
0 and 2,000 replicates.

`validate <dataset> --language L --rater ID (--scores FILE | --score-cmd CMD)`
compares the latest non-tie label for each unit against the scores. The optional
`--score-cmd` is split using shell-style quoting, run without a shell, and gets
the dataset path appended as its last argument. It must print score JSONL to
stdout. `--category-b` defaults to `b`; `--held-out-splits` defaults to
`test,held-out`. Validation defaults in `config.py` are 40 non-tie units, 20
category `b` units, 15 held-out units, 10 repeated units, accuracy 0.85, Wilson
lower bound 0.75, cluster-bootstrap lower bound 0.75, kappa 0.65, category
`b` accuracy 0.90, and self-consistency 0.90. Bootstrap defaults are seed 0
and 2,000 replicates. The category name and held-out splits can be overridden
by the command; callers can pass a replacement settings mapping to
`validation_record`.

Self-consistency uses every non-skipped label from the named rater for each
repeated unit, canonicalizes each choice to an item id, and counts a repeated
unit consistent only when all its mapped choices agree. Accuracy uses the
latest timestamped non-tie label once per unit. `n_units` counts distinct
non-skipped labelled units; `n_non_tie` counts distinct non-tie units with
matching score rows. The saved TOML record at `validation/<language>.toml` is
marked stale only if its previously stored `validated_against.calibration`
differs from the current score rows' calibration id. The record date is
derived from label timestamps.

## Scores JSONL

Each nonblank row represents a unit and maps **item ids** to numeric scores:

```json
{"unit_id":"pair-17","scores":{"item-a":72.5,"item-b":68.0},"calibration_id":"cal-1","formula":"vq1","profile_sha256":"none","split":"test","task_id":"task-4"}
```

`unit_id`, a `scores` object containing both unit item ids, and one nonempty
`calibration_id` shared by the file are required. Higher item scores predict
that item as preferred; equal scores predict a tie. Optional `formula`,
`profile_sha256`, `split`, and `task_id` are copied or used in the record.
Split names `test` and `held-out` count toward the held-out minimum by default.
The format is independent of the code module and scorer implementation.
