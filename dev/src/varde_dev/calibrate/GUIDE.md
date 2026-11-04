# Calibrate quality scores

The calibration tool compares implementations, summarizes labels, checks a
scorer against labels, and estimates one rater's preferences. A person can
calibrate on their own project even when the default golden set is imperfect:
import behavior-equivalent pairs for your tasks and label those. Validation
applies to the language, scorer output, and labels you provide. Small label
sets cannot establish broad statistical confidence.

Everything stays local unless you explicitly run `rate` without `--dry-run`.
Dry-run prepares the panel request without a model call. Live judging requires
both a usage-window file and `VARDE_CALIBRATE_ALLOW_LIVE=1`. A live request
sends the selected provider task text, code snippets, lens/rubric text, and
idiom notes. The run manifest records pair IDs and hashes, not raw snippets.

## Terminal walkthrough

Run `uv run python -m varde_dev.calibrate` from a Varde repository checkout's
root, after `uv sync --locked --all-packages` (usually under a minute on a warm
environment). The module is not a standalone installed command. Dataset
initialization and sample import take seconds; labeling nine pairs usually
takes 2-5 minutes. The sample contains three pair directories per language
(Python, TypeScript, and C#). Each directory imports as a pair of items, so
each language group has six distinct code texts. The pair-only import format
does not share an item across directories. The examples include sensible and
over-split solutions plus behavior-preserving implementation variants. Each
pair includes a behavior test; imported tests are stored, not run by the
importer. Singles are skipped because ordinal labels are not supported.

```sh
set -eu
CAL_DATA="${CAL_DATA:-$(mktemp -d)/calibration}"
uv run python -m varde_dev.calibrate init "$CAL_DATA"
uv run python -m varde_dev.calibrate import "$CAL_DATA" --sample
# Pause at the first item; this exits successfully and keeps the cursor.
printf 'p\n' | uv run python -m varde_dev.calibrate label "$CAL_DATA" --session walkthrough --seed 19 --reason-rate 0
# Resume the same session. The answers are scripted here for a quick smoke run.
printf 'a\nm\n\n%.0s' {1..9} | uv run python -m varde_dev.calibrate label "$CAL_DATA" --session walkthrough --seed 19 --reason-rate 0
# Pause the duel at a one-match budget; resume with the same session.
printf 'a\n\n' | uv run python -m varde_dev.calibrate duel "$CAL_DATA" --group sample-python-price-order --session walkthrough --seed 19 --max-matches 1
uv run python -m varde_dev.calibrate rank "$CAL_DATA" --rater human
uv run python -m varde_dev.calibrate report "$CAL_DATA"
uv run python -m varde_dev.calibrate verify "$CAL_DATA"
```

In normal labeling, enter `a`, `b`, or `t` for A, B, or tie; then choose
confidence (`h`, `m`, or `l`) and optionally enter a reason. `p`, Ctrl-C, or
end-of-file pauses before saving an incomplete response. Re-run `label` with
the same `--session` to resume. Session progress lives in
`DATASET/sessions/`; completed labels are appended to the dataset's label
batches. `duel` also saves resumable state under `sessions/`. Its uncertainty
line shows per-group score intervals and a confidence status. It stops when
every group is confident or has reached its group budget, printing either
`Stopped: confident.` or `Stopped: budget.`. The session-level
`--max-matches` cap pauses the session and prints `Paused.` with the resume
command. Continue with the same session name to resume.

For control questions or distractor examples, designate units before labeling
with unit metadata (`metadata.control = true` / `metadata.distractor = true`,
or `metadata.label_role` set to `control` / `distractor`) or create
`DATASET/label-config.json`, for example:

```json
{"controls":["opaque-control-unit"],"distractors":["opaque-distractor-unit"]}
```

Then use `--control-every N`, `--control-positions POSITION=UNIT_ID,...`, or
`--distractors N`. Controls and distractors are removed from the standard
schedule and selected only for their role. A requested control frequency needs
at least one designated control; the distractor count cannot exceed the
designated distractors. The default reason prompt chance is 0.2; set
`--reason-rate 0` to skip the random reason prompt (you can still enter `r`
after a choice). `--reshow-interval`, `--break-every`, and `--max-minutes`
adjust repetition and pacing. Controls and distractors must already be
designated in unit metadata or in `label-config.json`; these flags schedule
designated units but do not identify which units play those roles.

`rank` computes Bradley-Terry ratings within each `pair_group_id`. To compare
two raters or inspect adaptive next comparisons and a remaining-call estimate,
run:

```sh
uv run python -m varde_dev.calibrate rank "$CAL_DATA" --compare human human
uv run python -m varde_dev.calibrate rank "$CAL_DATA" --plan-next --rater human
```

These options do not call a judge. `report` summarizes agreement, accuracy
intervals, votes, dissent, and over-split results. `validate` compares your latest non-tie labels to your
score JSONL and writes `validation/<language>.toml`. A validation can report
not validated when its sample is too small or thresholds are not met.

## Personal preference profile

Prepare one JSON object per line with an item ID and numeric components, for
example `{"item_id":"opaque-item:a","components":{"size":12,"cognitive":0.7}}`.
Then run:

```sh
uv run python -m varde_dev.calibrate profile "$CAL_DATA" --rater human --components "$CAL_DATA/components.jsonl"
```

The command writes `profile.json`, including weights and a “dislikes most” list
with negative component contributions. Treat this as descriptive: a small label
set can leave the fit under-determined, which the output reports. It does not
change shipped calibration weights. Profile fitting uses training folds only;
held-out accuracy is reported separately.

## Own pairs and scorer validation

`import --pairs PAIR_ROOT` accepts the same exported pair directories used by
the sample importer. Each pair needs two code files, one behavior test, and a
`manifest.toml` with `id`, `pair_group_id`, `language`, `task`, file names,
`license`, and SHA-256 values for all three files. The test file is stored and
its hash is verified, not automatically executed by import. Keep license
information accurate. To use a different split, pass `--split dev`,
`regression`, `test`, or `test-restricted`. Keep personal preference labels
separate from protected evaluation data.

For validation, write score JSONL with one row per labeled unit, mapping its
item IDs to numeric scores and including one shared nonempty calibration ID:

```json
{"unit_id":"opaque-pair","scores":{"opaque-pair:a":72.5,"opaque-pair:b":68.0},"calibration_id":"my-calibration","split":"test"}
```

Then run this command (about a few seconds):

```sh
uv run python -m varde_dev.calibrate validate "$CAL_DATA" --language python --rater human --scores "$CAL_DATA/scores.jsonl"
```

Higher scores predict preference. The default validation minimums are much
larger than this sample; inspect the record's thresholds and agreement instead
of treating a small run as a pass. The `--score-cmd` alternative runs a command
without a shell, appends the dataset path, and reads score JSONL from stdout.

## Optional model panel

`rate` runs a panel and is guarded. `rate --dry-run` never calls a model. Live
runs are refused unless a valid usage window is provided explicitly. The
window-file is TOML with timezone-aware ISO timestamps, a positive call cap,
and a stop rule, for example:

```toml
start = "2026-10-19T09:00:00Z"
end = "2026-10-19T10:00:00Z"
cap_per_hour = 20
stop_rule = "stop_on_first_limit_message"
```

The planned calls for one invocation cannot exceed the cap. The runner records
the stop rule and stops on a provider usage or rate limit. Before a live run,
review the task text, code snippets, lens text, and idiom notes that the
provider will receive. Use `--window-file WINDOW.toml`; the file is required
for every live invocation and there is no default window path.

With lens and idiom-note files prepared, run a dry run locally:

```sh
uv run python -m varde_dev.calibrate rate "$CAL_DATA" --lens "$CAL_DATA/lens.md" --idiom-notes "$CAL_DATA/idiom-notes.md" --dry-run
```

## Local files and backups

Back up the complete dataset directory, including `manifest.toml`, item/unit/
task JSONL, label batches, `sessions/`, `validation/`, `profile.json`, and
`tasks/behaviour-tests/`. `verify` checks stored file digests and manifest
references. Sample and imported behavior tests are retained for your own test
runner. Keep a separate backup before editing labels or deleting sessions.
