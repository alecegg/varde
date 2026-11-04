# Calibration ranking

`python -m varde_dev.calibrate rank DATASET --rater ID` ranks stored pair
judgments within each `pair_group_id` using Bradley-Terry ratings. Add `--json`
for deterministic machine-readable output. `--compare ID1 ID2` reports Kendall
tau, top/bottom agreement, and discordant pairs. `--plan-next` prints the next
adaptive judging round and the remaining call estimate; it does not run a
client. Rater IDs can name a store `rater_id`, a panel-run lens, or `panel` to
aggregate the three latest lens votes. Planning accepts repeated `--lens FILE`
options or `--lens-count N` to project the calls across configured lenses.

`run_adaptive_loop` accepts an injected `run_round` callback and stops when the
rating stop rule or call budget is reached. The panel runner currently exposes
no public per-round function; its `rate --adaptive` command can adopt this loop
after it exposes one. Live client use remains subject to the panel runner's
usage-window guard.
