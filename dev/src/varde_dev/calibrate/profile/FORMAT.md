# Personal preference profile format

`python -m varde_dev.calibrate profile <dataset-dir> --rater ID
--calibration CALIBRATION.toml` asks `varde code score` to build item
components. Each item in `items.jsonl` needs a `facts_path` string naming its
facts JSONL file; relative paths resolve from the dataset directory. The
calibration file is required because `varde code score` has no calibration
default. By default the command runs
`varde code score --facts {facts} --calibration {calibration} --debug` once per
item. `--scorer COMMAND` or `VARDE_CALIBRATE_SCORER` can replace this command
template. It is split with `shlex`; placeholders `{item_id}`, `{item_path}`,
`{facts}`, and `{calibration}` are substituted in each argument. The scorer
must print a JSON response with a top-level `breakdown` array. Component
`name` and `debt` values from that whole-item scope breakdown become the item
components. File-level breakdowns are not summed because they omit interactions
between files in one scope. A nonzero exit or invalid output identifies the
item and fails the command.

`--components FILE` selects a JSONL component override instead; if both the
scorer and component file are provided, the component file wins. The override
reads one JSON object per line from `FILE`:

```json
{"item_id":"item-1","components":{"cognitive":0.7,"size":4}}
```

Each item id is unique. Component names map to finite numbers. Missing component
values on an item are treated as zero. The tool reads the calibration labels,
units, and items with the shared reports dataset reader. It converts `A` and `B`
using each label's `order_shown`, then fits the requested rater's pairwise
choices. Ties contribute one half observation.

The command writes `profile.json` in the dataset directory. Version 1 has these
fields:

- `schema_version`: integer `1`.
- `rater_id`: requested rater id.
- `components`: sorted component names.
- `weights`: component keyed objects with standardized logistic `weight`,
  `standard_error`, 95% Wald `interval_95`, input `mean`, and population
  standard deviation `scale`. Constant components have zero weight and error.
- `constant_components`: sorted names with zero variance.
- `held_out_pair_accuracy`: accuracy on held-out pairs, or `null` when the
  deterministic fold has no held-out pairs. Ties score one half.
- `under_determined` and `under_determined_components`: true and the active
  component names when training matches are fewer than five per active
  component; constant components are excluded.
- `dislikes_most`: up to ten lowest-rated items per group from the shared
  Bradley-Terry ratings, with raw component values and up to three negative
  weighted contributions relative to the group's highest-rated item; also up
  to ten observed pairs with the lowest fitted probability for their label.
- `input_hashes`: SHA-256 hashes of canonical, sorted records for this rater's
  labels and either the exact component file bytes or canonical scorer-derived
  component values.
- `fit_settings`: algorithm and fixed deterministic fit settings.

The logistic model is `P(x beats y) = sigmoid(w · (x - y))` after population
standardization. It uses L2 strength `1.0`, 200 fixed Newton/IRLS iterations,
and no intercept. Held-out fold 0 of 5 is selected by SHA-256 of the canonical
group and item ids. The reported weights are descriptive personal preferences;
they do not alter shipped calibration or gating.
