# Write budget

This budget sets a maximum amount of data written for common operations. Values
are in `clis/write-budget.toml`; component checks use those values directly.

| TOML key | Operation | Maximum |
| --- | --- | ---: |
| `toz_capture_ratio_x` | Capture a 64 KiB result | 14 times captured bytes |
| `toz_prune_healthy_bytes` | Healthy maintenance pass | 44,000 bytes |
| `toz_prune_tombstone_ratio_x` | First pass over a tombstone-heavy store | 0.275 times pre-prune database size |
| `toz_prune_runaway_second_pass_bytes` | Second pass after runaway maintenance | 44,000 bytes |
| `watch_reconcile_idle_bytes` | Idle reconciliation | 5,504 bytes |
| `map_cold_fixed_bytes` | Cold index build, fixed cost | 581,042 bytes |
| `map_cold_bytes_per_file` | Cold index build, per file | 995 bytes |
| `map_one_file_bytes` | Index one changed file, fixed cost | 196,608 bytes |
| `map_one_file_per_file_bytes` | Index one changed file, per indexed file | 151 bytes |
| `map_clean_rebuild_bytes` | Rebuild an unchanged index | 5,504 bytes |
| `friction_add_bytes` | Add one friction record | 320,000 bytes (about 313 KiB) |
| `msg_send_bytes` | Send one inbox message | 8 KiB |

## Typical day

The `[typical_day]` profile records the expected operation counts. Its estimated
writes are calculated from those counts and the operation limits. The cold index
build uses its 581,042-byte fixed cost plus 995 bytes per file for 1,200 files.
Each one-file map operation uses its 196,608-byte fixed cost plus 151 bytes per
indexed file; with 20 operations at 1,200 files this is 7,556,160 bytes. Capture
size is multiplied by the capture ratio. The typical-day total is 71,341,826
bytes, below the profile's 1.0 GB daily ceiling. The first incremental edit
after a cold build is excluded from the budget. A primed branch switch that
reparsed 110 files measured about 8.07 MB written and is also excluded because
the integration test cannot measure it cheaply and deterministically.

The profile keys are `capture_count`, `capture_bytes_each`,
`healthy_prune_count`, `runaway_second_pass_count`, `idle_reconcile_count`,
`cold_map_file_count`, `one_file_map_count`, `clean_map_rebuild_count`,
`friction_add_count`, `msg_send_count`, and `ceiling_bytes`.

## Updating a budget

Measure the operation using its component check and a representative fixture.
Set a ceiling with headroom for normal variation, then update the matching key
and this table together. Adjust the daily profile only when typical operation
counts have changed. Keep the daily estimate below its ceiling.

## Running the checks

Use the project's usual test runner to run the component test named
`write_budget` after changing a value. Confirm it passes at the normal scale,
then run it with `VARDE_WRITE_BUDGET_SCALE` set to `0.01` to confirm an operation
exceeds its reduced limit. The test also verifies that each configured key is
documented and that the daily estimate is within its ceiling.
