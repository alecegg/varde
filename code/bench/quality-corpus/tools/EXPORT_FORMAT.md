# Provisional dataset-store export format

This format is provisional until `qs-calibrate-tool` publishes `store/FORMAT.md`. It follows that task's current import contract: one opaque pair-id directory containing `a.<ext>`, `b.<ext>`, `behaviour_test.<ext>`, and `manifest.toml`.

The manifest stores the opaque item id, `pair_group_id` (the task id or pair group, so samples can be ranked head to head), language, task text when available, relative file paths, SHA-256 digests for all three files, and the license when supplied by the source item or its manifest. Pair ids are derived from file contents and extensions, not paths, so they are stable across machines.

For category (b) pairs that include the `padded` variant, the manifest also records `padded_evidence` as a TOML boolean. It is `true` for rich tasks and `false` for small tasks. Other exports omit the field, so existing manifests remain valid.

A category (b) pair whose right side is an `alt-good` preference version records `role = "alt-good"` and `preference_neutral = true`. Such a pair is two good solutions in different styles, not a quality delta: the export writes no direction, label, or ordered side, and calibration must not score it as one. A pair with `right_role = "alt-good"` that omits `preference_neutral = true` is rejected. The exporter rejects an `alt-pipeline`, `alt-table`, or `alt-class` file on either side unless that side has role `alt-good`; it also rejects `alt-good` on the left side or on a non-alt file. The item checker reports `alt_good_on_sensible` when `alt-good` is assigned to the `sensible` version.
