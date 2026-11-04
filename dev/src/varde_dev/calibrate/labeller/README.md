# Blind labeller

Run `python -m varde_dev.calibrate label DATASET [options]`. The command writes
resumable session records under `DATASET/sessions/` and appends each completed
comparison through the store's public label-batch API.

## Options and defaults

- `--session NAME`: create or resume that session. Without it, a timestamped
  name is generated.
- `--seed INT`: reproducible unit and side order. By default a random seed is
  saved with the session.
- `--control-every N`: insert a control at each Nth schedule position.
- `--control-positions POSITION=UNIT_ID,...`: place designated controls at
  explicit 1-based positions. Default: no controls.
- `--reshow-interval N`: re-show selected standard units after at least N
  intervening scheduled units. Default: disabled. Re-shows are never adjacent
  to the original.
- `--distractors N`: randomly select N designated distractor units. Default: 0.
- `--reason-rate FLOAT`: seeded chance of explicitly asking for a reason per
  scheduled unit. Default: 0.2. Every unit also accepts `r` after the choice.
- `--break-every N`: suggest a break after every N scheduled units. Default: 20.
- `--max-minutes FLOAT`: warn after this much active session time. Paused time
  does not count. Default: 120 minutes. `--hard-stop-minutes` is an alias.

Control and distractor units are generic dataset data. Designate them either
with unit metadata (`metadata.control = true` or
`metadata.distractor = true`, also accepted as `metadata.label_role = "control"`
or `"distractor"`) or in `DATASET/label-config.json`:

```json
{"controls": ["opaque-control-unit"], "distractors": ["opaque-distractor-unit"]}
```

Designated units are removed from the standard pool and appear only when
selected for their role. `--control-every` requires at least one designated
control; `--distractors N` requires at least N designated distractors.

Pairs save one label. A triple displays and collects its three pair comparisons;
the labeller derives three pair units through the public store import API and
appends three pair labels. Singles are skipped with a clear message because
ordinal labels are not supported. A skipped pair is kept in the session record
and offered once more at the end; the current store does not accept skip labels.

End-of-file or Ctrl-C at any point before a unit is complete pauses the session
without appending its partial response. The cursor remains on that unit. Paused
time is excluded from the hard-stop timer. A completed session can be run again
without changing its completion timestamp.

The display and choice prompt are reusable public interfaces:

```python
display_unit(
    unit: Mapping[str, Any],
    task: Mapping[str, Any],
    items: Mapping[str, Mapping[str, Any]],
    schedule_entry: Mapping[str, Any],
) -> str

prompt_choice(prompt: str = "Choose [a/b/t]: ", *, input_fn: Any | None = None) -> str
```

`display_unit` returns only the task description and anonymous A/B code blocks.
For triple units it includes all three comparisons. It omits item ids, file
names, scores, categories, variants, and metadata. `prompt_choice` returns
`"A"`, `"B"`, or `"tie"`, retrying invalid input; `input_fn` supports scripted
terminals and reuse by the head-to-head mode.
